from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.mappers import quality_to_api
from src.market_environment.application.ports import SnapshotRepository
from src.market_environment.domain.models import (
    CacheMetadata,
    CacheState,
    CollectionCandidate,
    DatasetDate,
    QualityMetadata,
)
from src.market_environment.infrastructure.compatibility import (
    LegacySnapshotRepositoryAdapter,
)
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresSnapshotRepository,
)
from src.market_environment.infrastructure.persistence.sqlite_import import (
    LegacySqliteSnapshotStore,
)
from src.market_environment.snapshot_store import SnapshotIntegrityError


AS_OF = date(2026, 9, 14)
PREVIOUS = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SnapshotRepositoryHarness:
    repository: SnapshotRepository
    tamper_payload: Callable[[DatasetDate], None]


def _candidate(as_of: date, *, settled: bool) -> CollectionCandidate:
    warning = "fixture-warning"
    quality = QualityMetadata(
        dataset="core",
        source="fixture-primary",
        provider="fixture",
        status="partial",
        observations=1,
        as_of=as_of,
        warning=warning,
        warnings=(warning,),
        cache=CacheMetadata(
            state=CacheState.FRESH,
            snapshot_fetched_at=FETCHED_AT,
            refreshing=False,
            refresh_warning="retained fixture warning",
        ),
        extra={"lineage": {"provider": "fixture"}},
    )
    return CollectionCandidate(
        identity=DatasetDate("core", as_of),
        payload={
            "asOf": as_of.isoformat(),
            "indices": [{"code": "sh000001", "close": 3210.5}],
            "quality": quality_to_api(quality),
        },
        source="fixture-primary",
        status="partial",
        observations=1,
        warnings=(warning,),
        settled=settled,
        actual_as_of=as_of,
        quality=quality,
    )


@pytest.fixture(params=("legacy-sqlite", "postgres-repository"))
def snapshot_repository_harness(request, tmp_path):
    if request.param == "legacy-sqlite":
        path = Path(tmp_path) / "repository-contract.sqlite3"
        repository = LegacySnapshotRepositoryAdapter(
            LegacySqliteSnapshotStore(path),
            now=lambda: FETCHED_AT,
        )

        def tamper(identity: DatasetDate) -> None:
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE snapshot_entries SET payload_json = ? "
                    "WHERE dataset = ? AND as_of = ?",
                    (
                        '{"asOf":"2026-09-14","indices":[]}',
                        identity.dataset,
                        identity.as_of.isoformat(),
                    ),
                )

        yield SnapshotRepositoryHarness(repository, tamper)
        return

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    connection.exec_driver_sql(
        """
        CREATE TABLE snapshot_entries (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, payload_json TEXT NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL, observations INTEGER NOT NULL,
            warnings_json TEXT NOT NULL, fetched_at TEXT NOT NULL, settled INTEGER NOT NULL,
            schema_version INTEGER NOT NULL, checksum TEXT NOT NULL, refresh_warning TEXT,
            PRIMARY KEY(dataset, as_of)
        )
        """
    )
    connection.commit()
    repository = PostgresSnapshotRepository(connection, now=lambda: FETCHED_AT)

    def tamper(identity: DatasetDate) -> None:
        connection.execute(
            text(
                "UPDATE snapshot_entries SET payload_json = :payload "
                "WHERE dataset = :dataset AND as_of = :as_of"
            ),
            {
                "payload": '{"asOf":"2026-09-14","indices":[]}',
                "dataset": identity.dataset,
                "as_of": identity.as_of,
            },
        )

    try:
        yield SnapshotRepositoryHarness(repository, tamper)
    finally:
        connection.close()
        engine.dispose()


def test_snapshot_repository_shared_exact_date_round_trip_contract(
    snapshot_repository_harness: SnapshotRepositoryHarness,
) -> None:
    repository = snapshot_repository_harness.repository
    previous = _candidate(PREVIOUS, settled=False)
    current = _candidate(AS_OF, settled=True)

    assert isinstance(repository, SnapshotRepository)
    assert repository.put(previous) == previous
    assert repository.put(current) == current
    assert repository.get(current.identity) == current
    assert repository.get(DatasetDate("core", date(2026, 9, 12))) is None
    assert tuple(repository.list_dates("core")) == (AS_OF, PREVIOUS)
    assert tuple(repository.list_dates("breadth")) == ()

    loaded = repository.get(current.identity)
    assert loaded is not None
    assert loaded.payload == current.payload
    assert loaded.source == current.source
    assert loaded.status == current.status
    assert loaded.observations == current.observations
    assert loaded.warnings == current.warnings
    assert loaded.settled is True
    assert loaded.quality == current.quality


def test_snapshot_repository_shared_checksum_tamper_contract(
    snapshot_repository_harness: SnapshotRepositoryHarness,
) -> None:
    repository = snapshot_repository_harness.repository
    candidate = _candidate(AS_OF, settled=True)
    repository.put(candidate)

    snapshot_repository_harness.tamper_payload(candidate.identity)

    with pytest.raises(SnapshotIntegrityError, match="checksum mismatch"):
        repository.get(candidate.identity)
