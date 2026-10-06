from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import (
    ProviderCapabilityRepository,
    SnapshotRepository,
    TradingSessionRepository,
)
from src.market_environment.domain.models import CollectionCandidate, DatasetDate
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresProviderCapabilityRepository,
    PostgresSnapshotRepository,
    PostgresTradingSessionRepository,
)
from src.market_environment.provider_capability import ProviderCapabilityReport
from src.market_environment.snapshot_store import (
    SnapshotIntegrityError,
    TradingSessionRecord,
)


AS_OF = date(2026, 9, 14)
PREVIOUS = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def repository_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    for statement in (
        """
        CREATE TABLE snapshot_entries (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, payload_json TEXT NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL, observations INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, fetched_at TEXT NOT NULL, settled INTEGER NOT NULL,
            schema_version INTEGER NOT NULL, checksum TEXT NOT NULL, refresh_warning TEXT,
            PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE trading_sessions (
            as_of DATE PRIMARY KEY, previous_as_of DATE, actual_as_of DATE,
            is_session INTEGER NOT NULL, source TEXT NOT NULL,
            schema_version INTEGER NOT NULL, checksum TEXT NOT NULL,
            fetched_at TEXT NOT NULL, warnings_json TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE provider_capability_reports (
            provider TEXT NOT NULL, dataset TEXT NOT NULL, revision TEXT NOT NULL,
            status TEXT NOT NULL, endpoint TEXT, field_coverage_json TEXT NOT NULL,
            date_evidence_json TEXT NOT NULL, history_window_json TEXT NOT NULL,
            pagination_evidence_json TEXT NOT NULL, permission_evidence_json TEXT NOT NULL,
            rate_limit_evidence_json TEXT NOT NULL, sample_count INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, missing_evidence_json TEXT NOT NULL,
            checked_at TEXT NOT NULL, schema_version INTEGER NOT NULL, checksum TEXT NOT NULL,
            PRIMARY KEY(provider, dataset, revision)
        )
        """,
    ):
        connection.exec_driver_sql(statement)
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def test_snapshot_repository_exact_date_list_read_write_and_checksum(
    repository_connection,
) -> None:
    repository = PostgresSnapshotRepository(
        repository_connection,
        now=lambda: FETCHED_AT,
    )
    candidate = CollectionCandidate(
        identity=DatasetDate("core", AS_OF),
        payload={"asOf": AS_OF.isoformat(), "indices": [{"code": "sh000001"}]},
        source="fixture",
        status="ok",
        observations=1,
        warnings=("fixture-warning",),
        settled=True,
        actual_as_of=AS_OF,
    )

    stored = repository.put(candidate)

    assert isinstance(repository, SnapshotRepository)
    assert stored == repository.get(candidate.identity)
    assert repository.get(DatasetDate("core", PREVIOUS)) is None
    assert repository.list_dates("core") == (AS_OF,)

    repository_connection.execute(
        text(
            "UPDATE snapshot_entries SET payload_json = :payload "
            "WHERE dataset = 'core' AND as_of = :as_of"
        ),
        {"payload": '{"asOf":"2026-09-14","indices":[]}', "as_of": AS_OF},
    )
    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        repository.get(candidate.identity)


def test_snapshot_repository_rejects_payload_date_relabel(repository_connection) -> None:
    repository = PostgresSnapshotRepository(repository_connection, now=lambda: FETCHED_AT)
    candidate = CollectionCandidate(
        identity=DatasetDate("breadth", AS_OF),
        payload={"asOf": PREVIOUS.isoformat(), "quality": {"asOf": PREVIOUS.isoformat()}},
        source="fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
    )
    with pytest.raises(SnapshotIntegrityError, match="exact-date mismatch|payload date mismatch"):
        repository.put(candidate)


def test_trading_session_repository_round_trip_filters_and_validates_checksum(
    repository_connection,
) -> None:
    repository = PostgresTradingSessionRepository(repository_connection)
    previous = TradingSessionRecord(
        PREVIOUS,
        None,
        True,
        "fixture",
        actual_as_of=PREVIOUS,
        fetched_at=FETCHED_AT,
    )
    current = TradingSessionRecord(
        AS_OF,
        PREVIOUS,
        True,
        "fixture",
        actual_as_of=AS_OF,
        fetched_at=FETCHED_AT,
    )

    repository.put_session(previous)
    repository.put_session(current)

    assert isinstance(repository, TradingSessionRepository)
    assert repository.get_session(AS_OF) == current.normalized()
    assert tuple(item.as_of for item in repository.list_sessions(after=PREVIOUS)) == (AS_OF,)

    repository_connection.execute(
        text("UPDATE trading_sessions SET checksum = 'broken' WHERE as_of = :as_of"),
        {"as_of": AS_OF},
    )
    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        repository.get_session(AS_OF)


def test_provider_capability_repository_is_immutable_per_revision_and_filterable(
    repository_connection,
) -> None:
    repository = PostgresProviderCapabilityRepository(repository_connection)
    report = ProviderCapabilityReport(
        provider="fuyao",
        dataset="core",
        revision="r1",
        status="eligible",
        field_coverage={"close": True},
        sample_count=5,
        checked_at=FETCHED_AT,
    ).normalized()

    repository.put_capability(report.to_dict())
    loaded = repository.get_capability("fuyao", "core", "r1")

    assert isinstance(repository, ProviderCapabilityRepository)
    assert loaded == report.to_dict()
    assert repository.list_capabilities(provider="fuyao") == (report.to_dict(),)
    changed = {**report.to_dict(), "sample_count": 6, "checksum": ""}
    with pytest.raises(ValueError, match="different checksum"):
        repository.put_capability(changed)
