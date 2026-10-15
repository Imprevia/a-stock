from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text

from src.market_environment.application.commands import (
    CollectionSubmissionRejected,
    RecoverableCollectionSubmissionService,
    RecoverableSubmissionDisposition,
)
from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    CollectionFailureCategory,
    FullCollectionSemantics,
    IdempotencyClaimDisposition,
    IdempotencyKey,
    SubmissionState,
)
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresCollectionIdempotencyRepository,
)


SCHEMA = """
CREATE TABLE collection_runs (
    run_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, status TEXT NOT NULL,
    requested_datasets_json TEXT NOT NULL, created_at TEXT NOT NULL,
    started_at TEXT, completed_at TEXT
);
CREATE TABLE collection_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
    dataset TEXT NOT NULL, as_of TEXT NOT NULL, status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'none', observations INTEGER NOT NULL DEFAULT 0,
    warning TEXT, failure_json TEXT, timings_json TEXT NOT NULL DEFAULT '{}',
    queued_at TEXT, started_at TEXT, completed_at TEXT, duration_ms REAL,
    settled INTEGER NOT NULL DEFAULT 0, UNIQUE(run_id, dataset)
);
CREATE TABLE collection_idempotency_bindings (
    operation_scope TEXT NOT NULL, idempotency_key TEXT NOT NULL,
    semantic_fingerprint TEXT NOT NULL, resolved_as_of TEXT NOT NULL,
    operation_version TEXT NOT NULL, dataset_fingerprint TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES collection_runs(run_id),
    submission_state TEXT NOT NULL DEFAULT 'reserved',
    submission_attempts INTEGER NOT NULL DEFAULT 0,
    submission_owner TEXT, submission_lease_expires_at TEXT,
    submission_error_json TEXT, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, submitted_at TEXT,
    PRIMARY KEY(operation_scope, idempotency_key)
);
CREATE TABLE refresh_leases (
    dataset TEXT NOT NULL, as_of TEXT NOT NULL, owner TEXT NOT NULL,
    expires_at TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(dataset, as_of)
);
"""


def _engine(path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"timeout": 10, "check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA busy_timeout=10000")

    with engine.begin() as connection:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement)
    return engine


def _task_ids(prefix: str) -> dict[str, str]:
    return {
        dataset: f"{prefix}-{index}"
        for index, dataset in enumerate(CANONICAL_FULL_COLLECTION_DATASETS, start=1)
    }


class _IdempotencyUnitOfWork:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.connection = None
        self.transaction = None
        self.collection_idempotency = None
        self.finished = False

    def __enter__(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.collection_idempotency = PostgresCollectionIdempotencyRepository(
            self.connection
        )
        self.finished = False
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.finished:
            self.transaction.rollback()
        self.connection.close()

    def commit(self) -> None:
        self.transaction.commit()
        self.finished = True

    def rollback(self) -> None:
        self.transaction.rollback()
        self.finished = True


@dataclass
class _SubmissionQueries:
    run_id: str
    status: str = "queued"

    def get_run(self, run_id: str):
        if run_id != self.run_id:
            return None
        return SimpleNamespace(run=SimpleNamespace(status=self.status))


class _SubmissionCommands:
    def __init__(self, run_id: str, *, task_status: str = "queued") -> None:
        self.run_id = run_id
        self.tasks = tuple(
            SimpleNamespace(dataset=dataset, status=task_status)
            for dataset in CANONICAL_FULL_COLLECTION_DATASETS
        )
        self.leases: set[str] = set()
        self.prepare_calls: list[tuple[str, float]] = []
        self.release_calls: list[str] = []
        self.execute_calls: list[str] = []

    def prepare_run_submission(self, run_id: str, *, lease_seconds: float):
        assert run_id == self.run_id
        self.prepare_calls.append((run_id, lease_seconds))
        self.leases.update(
            task.dataset for task in self.tasks if task.status == "queued"
        )
        return self.tasks

    def release_run_submission(self, run_id: str) -> int:
        assert run_id == self.run_id
        self.release_calls.append(run_id)
        released = len(self.leases)
        self.leases.clear()
        return released

    def execute_run(self, run_id: str):
        assert run_id == self.run_id
        self.execute_calls.append(run_id)
        return SimpleNamespace(status="success")


class _SubmissionExecutor:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, *args):
        self.calls.append((function, args))
        if self.reject:
            raise RuntimeError("executor capacity is exhausted")
        return SimpleNamespace(kind="accepted")


def _claim_original_run(engine, *, now: datetime):
    key = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    with engine.begin() as connection:
        claim = PostgresCollectionIdempotencyRepository(connection).claim(
            key,
            semantics,
            run_id="run-original",
            task_ids=_task_ids("task-original"),
            now=now,
        )
    return key, semantics, claim.binding


