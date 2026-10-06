from __future__ import annotations

import ast
from dataclasses import dataclass

import pytest

from src.market_environment.application.ports import (
    MarketEnvironmentUnitOfWork as UnitOfWorkPort,
)
from src.market_environment.database import DatabaseSettings
from src.market_environment.infrastructure.persistence.postgres import (
    DatabaseSchemaCompatibilityError,
    MINIMUM_SCHEMA_VERSION,
    MarketEnvironmentUnitOfWork,
    PostgresConnectionFactory,
    REQUIRED_RUNTIME_TABLES,
)


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return list(self.value)


class FakeValidationConnection:
    def __init__(self, *, tables=None, version=MINIMUM_SCHEMA_VERSION) -> None:
        self.tables = REQUIRED_RUNTIME_TABLES if tables is None else tables
        self.version = version
        self.statements: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def execute(self, statement, _parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if "information_schema.tables" in sql:
            return FakeScalarResult(sorted(self.tables))
        if "MAX(version)" in sql:
            return FakeScalarResult(self.version)
        return FakeScalarResult(1)


class FakeValidationEngine:
    def __init__(self, connection: FakeValidationConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


class FakeTransaction:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeUnitOfWorkConnection:
    def __init__(self) -> None:
        self.isolation_levels: list[str] = []
        self.transaction = FakeTransaction()
        self.closed = False

    def execution_options(self, *, isolation_level: str):
        self.isolation_levels.append(isolation_level)
        return self

    def begin(self):
        return self.transaction

    def close(self):
        self.closed = True


class FakeConnectionFactory:
    def __init__(self, connection: FakeUnitOfWorkConnection) -> None:
        self.connection = connection
        self.calls = 0

    def connect(self):
        self.calls += 1
        return self.connection


@dataclass
class FakeRepositories:
    snapshots: object = "snapshots"
    collection_runs: object = "collection-runs"
    collection_tasks: object = "collection-tasks"
    leases: object = "leases"
    trading_sessions: object = "trading-sessions"
    aggregates: object = "aggregates"
    provider_capabilities: object = "provider-capabilities"
    limit_details: object = "limit-details"
    timezone_preferences: object = "timezone-preferences"


def test_runtime_factory_checks_connectivity_and_schema_with_select_only() -> None:
    connection = FakeValidationConnection()
    engine = FakeValidationEngine(connection)
    settings = DatabaseSettings("postgresql+psycopg://user:pass@db/market")

    factory = PostgresConnectionFactory.from_settings(
        settings,
        engine_factory=lambda _settings: engine,
    )

    assert factory.validate_runtime().version == MINIMUM_SCHEMA_VERSION
    assert connection.closed is True
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in connection.statements)
    assert not any(
        keyword in statement.upper()
        for statement in connection.statements
        for keyword in ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
    )
    factory.dispose()
    assert engine.disposed is True


def test_runtime_factory_fails_closed_for_missing_or_old_schema() -> None:
    missing_engine = FakeValidationEngine(
        FakeValidationConnection(tables=REQUIRED_RUNTIME_TABLES - {"snapshot_entries"})
    )
    with pytest.raises(DatabaseSchemaCompatibilityError, match="snapshot_entries"):
        PostgresConnectionFactory(missing_engine).validate_runtime()

    old_engine = FakeValidationEngine(
        FakeValidationConnection(version=MINIMUM_SCHEMA_VERSION - 1)
    )
    with pytest.raises(DatabaseSchemaCompatibilityError, match="below required"):
        PostgresConnectionFactory(old_engine).validate_runtime()


def test_unit_of_work_commits_one_shared_read_committed_transaction() -> None:
    connection = FakeUnitOfWorkConnection()
    factory = FakeConnectionFactory(connection)
    seen_connections = []
    unit = MarketEnvironmentUnitOfWork(
        factory,
        lambda active_connection: (
            seen_connections.append(active_connection) or FakeRepositories()
        ),
    )

    with unit as active:
        assert isinstance(active, UnitOfWorkPort)
        assert active.snapshots == "snapshots"
        assert active.collection_tasks == "collection-tasks"
        active.commit()

    assert seen_connections == [connection]
    assert connection.isolation_levels == ["READ COMMITTED"]
    assert connection.transaction.commits == 1
    assert connection.transaction.rollbacks == 0
    assert connection.closed is True


def test_unit_of_work_rolls_back_on_exception_and_without_commit() -> None:
    exceptional = FakeUnitOfWorkConnection()
    with pytest.raises(ValueError, match="boom"):
        with MarketEnvironmentUnitOfWork(
            FakeConnectionFactory(exceptional),
            lambda _connection: FakeRepositories(),
        ):
            raise ValueError("boom")
    assert exceptional.transaction.rollbacks == 1
    assert exceptional.closed is True

    implicit = FakeUnitOfWorkConnection()
    with MarketEnvironmentUnitOfWork(
        FakeConnectionFactory(implicit),
        lambda _connection: FakeRepositories(),
    ):
        pass
    assert implicit.transaction.rollbacks == 1
    assert implicit.closed is True


def test_postgres_runtime_modules_do_not_import_schema_creation_helper() -> None:
    for path in (
        "src/market_environment/infrastructure/persistence/postgres/connection.py",
        "src/market_environment/infrastructure/persistence/postgres/unit_of_work.py",
    ):
        tree = ast.parse(open(path, encoding="utf-8").read())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "create_schema" not in imported
