"""Persistence-to-provider integration tests for full-collection idempotency."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import create_engine, event, text

from src.market_environment.application.collection import (
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
)
from src.market_environment.application.commands import (
    CollectionSubmissionRejected,
    FullCollectionCommand,
    FullCollectionIdempotencyConflictError,
    RecoverableCollectionSubmissionService,
)
from src.market_environment.application.ports import DatasetCommitEvidence
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    FullCollectionSemantics,
    IdempotencyClaimDisposition,
    IdempotencyKey,
    SubmissionState,
)
from src.market_environment.infrastructure.compatibility import (
    CoordinatorCollectionCommandAdapter,
    CoordinatorCollectionQueryAdapter,
)
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresCollectionIdempotencyRepository,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 10, 15)
AFTER_MARKET = datetime(2026, 10, 15, 16, 30, tzinfo=MARKET_TIME_ZONE)
NEXT_AFTER_MARKET = AFTER_MARKET + timedelta(days=1)
KEY = IdempotencyKey("hermes-market-collection-2026-10-15-1630")


IDEMPOTENCY_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_idempotency_bindings (
    operation_scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    semantic_fingerprint TEXT NOT NULL,
    resolved_as_of TEXT NOT NULL,
    operation_version TEXT NOT NULL,
    dataset_fingerprint TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES collection_runs(run_id),
    submission_state TEXT NOT NULL DEFAULT 'reserved',
    submission_attempts INTEGER NOT NULL DEFAULT 0,
    submission_owner TEXT,
    submission_lease_expires_at TEXT,
    submission_error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT,
    PRIMARY KEY(operation_scope, idempotency_key)
)
"""


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


@dataclass
class _IdempotencyAwareStore:
    """Model the PostgreSQL queued-task guard in the SQLite integration fixture."""

    delegate: SnapshotStore

    def expire_inactive_collection_tasks(self, *, now=None) -> int:
        del now
        return 0

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class _AllowingFuyaoPolicy:
    def preflight_error(self, dataset: str) -> None:
        del dataset
        return None


class _ProviderCalls:
    def __init__(self) -> None:
        self._calls: list[DatasetDate] = []
        self._lock = Lock()

    def record(self, identity: DatasetDate) -> None:
        with self._lock:
            self._calls.append(identity)

    def counts(self) -> Counter[str]:
        with self._lock:
            return Counter(item.dataset for item in self._calls)

    def total(self) -> int:
        with self._lock:
            return len(self._calls)


@dataclass
class _CountingProviderCollector:
    dataset_id: str
    provider_calls: _ProviderCalls

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        self.provider_calls.record(identity)
        payload = {
            "asOf": identity.as_of.isoformat(),
            "quality": {
                "dataset": identity.dataset,
                "source": "idempotency-fixture-provider",
                "provider": "idempotency-fixture-provider",
                "status": "ok",
                "observations": 1,
                "asOf": identity.as_of.isoformat(),
                "warning": None,
                "warnings": [],
            },
        }
        if identity.dataset == "core":
            payload["indices"] = [
                {
                    "code": "sh000001",
                    "history": [
                        {"date": identity.as_of.isoformat(), "close": 3200}
                    ],
                }
            ]
        candidate = CollectionCandidate(
            identity=identity,
            payload=payload,
            source="idempotency-fixture-provider",
            status="ok",
            observations=1,
            warnings=(),
            settled=True,
            actual_as_of=identity.as_of,
            fetched_at=AFTER_MARKET,
        )
        return CollectionOutcome(
            identity,
            CollectionTaskState.SUCCESS,
            candidate=candidate,
        )


@dataclass
class _SnapshotCommitter:
    dataset_id: str
    store: SnapshotStore

    def commit(self, request) -> DatasetCommitEvidence:
        candidate = request.candidate
        self.store.put(
            SnapshotRecord(
                dataset=candidate.identity.dataset,
                as_of=candidate.identity.as_of,
                payload=dict(candidate.payload),
                source=candidate.source,
                status=candidate.status,
                observations=candidate.observations,
                warnings=candidate.warnings,
                fetched_at=candidate.fetched_at or AFTER_MARKET,
                settled=candidate.settled,
            ),
            lease=request.lease,
            now=AFTER_MARKET,
        )
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=candidate,
            writes=("snapshot",),
        )


