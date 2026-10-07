from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import LeaseRepository
from src.market_environment.database import DatabaseSettings, create_database_engine
from src.market_environment.domain.models import DatasetDate
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresLeaseRepository,
)
from src.market_environment.snapshot_store import LeaseFenceError


AS_OF = date(2026, 9, 14)
IDENTITY = DatasetDate("core", AS_OF)
NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def lease_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    for statement in (
        """
        CREATE TABLE refresh_leases (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            generation INTEGER NOT NULL, token TEXT NOT NULL,
            PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE refresh_lease_fences (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, generation INTEGER NOT NULL,
            token TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE lease_fence_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL,
            as_of DATE NOT NULL, owner TEXT NOT NULL, generation INTEGER NOT NULL,
            token TEXT NOT NULL, operation TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE TABLE fenced_writes (value TEXT NOT NULL)",
    ):
        connection.exec_driver_sql(statement)
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def test_acquire_duplicate_expiry_takeover_and_generation_audit(lease_connection) -> None:
    current = [NOW]
    repository = PostgresLeaseRepository(lease_connection, now=lambda: current[0])

    first = repository.acquire(IDENTITY, "worker-1", lease_seconds=30)
    duplicate = repository.acquire(IDENTITY, "worker-2", lease_seconds=30)
    current[0] += timedelta(seconds=31)
    second = repository.acquire(IDENTITY, "worker-2", lease_seconds=30)

    assert isinstance(repository, LeaseRepository)
    assert first is not None
    assert duplicate is None
    assert second is not None
    assert second.generation == first.generation + 1
    assert second.token != first.token
    ledger = lease_connection.execute(
        text(
            "SELECT generation, token FROM refresh_lease_fences "
            "WHERE dataset = 'core' AND as_of = :as_of"
        ),
        {"as_of": AS_OF},
    ).mappings().one()
    assert ledger["generation"] == second.generation
    assert ledger["token"] == "[redacted]"


def test_renew_release_and_stale_token_fenced_write_audit(lease_connection) -> None:
    current = [NOW]
    repository = PostgresLeaseRepository(lease_connection, now=lambda: current[0])
    first = repository.acquire(IDENTITY, "worker-1", lease_seconds=30)
    assert first is not None
    renewed = repository.renew(first, lease_seconds=60)
    assert renewed is not None and renewed.expires_at == NOW + timedelta(seconds=60)

    current[0] += timedelta(seconds=61)
    second = repository.acquire(IDENTITY, "worker-2", lease_seconds=30)
    assert second is not None
    assert repository.renew(first, lease_seconds=30) is None
    assert repository.release(first) is False

    writes = []
    with pytest.raises(LeaseFenceError, match="fenced"):
        repository.execute_fenced(
            first,
            "snapshot",
            lambda connection: writes.append(
                connection.execute(
                    text("INSERT INTO fenced_writes(value) VALUES ('stale')")
                )
            ),
            expected_identity=IDENTITY,
        )
    assert writes == []
    events = repository.list_fence_events(identity=IDENTITY)
    assert len(events) == 1
    assert events[0]["token_fingerprint"] != first.token
    assert len(events[0]["token_fingerprint"]) == 64

    repository.execute_fenced(
        second,
        "snapshot",
        lambda connection: connection.execute(
            text("INSERT INTO fenced_writes(value) VALUES ('current')")
        ),
        expected_identity=IDENTITY,
    )
    assert lease_connection.execute(
        text("SELECT value FROM fenced_writes")
    ).scalar_one() == "current"
    assert repository.release(second) is True


@pytest.mark.integration
def test_postgres_duplicate_acquisition_is_serialized_by_advisory_lock() -> None:
    url = os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set MARKET_ENVIRONMENT_TEST_DATABASE_URL for PostgreSQL concurrency")
    engine = create_database_engine(DatabaseSettings(url=url))
    as_of = date(2099, 1, 1)
    owner_prefix = f"lease-contract-{uuid.uuid4().hex}"

    def acquire(index: int):
        with engine.begin() as connection:
            return PostgresLeaseRepository(connection).acquire(
                DatasetDate("core", as_of),
                f"{owner_prefix}-{index}",
                lease_seconds=30,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            leases = list(pool.map(acquire, (1, 2)))
        assert sum(value is not None for value in leases) == 1
        winner = next(value for value in leases if value is not None)
        with engine.begin() as connection:
            assert PostgresLeaseRepository(connection).release(winner) is True
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_stale_token_is_fenced_before_write_callback() -> None:
    url = os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set MARKET_ENVIRONMENT_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    engine = create_database_engine(DatabaseSettings(url=url))
    unique = uuid.uuid4().int
    identity = DatasetDate(
        "core",
        date(3000 + unique % 6000, 1 + unique % 12, 1 + unique % 28),
    )
    owner_prefix = f"fence-contract-{uuid.uuid4().hex}"
    current = [NOW]
    callback_calls: list[str] = []

    try:
        with engine.begin() as connection:
            repository = PostgresLeaseRepository(
                connection,
                now=lambda: current[0],
            )
            first = repository.acquire(identity, f"{owner_prefix}-1", lease_seconds=30)
            assert first is not None
            current[0] += timedelta(seconds=31)
            second = repository.acquire(identity, f"{owner_prefix}-2", lease_seconds=30)
            assert second is not None

            with pytest.raises(LeaseFenceError, match="fenced"):
                repository.execute_fenced(
                    first,
                    "snapshot",
                    lambda _connection: callback_calls.append("stale"),
                    expected_identity=identity,
                )
            assert callback_calls == []

            repository.execute_fenced(
                second,
                "snapshot",
                lambda active_connection: callback_calls.append(
                    str(active_connection.execute(text("SELECT 1")).scalar_one())
                ),
                expected_identity=identity,
            )
            assert callback_calls == ["1"]
            assert repository.release(second) is True
    finally:
        with engine.begin() as connection:
            parameters = {
                "dataset": identity.dataset,
                "as_of": identity.as_of,
            }
            connection.execute(
                text(
                    "DELETE FROM lease_fence_events "
                    "WHERE dataset = :dataset AND as_of = :as_of"
                ),
                parameters,
            )
            connection.execute(
                text(
                    "DELETE FROM refresh_leases "
                    "WHERE dataset = :dataset AND as_of = :as_of"
                ),
                parameters,
            )
            connection.execute(
                text(
                    "DELETE FROM refresh_lease_fences "
                    "WHERE dataset = :dataset AND as_of = :as_of"
                ),
                parameters,
            )
        engine.dispose()
