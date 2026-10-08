from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports.core_committers import (
    CoreCommitRequest,
    CoreIndexCommitEvidence,
    CoreTradingSessionEvidence,
)
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    QualityMetadata,
)
from src.market_environment.infrastructure.collection.core_committer import (
    CoreDatasetCommitter,
)
from src.market_environment.infrastructure.persistence.postgres import (
    MarketEnvironmentUnitOfWork,
    PostgresCollectionTaskRepository,
    PostgresConnectionFactory,
    PostgresCoreIndexResultRepository,
    PostgresLeaseRepository,
    PostgresSnapshotRepository,
    PostgresTradingSessionRepository,
)
from src.market_environment.snapshot_store import (
    CollectionTaskRecord,
    LeaseFenceError,
    LeaseToken,
    TradingSessionRecord,
)


AS_OF = date(2026, 9, 14)
PREVIOUS = date(2026, 9, 11)
PRIOR = date(2026, 9, 10)
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
IDENTITY = DatasetDate("core", AS_OF)
TASK_ID = "task-core"
TOKEN = "active-token"


@pytest.fixture
def core_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        for statement in (
            """
            CREATE TABLE snapshot_entries (
                dataset TEXT NOT NULL, as_of DATE NOT NULL, payload_json TEXT NOT NULL,
                source TEXT NOT NULL, status TEXT NOT NULL, observations INTEGER NOT NULL,
                warnings_json TEXT NOT NULL, fetched_at TEXT NOT NULL, settled INTEGER NOT NULL,
                schema_version INTEGER NOT NULL, checksum TEXT NOT NULL,
                refresh_warning TEXT, PRIMARY KEY(dataset, as_of)
            )
            """,
            """
            CREATE TABLE collection_tasks (
                task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset TEXT NOT NULL,
                as_of DATE NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
                observations INTEGER NOT NULL, warning TEXT, timings_json TEXT NOT NULL,
                queued_at TEXT, started_at TEXT, completed_at TEXT,
                duration_ms REAL, settled INTEGER NOT NULL,
                UNIQUE(run_id, dataset)
            )
            """,
            """
            CREATE TABLE core_index_results (
                task_id TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL, source TEXT NOT NULL, observations INTEGER NOT NULL,
                warning TEXT, duration_ms REAL, payload_json TEXT,
                PRIMARY KEY(task_id, code)
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
            CREATE TABLE refresh_leases (
                dataset TEXT NOT NULL, as_of DATE NOT NULL, owner TEXT NOT NULL,
                acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                generation INTEGER NOT NULL, token TEXT NOT NULL,
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
        ):
            connection.exec_driver_sql(statement)
    try:
        yield engine
    finally:
        engine.dispose()


@dataclass
class RepositoryBundle:
    snapshots: object
    collection_tasks: object
    core_index_results: object
    leases: object
    trading_sessions: object
    collection_runs: object = None
    aggregates: object = None
    provider_capabilities: object = None
    limit_details: object = None
    timezone_preferences: object = None


class FailingSnapshotRepository:
    def __init__(self, delegate: PostgresSnapshotRepository) -> None:
        self.delegate = delegate

    def get(self, identity):
        return self.delegate.get(identity)

    def put(self, _candidate):
        raise RuntimeError("injected snapshot failure")


def unit_of_work_factory(engine, *, fail_snapshot: bool = False):
    connections = PostgresConnectionFactory(engine)

    def repositories(connection):
        snapshots = PostgresSnapshotRepository(connection, now=lambda: NOW)
        return RepositoryBundle(
            snapshots=(
                FailingSnapshotRepository(snapshots) if fail_snapshot else snapshots
            ),
            collection_tasks=PostgresCollectionTaskRepository(connection),
            core_index_results=PostgresCoreIndexResultRepository(connection),
            leases=PostgresLeaseRepository(connection, now=lambda: NOW),
            trading_sessions=PostgresTradingSessionRepository(connection),
        )

    return lambda: MarketEnvironmentUnitOfWork(
        connections,
        repositories,
        isolation_level="SERIALIZABLE",
    )


def seed_task_and_lease(engine, *, token: str = TOKEN) -> LeaseToken:
    lease = LeaseToken(
        dataset="core",
        as_of=AS_OF,
        owner=TASK_ID,
        generation=1,
        token=token,
        expires_at=NOW + timedelta(minutes=10),
    )
    with engine.begin() as connection:
        PostgresCollectionTaskRepository(connection).create_task(
            CollectionTaskRecord(
                task_id=TASK_ID,
                run_id="run-core",
                dataset="core",
                as_of=AS_OF,
                status="collecting",
                queued_at=NOW - timedelta(seconds=2),
                started_at=NOW - timedelta(seconds=1),
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO refresh_leases(
                    dataset, as_of, owner, acquired_at, expires_at, generation, token
                ) VALUES (
                    :dataset, :as_of, :owner, :acquired_at, :expires_at,
                    :generation, :token
                )
                """
            ),
            {
                "dataset": lease.dataset,
                "as_of": lease.as_of,
                "owner": lease.owner,
                "acquired_at": NOW,
                "expires_at": lease.expires_at,
                "generation": lease.generation,
                "token": lease.token,
            },
        )
    return lease