class _ImmediateExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, *args):
        self.calls.append((function, args))
        future: Future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:  # pragma: no cover - surfaced by focused failures
            future.set_exception(error)
            raise
        return future


class _RejectingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, *args):
        self.calls.append((function, args))
        raise RuntimeError("fixture executor capacity is exhausted")


class _GateExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...]]] = []
        self.started = Event()
        self.release = Event()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._futures: list[Future] = []
        self._lock = Lock()

    def submit(self, function, *args):
        with self._lock:
            self.calls.append((function, args))

        def execute_after_release():
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("fixture executor was not released")
            return function(*args)

        future = self._pool.submit(execute_after_release)
        self._futures.append(future)
        return future

    def finish(self) -> None:
        self.release.set()
        for future in self._futures:
            future.result(timeout=10)

    def shutdown(self) -> None:
        self.release.set()
        self._pool.shutdown(wait=True)


@dataclass
class _Harness:
    command: FullCollectionCommand
    queries: CoordinatorCollectionQueryAdapter
    store: SnapshotStore
    engine: object
    executor: object
    provider_calls: _ProviderCalls
    unit_of_work_factory: object

    def persistence_counts(self) -> tuple[int, int, int]:
        with self.engine.connect() as connection:
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

    def close(self) -> None:
        shutdown = getattr(self.executor, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self.engine.dispose()


def _build_harness(
    database_path: Path,
    *,
    executor,
    provider_calls: _ProviderCalls | None = None,
    current: datetime = AFTER_MARKET,
) -> _Harness:
    raw_store = SnapshotStore(database_path)
    guarded_store = _IdempotencyAwareStore(raw_store)
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA busy_timeout=10000")

    with engine.begin() as connection:
        connection.exec_driver_sql(IDEMPOTENCY_SCHEMA)

    calls = provider_calls or _ProviderCalls()
    collectors = tuple(
        _CountingProviderCollector(dataset, calls)
        for dataset in CANONICAL_FULL_COLLECTION_DATASETS
    )
    committers = tuple(
        _SnapshotCommitter(dataset, raw_store)
        for dataset in CANONICAL_FULL_COLLECTION_DATASETS
    )
    coordinator = CollectionCoordinator(
        None,
        guarded_store,
        now=lambda: current,
        fuyao_policy=_AllowingFuyaoPolicy(),
        collector_registry=DatasetCollectorRegistry.complete(collectors),
        committer_registry=DatasetCommitterRegistry.complete(committers),
        typed_cutover_datasets=CANONICAL_FULL_COLLECTION_DATASETS,
    )
    queries = CoordinatorCollectionQueryAdapter(coordinator)
    commands = CoordinatorCollectionCommandAdapter(coordinator, executor)

    def unit_of_work_factory():
        return _IdempotencyUnitOfWork(engine)

    submission_service = RecoverableCollectionSubmissionService(
        unit_of_work_factory=unit_of_work_factory,
        commands=commands,
        queries=queries,
        executor=executor,
        clock=lambda: current.astimezone(timezone.utc),
        submission_lease_seconds=1800,
        task_lease_seconds=1800,
    )
    command = FullCollectionCommand(
        unit_of_work_factory=unit_of_work_factory,
        submission_service=submission_service,
        queries=queries,
        clock=lambda: current,
        settlement_boundary=time(15, 10),
    )
    return _Harness(
        command=command,
        queries=queries,
        store=raw_store,
        engine=engine,
        executor=executor,
        provider_calls=calls,
        unit_of_work_factory=unit_of_work_factory,
    )


def _assert_one_provider_call_per_dataset(calls: _ProviderCalls) -> None:
    assert calls.total() == len(CANONICAL_FULL_COLLECTION_DATASETS)
    assert calls.counts() == Counter(
        {dataset: 1 for dataset in CANONICAL_FULL_COLLECTION_DATASETS}
    )


def test_serial_uncertain_and_terminal_replays_never_recollect(tmp_path) -> None:
    executor = _GateExecutor()
    harness = _build_harness(tmp_path / "serial-replay.sqlite3", executor=executor)
    try:
        first = harness.command.execute(KEY)
        assert executor.started.wait(timeout=5)

        # Model a lost first HTTP response: the caller knows only its stable key.
        uncertain_response_replay = harness.command.execute(KEY)

        assert uncertain_response_replay.run_id == first.run_id
        assert first.claim_disposition is IdempotencyClaimDisposition.CREATED
        assert (
            uncertain_response_replay.claim_disposition
            is IdempotencyClaimDisposition.REPLAY
        )
        assert len(executor.calls) == 1
        assert harness.provider_calls.total() == 0
        assert harness.persistence_counts() == (1, 7, 1)

        executor.finish()
        terminal = harness.queries.get_run(first.run_id)
        assert terminal.run.status == "success"
        _assert_one_provider_call_per_dataset(harness.provider_calls)

        terminal_replay = harness.command.execute(KEY)

        assert terminal_replay.run_id == first.run_id
        assert terminal_replay.run.run.status == "success"
        assert terminal_replay.submission is None
        assert len(executor.calls) == 1
        _assert_one_provider_call_per_dataset(harness.provider_calls)
        assert harness.persistence_counts() == (1, 7, 1)
    finally:
        harness.close()


def test_concurrent_matching_replays_share_run_submission_and_provider_calls(
    tmp_path,
) -> None:
    executor = _GateExecutor()
    harness = _build_harness(
        tmp_path / "concurrent-replay.sqlite3",
        executor=executor,
    )
    request_barrier = Barrier(2)

    def invoke(_index: int):
        request_barrier.wait()
        return harness.command.execute(KEY)

    try:
        with ThreadPoolExecutor(max_workers=2) as requests:
            results = tuple(requests.map(invoke, (1, 2)))

        assert {result.run_id for result in results} == {results[0].run_id}
        assert {result.claim_disposition for result in results} == {
            IdempotencyClaimDisposition.CREATED,
            IdempotencyClaimDisposition.REPLAY,
        }
        assert len(executor.calls) == 1
        assert harness.provider_calls.total() == 0
        assert harness.persistence_counts() == (1, 7, 1)

        executor.finish()

        assert harness.queries.get_run(results[0].run_id).run.status == "success"
        _assert_one_provider_call_per_dataset(harness.provider_calls)
    finally:
        harness.close()


def test_restart_replay_recovers_rejected_executor_without_replacement_run(
    tmp_path,
) -> None:
    database_path = tmp_path / "restart-after-rejection.sqlite3"
    provider_calls = _ProviderCalls()
    rejected_executor = _RejectingExecutor()
    first_process = _build_harness(
        database_path,
        executor=rejected_executor,
        provider_calls=provider_calls,
    )
    try:
        with pytest.raises(CollectionSubmissionRejected) as rejected:
            first_process.command.execute(KEY)

        original_run_id = rejected.value.binding.run_id
        assert rejected.value.binding.submission_state is SubmissionState.SUBMISSION_FAILED
        assert rejected.value.binding.submission_error is not None
        assert rejected.value.binding.submission_error.code == "EXECUTOR_SUBMISSION_REJECTED"
        assert len(rejected_executor.calls) == 1
        assert provider_calls.total() == 0
        assert first_process.persistence_counts() == (1, 7, 1)
        original = first_process.queries.get_run(original_run_id)
        assert all(task.status == "queued" for task in original.tasks)
        assert all(
            first_process.store.get_lease_token(
                task.dataset,
                task.as_of,
                owner=task.task_id,
            )
            is None
            for task in original.tasks
        )
    finally:
        first_process.close()

    accepted_executor = _ImmediateExecutor()
    restarted_process = _build_harness(
        database_path,
        executor=accepted_executor,
        provider_calls=provider_calls,
    )
    try:
        recovered = restarted_process.command.execute(KEY)

        assert recovered.run_id == original_run_id
        assert recovered.claim_disposition is IdempotencyClaimDisposition.REPLAY
        assert recovered.run.run.status == "success"
        assert recovered.binding.submission_attempts == 2
        assert len(accepted_executor.calls) == 1
        _assert_one_provider_call_per_dataset(provider_calls)
        assert restarted_process.persistence_counts() == (1, 7, 1)

        restarted_process.command.execute(KEY)
        assert len(accepted_executor.calls) == 1
        _assert_one_provider_call_per_dataset(provider_calls)
    finally:
        restarted_process.close()


def test_same_key_cross_date_and_version_conflicts_do_no_new_work(tmp_path) -> None:
    executor = _GateExecutor()
    harness = _build_harness(
        tmp_path / "semantic-conflicts.sqlite3",
        executor=executor,
    )
    try:
        original = harness.command.execute(KEY)
        assert executor.started.wait(timeout=5)

        next_date_command = replace(
            harness.command,
            clock=lambda: NEXT_AFTER_MARKET,
        )
        with pytest.raises(FullCollectionIdempotencyConflictError) as cross_date:
            next_date_command.execute(KEY)

        assert cross_date.value.binding.run_id == original.run_id
        assert cross_date.value.requested.resolved_as_of == NEXT_AFTER_MARKET.date()

        version_two = FullCollectionSemantics(
            resolved_as_of=AS_OF,
            operation_version="v2",
        )
        with harness.unit_of_work_factory() as unit_of_work:
            version_conflict = unit_of_work.collection_idempotency.claim(
                KEY,
                version_two,
                run_id="run-v2-must-not-persist",
                task_ids={
                    dataset: f"task-v2-{index}"
                    for index, dataset in enumerate(
                        CANONICAL_FULL_COLLECTION_DATASETS,
                        start=1,
                    )
                },
                now=AFTER_MARKET.astimezone(timezone.utc),
            )
            unit_of_work.commit()

        assert version_conflict.disposition is IdempotencyClaimDisposition.CONFLICT
        assert version_conflict.binding.run_id == original.run_id
        assert version_conflict.binding.operation_version == "v1"
        assert harness.persistence_counts() == (1, 7, 1)
        assert len(executor.calls) == 1
        assert harness.provider_calls.total() == 0

        executor.finish()
        _assert_one_provider_call_per_dataset(harness.provider_calls)
    finally:
        harness.close()


def test_different_keys_same_date_rely_on_leases_and_do_not_duplicate_provider_calls(
    tmp_path,
) -> None:
    executor = _GateExecutor()
    harness = _build_harness(
        tmp_path / "different-keys-same-date.sqlite3",
        executor=executor,
    )
    second_key = IdempotencyKey("manual-recovery-2026-10-15")
    try:
        first = harness.command.execute(KEY)
        assert executor.started.wait(timeout=5)

        competing = harness.command.execute(second_key)

        assert competing.run_id != first.run_id
        assert competing.run.run.status == "failed"
        assert {task.status for task in competing.run.tasks} == {"busy"}
        assert len(executor.calls) == 1
        assert harness.provider_calls.total() == 0
        assert harness.persistence_counts() == (2, 14, 2)

        executor.finish()

        assert harness.queries.get_run(first.run_id).run.status == "success"
        _assert_one_provider_call_per_dataset(harness.provider_calls)

        busy_replay = harness.command.execute(second_key)
        assert busy_replay.run_id == competing.run_id
        assert busy_replay.run.run.status == "failed"
        assert len(executor.calls) == 1
        _assert_one_provider_call_per_dataset(harness.provider_calls)
    finally:
        harness.close()
