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