def index_payload(code: str, close: float) -> dict[str, object]:
    return {
        "code": code,
        "name": code,
        "history": [
            {"date": PREVIOUS.isoformat(), "close": close - 1},
            {"date": AS_OF.isoformat(), "close": close},
        ],
        "dataQuality": {"source": "fixture"},
    }


def candidate(indices, *, status: str = "partial") -> CollectionCandidate:
    return CollectionCandidate(
        identity=IDENTITY,
        payload={"asOf": AS_OF.isoformat(), "indices": list(indices)},
        source="fixture",
        status=status,
        observations=len(indices),
        warnings=("one index retained",) if status == "partial" else (),
        settled=True,
        actual_as_of=AS_OF,
    )


def core_request(
    lease: LeaseToken,
    *,
    retained_payload: dict[str, object] | None = None,
) -> CoreCommitRequest:
    fresh = index_payload("sh000001", 3200)
    results = [
        CoreIndexCommitEvidence(
            code="sh000001",
            name="上证指数",
            state=CollectionTaskState.SUCCESS,
            source="fixture",
            observations=2,
            payload=fresh,
            duration_ms=2.5,
        )
    ]
    payloads = [fresh]
    state = CollectionTaskState.SUCCESS
    if retained_payload is not None:
        results.append(
            CoreIndexCommitEvidence(
                code="sz399001",
                name="深证成指",
                state=CollectionTaskState.FAILED_RETAINED,
                source="old-fixture",
                observations=2,
                payload=retained_payload,
                warning="provider unavailable",
                duration_ms=3.5,
                retained=True,
            )
        )
        payloads.append(retained_payload)
        state = CollectionTaskState.PARTIAL
    value = candidate(payloads, status=state.value)
    return CoreCommitRequest(
        identity=IDENTITY,
        outcome=CollectionOutcome(
            identity=IDENTITY,
            state=state,
            candidate=value,
            warning="one index retained" if retained_payload is not None else None,
        ),
        lease=lease,
        task_id=TASK_ID,
        index_results=tuple(results),
        session=CoreTradingSessionEvidence(
            as_of=AS_OF,
            previous_as_of=PREVIOUS,
            is_session=True,
            source="core-index-history:fixture",
            actual_as_of=AS_OF,
            fetched_at=NOW,
        ),
        previous_session=CoreTradingSessionEvidence(
            as_of=PREVIOUS,
            previous_as_of=None,
            is_session=True,
            source="core-index-history:fixture",
            actual_as_of=PREVIOUS,
            fetched_at=NOW,
        ),
        completed_at=NOW,
        task_timings={"collectMs": 6.0},
        duration_ms=7.0,
    )