def _submission_service(
    engine,
    *,
    commands: _SubmissionCommands,
    queries: _SubmissionQueries,
    executor: _SubmissionExecutor,
    now: datetime,
) -> RecoverableCollectionSubmissionService:
    return RecoverableCollectionSubmissionService(
        unit_of_work_factory=lambda: _IdempotencyUnitOfWork(engine),
        commands=commands,
        queries=queries,
        executor=executor,
        clock=lambda: now,
        submission_lease_seconds=1800,
        task_lease_seconds=1800,
    )


def _persistence_counts(engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM collection_runs),
                      (SELECT COUNT(*) FROM collection_tasks),
                      (SELECT COUNT(*) FROM collection_idempotency_bindings)
                    """
                )
            ).one()
        )


def test_atomic_claim_replay_and_conflict_create_one_run_and_seven_tasks(tmp_path) -> None:
    engine = _engine(tmp_path / "idempotency.sqlite3")
    key = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)

    with engine.begin() as connection:
        created = PostgresCollectionIdempotencyRepository(connection).claim(
            key,
            semantics,
            run_id="run-created",
            task_ids=_task_ids("task-created"),
            now=now,
        )
    with engine.begin() as connection:
        replay = PostgresCollectionIdempotencyRepository(connection).claim(
            key,
            semantics,
            run_id="run-replay-must-rollback",
            task_ids=_task_ids("task-replay"),
            now=now,
        )
    with engine.begin() as connection:
        conflict = PostgresCollectionIdempotencyRepository(connection).claim(
            key,
            FullCollectionSemantics.create(date(2026, 10, 16)),
            run_id="run-conflict-must-rollback",
            task_ids=_task_ids("task-conflict"),
            now=now,
        )
        counts = connection.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM collection_runs),
                  (SELECT COUNT(*) FROM collection_tasks),
                  (SELECT COUNT(*) FROM collection_idempotency_bindings)
                """
            )
        ).one()
        datasets = tuple(
            connection.execute(
                text(
                    "SELECT dataset FROM collection_tasks "
                    "WHERE run_id='run-created' ORDER BY queued_at, rowid"
                )
            ).scalars()
        )

    assert created.disposition is IdempotencyClaimDisposition.CREATED
    assert replay.disposition is IdempotencyClaimDisposition.REPLAY
    assert conflict.disposition is IdempotencyClaimDisposition.CONFLICT
    assert replay.binding.run_id == created.binding.run_id == "run-created"
    assert conflict.binding.run_id == "run-created"
    assert tuple(counts) == (1, 7, 1)
    assert datasets == CANONICAL_FULL_COLLECTION_DATASETS
    engine.dispose()


