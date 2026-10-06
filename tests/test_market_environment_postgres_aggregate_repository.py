from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import MaterializedAggregateRepository
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresMaterializedAggregateRepository,
)
from src.market_environment.snapshot_store import (
    MATERIALIZED_COMPONENT_REVISION_KEY,
    MaterializedAggregateConflict,
    SnapshotIntegrityError,
)


AS_OF = date(2026, 9, 14)
GENERATED_AT = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def aggregate_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    for statement in (
        """
        CREATE TABLE snapshot_entries (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, source TEXT NOT NULL,
            status TEXT NOT NULL, observations INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, fetched_at TEXT NOT NULL,
            settled INTEGER NOT NULL, schema_version INTEGER NOT NULL,
            checksum TEXT NOT NULL, refresh_warning TEXT,
            PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE trading_sessions (
            as_of DATE PRIMARY KEY, previous_as_of DATE, actual_as_of DATE,
            is_session INTEGER NOT NULL, source TEXT NOT NULL,
            schema_version INTEGER NOT NULL, checksum TEXT NOT NULL,
            warnings_json TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE limit_security_datasets (
            as_of DATE PRIMARY KEY, actual_as_of DATE, source TEXT NOT NULL,
            source_revision TEXT, rule_version TEXT, schema_version INTEGER NOT NULL,
            complete INTEGER NOT NULL, excluded INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, dataset_checksum TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE materialization_component_versions (
            component_kind TEXT NOT NULL, dataset TEXT NOT NULL,
            as_of DATE NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY(component_kind, dataset, as_of)
        )
        """,
        """
        CREATE TABLE materialized_market_environment (
            as_of DATE PRIMARY KEY, payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL, checksum TEXT NOT NULL
        )
        """,
    ):
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(
        "INSERT INTO materialization_component_versions"
        "(component_kind, dataset, as_of, revision) VALUES (?, ?, ?, ?)",
        ("snapshot", "core", AS_OF.isoformat(), 1),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def _payload(revision: str) -> dict:
    return {
        "asOf": AS_OF.isoformat(),
        "generatedAt": GENERATED_AT.isoformat(),
        "indices": [],
        "summary": {},
        "chapter01": {},
        MATERIALIZED_COMPONENT_REVISION_KEY: revision,
    }


def test_aggregate_repository_provider_free_read_checksum_and_exact_date(
    aggregate_connection,
) -> None:
    repository = PostgresMaterializedAggregateRepository(aggregate_connection)
    revision = repository.revision(AS_OF)
    payload = _payload(revision.value)

    stored_revision = repository.compare_and_swap(AS_OF, revision, payload)

    assert isinstance(repository, MaterializedAggregateRepository)
    assert stored_revision == revision
    assert repository.get_aggregate(AS_OF) == payload
    assert repository.get_aggregate(date(2026, 9, 15)) is None
    aggregate_connection.execute(
        text(
            "UPDATE materialized_market_environment SET payload_json = '{}' "
            "WHERE as_of = :as_of"
        ),
        {"as_of": AS_OF},
    )
    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        repository.get_aggregate(AS_OF)


def test_aggregate_compare_and_swap_conflict_can_retry_with_new_revision(
    aggregate_connection,
) -> None:
    repository = PostgresMaterializedAggregateRepository(aggregate_connection)
    stale = repository.revision(AS_OF)
    aggregate_connection.execute(
        text(
            "UPDATE materialization_component_versions SET revision = revision + 1 "
            "WHERE component_kind = 'snapshot' AND dataset = 'core' AND as_of = :as_of"
        ),
        {"as_of": AS_OF},
    )

    with pytest.raises(MaterializedAggregateConflict, match="inputs changed"):
        repository.compare_and_swap(AS_OF, stale, _payload(stale.value))

    current = repository.revision(AS_OF)
    repository.compare_and_swap(AS_OF, current, _payload(current.value))
    assert repository.get_aggregate(AS_OF)[MATERIALIZED_COMPONENT_REVISION_KEY] == current.value


def test_aggregate_payload_revision_must_match_cas_token(aggregate_connection) -> None:
    repository = PostgresMaterializedAggregateRepository(aggregate_connection)
    revision = repository.revision(AS_OF)
    with pytest.raises(ValueError, match="revision does not match"):
        repository.compare_and_swap(AS_OF, revision, _payload("wrong-revision"))