def test_core_committer_atomically_preserves_partial_retention_session_and_checksum(
    core_engine,
) -> None:
    lease = seed_task_and_lease(core_engine)
    retained = index_payload("sz399001", 10500)
    with core_engine.begin() as connection:
        PostgresSnapshotRepository(connection, now=lambda: NOW).put(
            candidate((retained,), status="ok")
        )

    evidence = CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(
        core_request(lease, retained_payload=retained)
    )

    with core_engine.connect() as connection:
        snapshots = PostgresSnapshotRepository(connection, now=lambda: NOW)
        tasks = PostgresCollectionTaskRepository(connection)
        results = PostgresCoreIndexResultRepository(connection)
        sessions = PostgresTradingSessionRepository(connection)
        stored = snapshots.get(IDENTITY)
        assert stored == evidence.candidate
        assert evidence.outcome_state is CollectionTaskState.PARTIAL
        assert evidence.writes == (
            "core-index-results",
            "trading-session",
            "snapshot",
            "collection-task",
        )
        assert connection.execute(
            text(
                "SELECT checksum FROM snapshot_entries "
                "WHERE dataset = 'core' AND as_of = :as_of"
            ),
            {"as_of": AS_OF},
        ).scalar_one() == evidence.snapshot_checksum
        assert [item.status for item in results.list_results(TASK_ID)] == [
            "success",
            "failed-retained",
        ]
        assert tasks.get_task(TASK_ID).status == "partial"
        assert tasks.get_task(TASK_ID).timings == {"collectMs": 6.0}
        assert sessions.get_session(AS_OF).previous_as_of == PREVIOUS
        assert sessions.get_session(PREVIOUS).actual_as_of == PREVIOUS


def test_core_committer_preserves_exact_identity_for_legacy_stale_payload(
    core_engine,
) -> None:
    lease = seed_task_and_lease(core_engine)
    request = core_request(lease)
    stale_index = {
        "code": "sh000001",
        "name": "sh000001",
        "history": [
            {"date": PRIOR.isoformat(), "close": 3199},
            {"date": PREVIOUS.isoformat(), "close": 3200},
        ],
        "dataQuality": {"source": "fixture"},
    }
    stale_candidate = replace(
        request.candidate,
        payload={"asOf": PREVIOUS.isoformat(), "indices": [stale_index]},
        quality=QualityMetadata(
            dataset="core-indices",
            source="fixture",
            provider="fixture",
            status="ok",
            observations=1,
            as_of=AS_OF,
        ),
    )
    stale_request = replace(
        request,
        outcome=replace(request.outcome, candidate=stale_candidate),
        index_results=(replace(request.index_results[0], payload=stale_index),),
        session=None,
        previous_session=None,
        session_warning="core index history could not prove the requested session",
    )

    evidence = CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(
        stale_request
    )

    with core_engine.connect() as connection:
        stored = PostgresSnapshotRepository(connection, now=lambda: NOW).get(IDENTITY)
        assert stored is not None
        assert stored.identity == IDENTITY
        assert stored.payload["asOf"] == PREVIOUS.isoformat()
        assert evidence.candidate == stored


def test_core_committer_does_not_overwrite_existing_previous_session(
    core_engine,
) -> None:
    lease = seed_task_and_lease(core_engine)
    authoritative = TradingSessionRecord(
        PREVIOUS,
        PRIOR,
        True,
        "authoritative-previous-collection",
        actual_as_of=PREVIOUS,
        fetched_at=NOW - timedelta(hours=1),
    )
    with core_engine.begin() as connection:
        PostgresTradingSessionRepository(connection).put_session(authoritative)

    CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(core_request(lease))

    with core_engine.connect() as connection:
        stored = PostgresTradingSessionRepository(connection).get_session(PREVIOUS)
        assert stored == authoritative.normalized()