def test_concurrent_first_claims_share_one_parent_and_canonical_tasks(tmp_path) -> None:
    engine = _engine(tmp_path / "concurrent-idempotency.sqlite3")
    barrier = Barrier(2)
    key = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)

    def claim(index: int):
        barrier.wait()
        with engine.begin() as connection:
            return PostgresCollectionIdempotencyRepository(connection).claim(
                key,
                semantics,
                run_id=f"run-{index}",
                task_ids=_task_ids(f"task-{index}"),
                now=now,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(claim, (1, 2)))

    with engine.connect() as connection:
        counts = tuple(
            connection.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM collection_runs),
                      (SELECT COUNT(*) FROM collection_tasks),
                      (SELECT COUNT(*) FROM collection_idempotency_bindings)
                    """
                )
            ).one()
        )
        run_ids = {
            str(value)
            for value in connection.execute(
                text("SELECT run_id FROM collection_idempotency_bindings")
            ).scalars()
        }

    assert {claim.disposition for claim in claims} == {
        IdempotencyClaimDisposition.CREATED,
        IdempotencyClaimDisposition.REPLAY,
    }
    assert {claim.binding.run_id for claim in claims} == run_ids
    assert counts == (1, 7, 1)
    engine.dispose()


def test_concurrent_submission_claims_have_one_live_owner(tmp_path) -> None:
    engine = _engine(tmp_path / "concurrent-submission-owner.sqlite3")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    key, semantics, original = _claim_original_run(engine, now=now)
    barrier = Barrier(2)

    def acquire(index: int):
        barrier.wait()
        with engine.begin() as connection:
            return PostgresCollectionIdempotencyRepository(
                connection
            ).acquire_submission(
                semantics.operation_scope,
                key,
                owner=f"owner-{index}",
                now=now,
                lease_seconds=1800,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        acquired = tuple(executor.map(acquire, (1, 2)))

    winners = tuple(binding for binding in acquired if binding is not None)
    assert len(winners) == 1
    assert winners[0].run_id == original.run_id
    assert winners[0].submission_state is SubmissionState.SUBMITTING
    assert winners[0].submission_attempts == 1
    assert winners[0].submission_owner in {"owner-1", "owner-2"}
    assert _persistence_counts(engine) == (1, 7, 1)
    engine.dispose()


def test_mark_submitted_keeps_a_recovery_window_before_takeover(tmp_path) -> None:
    engine = _engine(tmp_path / "submitted-recovery-window.sqlite3")
    key = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)

    with engine.begin() as connection:
        repository = PostgresCollectionIdempotencyRepository(connection)
        repository.claim(
            key,
            semantics,
            run_id="run-original",
            task_ids=_task_ids("task-original"),
            now=now,
        )
        acquired = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-original",
            now=now,
            lease_seconds=30,
        )
        assert acquired is not None
        submitted = repository.mark_submitted(
            semantics.operation_scope,
            key,
            owner="owner-original",
            now=now + timedelta(seconds=1),
            recovery_seconds=120,
        )

    assert submitted.submission_state is SubmissionState.SUBMITTED
    assert submitted.submission_owner is None
    assert submitted.submission_lease_expires_at == now + timedelta(seconds=121)
    assert submitted.submission_attempts == 1

    with engine.begin() as connection:
        repository = PostgresCollectionIdempotencyRepository(connection)
        before_expiry = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-too-early",
            now=now + timedelta(seconds=120),
            lease_seconds=30,
        )
        after_expiry = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-recovery",
            now=now + timedelta(seconds=122),
            lease_seconds=30,
        )

    assert before_expiry is None
    assert after_expiry is not None
    assert after_expiry.run_id == "run-original"
    assert after_expiry.submission_state is SubmissionState.SUBMITTING
    assert after_expiry.submission_attempts == 2
    assert after_expiry.submission_owner == "owner-recovery"
    engine.dispose()


def test_live_task_lease_blocks_stale_submission_takeover(tmp_path) -> None:
    engine = _engine(tmp_path / "live-task-lease-fence.sqlite3")
    key = IdempotencyKey("hermes-market-collection-2026-10-15-1630")
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    task_ids = _task_ids("task-original")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)

    with engine.begin() as connection:
        repository = PostgresCollectionIdempotencyRepository(connection)
        repository.claim(
            key,
            semantics,
            run_id="run-original",
            task_ids=task_ids,
            now=now,
        )
        acquired = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-original",
            now=now,
            lease_seconds=5,
        )
        assert acquired is not None
        connection.execute(
            text(
                """
                INSERT INTO refresh_leases(dataset, as_of, owner, expires_at)
                VALUES (:dataset, :as_of, :owner, :expires_at)
                """
            ),
            {
                "dataset": "core",
                "as_of": semantics.resolved_as_of,
                "owner": task_ids["core"],
                "expires_at": now + timedelta(seconds=60),
            },
        )

    with engine.begin() as connection:
        repository = PostgresCollectionIdempotencyRepository(connection)
        fenced = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-stale-takeover",
            now=now + timedelta(seconds=10),
            lease_seconds=30,
        )
        recovered = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-after-task-expiry",
            now=now + timedelta(seconds=61),
            lease_seconds=30,
        )

    assert fenced is None
    assert recovered is not None
    assert recovered.run_id == "run-original"
    assert recovered.submission_attempts == 2
    assert recovered.submission_owner == "owner-after-task-expiry"
    engine.dispose()


def test_capacity_rejection_releases_leases_and_same_key_replays_original_run(
    tmp_path,
) -> None:
    engine = _engine(tmp_path / "submission-rejection-replay.sqlite3")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    key, semantics, original = _claim_original_run(engine, now=now)
    commands = _SubmissionCommands(original.run_id)
    queries = _SubmissionQueries(original.run_id)
    rejected_executor = _SubmissionExecutor(reject=True)
    rejected_service = _submission_service(
        engine,
        commands=commands,
        queries=queries,
        executor=rejected_executor,
        now=now,
    )

    with pytest.raises(CollectionSubmissionRejected) as rejection:
        rejected_service.submit(semantics.operation_scope, key, original.run_id)

    failed = rejection.value.binding
    assert failed.run_id == original.run_id
    assert failed.submission_state is SubmissionState.SUBMISSION_FAILED
    assert failed.submission_attempts == 1
    assert failed.submission_error is not None
    assert failed.submission_error.category is CollectionFailureCategory.CONCURRENCY
    assert failed.submission_error.code == "EXECUTOR_SUBMISSION_REJECTED"
    assert failed.submission_error.retryable is True
    assert commands.release_calls == [original.run_id]
    assert commands.leases == set()
    assert _persistence_counts(engine) == (1, 7, 1)

    accepted_executor = _SubmissionExecutor()
    replay_service = _submission_service(
        engine,
        commands=commands,
        queries=queries,
        executor=accepted_executor,
        now=now + timedelta(seconds=1),
    )
    replay = replay_service.submit(
        semantics.operation_scope,
        key,
        original.run_id,
    )
    duplicate = replay_service.submit(
        semantics.operation_scope,
        key,
        original.run_id,
    )

    assert replay.disposition is RecoverableSubmissionDisposition.SUBMITTED
    assert replay.binding.run_id == original.run_id
    assert replay.binding.submission_state is SubmissionState.SUBMITTED
    assert replay.binding.submission_attempts == 2
    assert duplicate.disposition is RecoverableSubmissionDisposition.ACTIVE
    assert duplicate.binding.run_id == original.run_id
    assert len(accepted_executor.calls) == 1
    assert accepted_executor.calls[0][1] == (original.run_id,)
    assert _persistence_counts(engine) == (1, 7, 1)
    engine.dispose()


def test_active_submitting_replay_does_not_prepare_or_submit_again(tmp_path) -> None:
    engine = _engine(tmp_path / "active-submitting-replay.sqlite3")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    key, semantics, original = _claim_original_run(engine, now=now)
    with engine.begin() as connection:
        active = PostgresCollectionIdempotencyRepository(
            connection
        ).acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-live",
            now=now,
            lease_seconds=120,
        )
    assert active is not None

    commands = _SubmissionCommands(original.run_id)
    executor = _SubmissionExecutor()
    replay = _submission_service(
        engine,
        commands=commands,
        queries=_SubmissionQueries(original.run_id),
        executor=executor,
        now=now + timedelta(seconds=30),
    ).submit(semantics.operation_scope, key, original.run_id)

    assert replay.disposition is RecoverableSubmissionDisposition.ACTIVE
    assert replay.binding.submission_state is SubmissionState.SUBMITTING
    assert replay.binding.submission_attempts == 1
    assert commands.prepare_calls == []
    assert executor.calls == []
    assert _persistence_counts(engine) == (1, 7, 1)
    engine.dispose()


@pytest.mark.parametrize("stale_state", ("submitting", "submitted"))
def test_expired_submission_state_replays_original_run_without_replacement(
    tmp_path,
    stale_state: str,
) -> None:
    engine = _engine(tmp_path / f"expired-{stale_state}-replay.sqlite3")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    key, semantics, original = _claim_original_run(engine, now=now)
    with engine.begin() as connection:
        repository = PostgresCollectionIdempotencyRepository(connection)
        acquired = repository.acquire_submission(
            semantics.operation_scope,
            key,
            owner="owner-lost",
            now=now,
            lease_seconds=5,
        )
        assert acquired is not None
        if stale_state == "submitted":
            repository.mark_submitted(
                semantics.operation_scope,
                key,
                owner="owner-lost",
                now=now,
                recovery_seconds=5,
            )

    commands = _SubmissionCommands(original.run_id)
    executor = _SubmissionExecutor()
    recovered = _submission_service(
        engine,
        commands=commands,
        queries=_SubmissionQueries(original.run_id),
        executor=executor,
        now=now + timedelta(seconds=6),
    ).submit(semantics.operation_scope, key, original.run_id)

    assert recovered.disposition is RecoverableSubmissionDisposition.SUBMITTED
    assert recovered.binding.run_id == original.run_id
    assert recovered.binding.submission_state is SubmissionState.SUBMITTED
    assert recovered.binding.submission_attempts == 2
    assert len(executor.calls) == 1
    assert executor.calls[0][1] == (original.run_id,)
    assert _persistence_counts(engine) == (1, 7, 1)
    engine.dispose()


def test_terminal_original_run_is_finalized_without_executor_submission(tmp_path) -> None:
    engine = _engine(tmp_path / "terminal-original-run.sqlite3")
    now = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    key, semantics, original = _claim_original_run(engine, now=now)
    commands = _SubmissionCommands(original.run_id, task_status="success")
    executor = _SubmissionExecutor()
    result = _submission_service(
        engine,
        commands=commands,
        queries=_SubmissionQueries(original.run_id, status="success"),
        executor=executor,
        now=now + timedelta(seconds=1),
    ).submit(semantics.operation_scope, key, original.run_id)

    assert result.disposition is RecoverableSubmissionDisposition.TERMINAL
    assert result.binding.run_id == original.run_id
    assert result.binding.submission_state is SubmissionState.SUBMITTED
    assert result.binding.submission_attempts == 1
    assert executor.calls == []
    assert commands.execute_calls == []
    assert _persistence_counts(engine) == (1, 7, 1)
    engine.dispose()
