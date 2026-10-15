from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import (
    CollectionRunRepository,
    CollectionTaskRepository,
    CoreIndexResultRepository,
)
from src.market_environment.domain.models import (
    CollectionFailureCategory,
    StructuredTaskFailure,
)
from src.market_environment.infrastructure.collection.coordinator import (
    CollectionCoordinator,
)
from src.market_environment.infrastructure.persistence.postgres import (
    PostgresCollectionRunRepository,
    PostgresCollectionTaskRepository,
    PostgresCoreIndexResultRepository,
)
from src.market_environment.snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    CoreIndexResultRecord,
)


AS_OF = date(2026, 9, 14)
NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def collection_connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    connection = engine.connect()
    for statement in (
        """
        CREATE TABLE collection_runs (
            run_id TEXT PRIMARY KEY, as_of DATE NOT NULL, status TEXT NOT NULL,
            requested_datasets_json TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT, completed_at TEXT
        )
        """,
        """
        CREATE TABLE collection_tasks (
            task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset TEXT NOT NULL,
            as_of DATE NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
            observations INTEGER NOT NULL, warning TEXT, failure_json TEXT,
            timings_json TEXT NOT NULL, queued_at TEXT, started_at TEXT, completed_at TEXT,
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
        CREATE TABLE refresh_leases (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, owner TEXT NOT NULL,
            expires_at TEXT NOT NULL, PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE snapshot_entries (
            dataset TEXT NOT NULL, as_of DATE NOT NULL, PRIMARY KEY(dataset, as_of)
        )
        """,
        """
        CREATE TABLE collection_idempotency_bindings (
            run_id TEXT NOT NULL UNIQUE, submission_state TEXT NOT NULL
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


def _run(run_id: str = "run-1") -> CollectionRunRecord:
    return CollectionRunRecord(run_id, AS_OF, "queued", ("core", "breadth"), NOW)


def _task(task_id: str, dataset: str, *, status: str = "queued") -> CollectionTaskRecord:
    return CollectionTaskRecord(
        task_id=task_id,
        run_id="run-1",
        dataset=dataset,
        as_of=AS_OF,
        status=status,
        queued_at=NOW,
    )


class RepositoryStatusStore:
    def __init__(self, runs, tasks) -> None:
        self.runs = runs
        self.tasks = tasks

    def expire_inactive_collection_tasks(self, *, now) -> int:
        return self.tasks.expire_inactive(now=now)

    def get_collection_run(self, run_id: str):
        return self.runs.get_run(run_id)

    def list_collection_tasks(self, run_id: str):
        return self.tasks.list_tasks(run_id)

    def update_collection_run(self, run_id: str, status: str, **values):
        return self.runs.transition_run(run_id, status, **values)


def test_run_repository_preserves_legal_transitions(collection_connection) -> None:
    repository = PostgresCollectionRunRepository(collection_connection)
    repository.create_run(_run())

    collecting = repository.transition_run("run-1", "collecting", started_at=NOW)
    success = repository.transition_run(
        "run-1",
        "success",
        completed_at=NOW + timedelta(seconds=2),
    )

    assert isinstance(repository, CollectionRunRepository)
    assert collecting.started_at == NOW
    assert success.status == "success"
    with pytest.raises(ValueError, match="transition rejected"):
        repository.transition_run("run-1", "collecting")


def test_task_repository_expected_state_and_restart_recovery(collection_connection) -> None:
    runs = PostgresCollectionRunRepository(collection_connection)
    tasks = PostgresCollectionTaskRepository(collection_connection)
    runs.create_run(_run())
    tasks.create_task(_task("task-core", "core"))
    tasks.create_task(_task("task-breadth", "breadth"))
    collection_connection.exec_driver_sql(
        "INSERT INTO snapshot_entries(dataset, as_of) VALUES (?, ?)",
        ("core", AS_OF.isoformat()),
    )

    collecting = tasks.transition_task(
        "task-core",
        "collecting",
        expected_statuses=("queued",),
        started_at=NOW,
    )
    with pytest.raises(ValueError, match="transition rejected"):
        tasks.transition_task(
            "task-core",
            "success",
            expected_statuses=("queued",),
        )
    recovered = tasks.expire_inactive(now=NOW + timedelta(minutes=10))

    assert isinstance(tasks, CollectionTaskRepository)
    assert collecting.status == "collecting"
    assert recovered == 2
    assert tasks.get_task("task-core").status == "failed-retained"
    assert tasks.get_task("task-breadth").status == "failed-missing"
    assert "retryable" in tasks.get_task("task-breadth").warning
    assert (
        tasks.get_task("task-core").failure.category
        is CollectionFailureCategory.WORKER_INTERRUPTED
    )
    assert tasks.get_task("task-core").failure.retained is True
    assert tasks.get_task("task-breadth").failure.retained is False


@pytest.mark.parametrize("submission_state", ("reserved", "submitted"))
def test_status_read_expiration_preserves_claimed_queued_tasks(
    collection_connection,
    submission_state: str,
) -> None:
    runs = PostgresCollectionRunRepository(collection_connection)
    tasks = PostgresCollectionTaskRepository(collection_connection)
    runs.create_run(_run())
    tasks.create_task(_task("task-core", "core"))
    collection_connection.exec_driver_sql(
        """
        INSERT INTO collection_idempotency_bindings(run_id, submission_state)
        VALUES (?, ?)
        """,
        ("run-1", submission_state),
    )

    coordinator = object.__new__(CollectionCoordinator)
    coordinator.store = RepositoryStatusStore(runs, tasks)
    coordinator._now = lambda: NOW + timedelta(minutes=10)

    status = coordinator.get_run("run-1")

    assert status is not None
    assert status.run.status == "queued"
    assert status.tasks[0].status == "queued"
    queued = tasks.get_task("task-core")
    assert queued is not None
    assert queued.status == "queued"
    assert queued.failure is None


def test_task_repository_failure_codec_survives_repository_restart(
    collection_connection,
) -> None:
    runs = PostgresCollectionRunRepository(collection_connection)
    tasks = PostgresCollectionTaskRepository(collection_connection)
    runs.create_run(_run())
    failure = StructuredTaskFailure(
        category=CollectionFailureCategory.CONCURRENCY,
        message="another task owns the dataset/date lease",
        retryable=True,
        retained=False,
        stage="lease-acquisition",
        blocked_by=("industry-ranking",),
    )
    tasks.create_task(
        CollectionTaskRecord(
            task_id="task-core",
            run_id="run-1",
            dataset="core",
            as_of=AS_OF,
            status="busy",
            warning="another task owns the lease",
            failure=failure,
            queued_at=NOW,
        )
    )

    restarted = PostgresCollectionTaskRepository(collection_connection)
    restored = restarted.get_task("task-core")
    assert restored.failure == failure
    assert restored.warning == "another task owns the lease"

    preserved = restarted.transition_task(
        "task-core",
        "busy",
        expected_statuses=("busy",),
        timings={"leaseWaitMs": 3.5},
    )
    assert preserved.failure == failure
    assert preserved.timings == {"leaseWaitMs": 3.5}

    successful = restarted.transition_task(
        "task-core",
        "success",
        expected_statuses=("busy",),
        source="fixture",
        observations=1,
    )
    assert successful.failure is None


def test_active_task_requires_matching_unexpired_owner_lease(collection_connection) -> None:
    runs = PostgresCollectionRunRepository(collection_connection)
    tasks = PostgresCollectionTaskRepository(collection_connection)
    runs.create_run(_run())
    tasks.create_task(_task("task-core", "core"))
    collection_connection.exec_driver_sql(
        "INSERT INTO refresh_leases(dataset, as_of, owner, expires_at) VALUES (?, ?, ?, ?)",
        (
            "core",
            AS_OF.isoformat(),
            "task-core",
            (NOW + timedelta(minutes=5)).isoformat(),
        ),
    )

    assert tasks.active_task("core", AS_OF, now=NOW).task_id == "task-core"
    assert tasks.active_task(
        "core",
        AS_OF,
        now=NOW + timedelta(minutes=6),
    ) is None


def test_core_index_results_upsert_and_list_in_code_order(collection_connection) -> None:
    repository = PostgresCoreIndexResultRepository(collection_connection)
    second = CoreIndexResultRecord(
        "task-core", "sz399001", "深证成指", "success", "fixture", 10,
        payload={"close": 100},
    )
    first = CoreIndexResultRecord(
        "task-core", "sh000001", "上证指数", "partial", "fixture", 9,
        warning="fallback",
        payload={"close": 90},
    )

    repository.put_result(second)
    repository.put_result(first)
    updated = CoreIndexResultRecord(
        "task-core", "sh000001", "上证指数", "success", "fixture", 10,
        payload={"close": 91},
    )
    repository.put_result(updated)

    assert isinstance(repository, CoreIndexResultRepository)
    results = repository.list_results("task-core")
    assert [item.code for item in results] == ["sh000001", "sz399001"]
    assert results[0] == updated
