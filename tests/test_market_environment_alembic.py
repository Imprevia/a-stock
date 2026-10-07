from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from pathlib import Path

from src.market_environment.infrastructure.persistence.postgres import (
    MINIMUM_SCHEMA_VERSION,
    REQUIRED_RUNTIME_TABLES,
    PostgresProviderCapabilityRepository,
)
from src.market_environment.postgres_schema import SCHEMA_STATEMENTS


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0003_provider_capability_reports.py"
ALEMBIC_ENV_PATH = ROOT / "alembic" / "env.py"


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "test_0003_provider_capability_reports",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).lower()


def test_0003_revision_is_additive_and_matches_runtime_schema_contract() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0003_provider_capability_reports"
    assert migration.down_revision == "0002_limit_membership_details"
    normalized = tuple(_normalize_sql(statement) for statement in operations.statements)
    expected_schema = tuple(
        _normalize_sql(statement)
        for statement in SCHEMA_STATEMENTS
        if _normalize_sql(statement).startswith(
            (
                "create table if not exists provider_capability_reports",
                "create index if not exists provider_capability_reports_",
            )
        )
    )
    assert normalized[:3] == expected_schema
    assert len(normalized) == 4
    assert "values (6, 'add-provider-capability-reports'" in normalized[3]
    assert "on conflict(version) do nothing" in normalized[3]

    destructive = re.compile(r"\b(alter|drop|update|delete|truncate)\b", re.IGNORECASE)
    assert all(destructive.search(statement) is None for statement in operations.statements)
    assert MINIMUM_SCHEMA_VERSION == 6
    assert "provider_capability_reports" in REQUIRED_RUNTIME_TABLES


def test_0003_table_columns_primary_key_and_indexes_match_repository_usage() -> None:
    migration = _load_migration()
    table_sql = _normalize_sql(migration.UPGRADE_STATEMENTS[0])
    repository_source = inspect.getsource(PostgresProviderCapabilityRepository)
    columns = (
        "provider",
        "dataset",
        "revision",
        "status",
        "endpoint",
        "field_coverage_json",
        "date_evidence_json",
        "history_window_json",
        "pagination_evidence_json",
        "permission_evidence_json",
        "rate_limit_evidence_json",
        "sample_count",
        "warnings_json",
        "missing_evidence_json",
        "checked_at",
        "schema_version",
        "checksum",
    )

    for column in columns:
        assert re.search(rf"\b{column}\b", table_sql)
        assert column in repository_source
    assert "primary key(provider, dataset, revision)" in table_sql
    assert "provider_capability_reports_dataset_idx" in migration.UPGRADE_STATEMENTS[1]
    assert "provider_capability_reports_status_idx" in migration.UPGRADE_STATEMENTS[2]


def test_alembic_runtime_does_not_bootstrap_schema_or_destructively_downgrade() -> None:
    env_source = ALEMBIC_ENV_PATH.read_text(encoding="utf-8")
    env_tree = ast.parse(env_source)
    imported_names = {
        alias.name
        for node in ast.walk(env_tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(env_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "create_schema" not in imported_names
    assert "create_schema" not in called_names

    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations
    migration.downgrade()
    assert operations.statements == []