def test_core_committer_records_all_failed_retention_without_snapshot_overwrite(
    core_engine,
) -> None:
    lease = seed_task_and_lease(core_engine)
    retained = index_payload("sh000001", 3200)
    existing = candidate((retained,), status="ok")
    with core_engine.begin() as connection:
        stored_before = PostgresSnapshotRepository(
            connection,
            now=lambda: NOW - timedelta(hours=1),
        ).put(existing)
    base = core_request(lease)
    attempted_candidate = replace(
        candidate((retained,), status="partial"),
        payload={
            "asOf": AS_OF.isoformat(),
            "generatedAt": NOW.isoformat(),
            "indices": [retained],
        },
    )
    retained_result = replace(
        base.index_results[0],
        state=CollectionTaskState.FAILED_RETAINED,
        payload=retained,
        warning="all providers unavailable",
        retained=True,
    )
    request = replace(
        base,
        outcome=CollectionOutcome(
            identity=IDENTITY,
            state=CollectionTaskState.FAILED_RETAINED,
            candidate=attempted_candidate,
            warning="all providers unavailable",
            retained=True,
        ),
        index_results=(retained_result,),
    )

    evidence = CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(request)

    with core_engine.connect() as connection:
        stored_after = PostgresSnapshotRepository(connection, now=lambda: NOW).get(
            IDENTITY
        )
        assert stored_after == stored_before
        assert evidence.candidate == stored_before
        assert evidence.outcome_state is CollectionTaskState.FAILED_RETAINED
        assert "snapshot" not in evidence.writes
        assert PostgresCollectionTaskRepository(connection).get_task(TASK_ID).status == (
            "failed-retained"
        )
        results = PostgresCoreIndexResultRepository(connection).list_results(TASK_ID)
        assert len(results) == 1
        assert results[0].status == "failed-retained"
        assert results[0].payload == retained


def test_core_committer_rolls_back_every_write_when_snapshot_fails(core_engine) -> None:
    lease = seed_task_and_lease(core_engine)
    committer = CoreDatasetCommitter(
        unit_of_work_factory(core_engine, fail_snapshot=True)
    )

    with pytest.raises(RuntimeError, match="injected snapshot failure"):
        committer.commit(core_request(lease))

    with core_engine.connect() as connection:
        assert PostgresCoreIndexResultRepository(connection).list_results(TASK_ID) == ()
        assert PostgresTradingSessionRepository(connection).get_session(AS_OF) is None
        assert PostgresTradingSessionRepository(connection).get_session(PREVIOUS) is None
        assert PostgresCollectionTaskRepository(connection).get_task(TASK_ID).status == "collecting"
        assert PostgresSnapshotRepository(connection, now=lambda: NOW).get(IDENTITY) is None


def test_core_committer_stale_fence_fails_before_any_partial_write(core_engine) -> None:
    seed_task_and_lease(core_engine)
    stale = LeaseToken(
        "core",
        AS_OF,
        TASK_ID,
        1,
        "stale-token",
        NOW + timedelta(minutes=10),
    )

    with pytest.raises(LeaseFenceError, match="lease fenced"):
        CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(
            core_request(stale)
        )

    with core_engine.connect() as connection:
        assert PostgresCoreIndexResultRepository(connection).list_results(TASK_ID) == ()
        assert PostgresTradingSessionRepository(connection).get_session(AS_OF) is None
        assert PostgresCollectionTaskRepository(connection).get_task(TASK_ID).status == "collecting"
        assert PostgresSnapshotRepository(connection, now=lambda: NOW).get(IDENTITY) is None


def test_core_committer_rejects_retention_not_backed_by_same_date_snapshot(
    core_engine,
) -> None:
    lease = seed_task_and_lease(core_engine)
    retained = index_payload("sz399001", 10500)
    with core_engine.begin() as connection:
        PostgresSnapshotRepository(connection, now=lambda: NOW).put(
            candidate((retained,), status="ok")
        )
    mismatched = index_payload("sz399001", 9999)

    with pytest.raises(ValueError, match="lacks matching same-date snapshot"):
        CoreDatasetCommitter(unit_of_work_factory(core_engine)).commit(
            core_request(lease, retained_payload=mismatched)
        )

    with core_engine.connect() as connection:
        assert PostgresCoreIndexResultRepository(connection).list_results(TASK_ID) == ()
        assert PostgresTradingSessionRepository(connection).get_session(AS_OF) is None
        assert PostgresCollectionTaskRepository(connection).get_task(TASK_ID).status == "collecting"
        stored = PostgresSnapshotRepository(connection, now=lambda: NOW).get(IDENTITY)
        assert stored is not None
        assert stored.payload["indices"] == [retained]
