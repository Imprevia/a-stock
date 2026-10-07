from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient

from src.market_environment.application.commands import (
    ExecuteCollectionRunCommand,
    RebuildAggregateCommand,
    RefreshDatasetsCommand,
    StartCollectionRunCommand,
    SubmitCollectionRunCommand,
)
from src.market_environment.application.ports import TaskExecutor
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.infrastructure.compatibility import (
    CoordinatorCollectionCommandAdapter,
)
from src.market_environment.infrastructure.execution import BoundedTaskExecutor
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotStore
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 9, 14)
NOW = datetime(2026, 9, 14, 16, 0, tzinfo=MARKET_TIME_ZONE)


class FakeCollectionCommands:
    def __init__(self) -> None:
        self.calls = []

    def start_run(self, as_of, datasets=None):
        self.calls.append(("start", as_of, tuple(datasets or ())))
        return {"kind": "started", "asOf": as_of, "datasets": tuple(datasets or ())}

    def submit_run(self, run_id):
        self.calls.append(("submit", run_id))
        return run_id

    def execute_run(self, run_id):
        self.calls.append(("execute", run_id))
        return {"kind": "executed", "runId": run_id}

    def refresh(
        self,
        as_of,
        datasets=None,
        *,
        allow_historical_latest_only=False,
        fetch_previous_limit_details=True,
    ):
        self.calls.append(
            (
                "refresh",
                as_of,
                tuple(datasets or ()),
                allow_historical_latest_only,
                fetch_previous_limit_details,
            )
        )
        return {"kind": "refreshed", "asOf": as_of}


class FakeAggregateCommands:
    def __init__(self) -> None:
        self.calls = []

    def rebuild(self, as_of):
        self.calls.append(as_of)
        return {"asOf": as_of.isoformat(), "rebuilt": True}


class ImmediateTask:
    def __init__(self, value) -> None:
        self._value = value

    def result(self, timeout=None):
        return self._value


class ImmediateExecutor:
    def __init__(self) -> None:
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return ImmediateTask(function(*args, **kwargs))

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        return None


class NoopExecutor:
    def __init__(self) -> None:
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return ImmediateTask(None)

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        return None


class ForbiddenProvider:
    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"provider execution was not expected: {name}")


def test_collection_and_aggregate_command_use_cases_delegate_through_ports() -> None:
    collection = FakeCollectionCommands()
    aggregate = FakeAggregateCommands()
    immediate = ImmediateExecutor()
    start = StartCollectionRunCommand(collection)
    execute = ExecuteCollectionRunCommand(collection)

    started = start.execute(AS_OF, ("core", "breadth"))
    executed = execute.execute("run-1")
    submitted = SubmitCollectionRunCommand(immediate, execute).execute("run-2").result()
    refreshed = RefreshDatasetsCommand(collection).execute(
        AS_OF,
        ("limits",),
        allow_historical_latest_only=True,
        fetch_previous_limit_details=False,
    )
    rebuilt = RebuildAggregateCommand(aggregate).execute(AS_OF)

    assert started["kind"] == "started"
    assert executed == {"kind": "executed", "runId": "run-1"}
    assert submitted == {"kind": "executed", "runId": "run-2"}
    assert refreshed["kind"] == "refreshed"
    assert rebuilt == {"asOf": AS_OF.isoformat(), "rebuilt": True}
    assert collection.calls[-1] == (
        "refresh",
        AS_OF,
        ("limits",),
        True,
        False,
    )
    assert aggregate.calls == [AS_OF]
    assert isinstance(immediate, TaskExecutor)


def test_bounded_executor_rejects_work_beyond_running_and_queue_capacity() -> None:
    started = Event()
    release = Event()
    executor = BoundedTaskExecutor(max_workers=1, max_pending_tasks=0)

    def blocking_task():
        started.set()
        release.wait(timeout=5)
        return "done"

    first = executor.submit(blocking_task)
    assert started.wait(timeout=2)
    with pytest.raises(RuntimeError, match="capacity is exhausted"):
        executor.submit(lambda: "unexpected")

    release.set()
    assert first.result(timeout=2) == "done"
    assert executor.submit(lambda: "next").result(timeout=2) == "next"
    executor.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        executor.submit(lambda: None)


@dataclass(frozen=True)
class HttpCommandUseCases:
    coordinator: CollectionCoordinator
    start: StartCollectionRunCommand
    submit: SubmitCollectionRunCommand

    def start_run(self, as_of, datasets=None):
        return self.start.execute(as_of, datasets)

    def submit_run(self, run_id):
        return self.submit.execute(run_id)


def test_http_post_returns_202_before_noop_executor_runs_provider(tmp_path) -> None:
    provider = ForbiddenProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "commands.sqlite3"),
        now=lambda: NOW,
    )
    legacy = CoordinatorCollectionCommandAdapter(coordinator, NoopExecutor())
    execute = ExecuteCollectionRunCommand(legacy)
    noop = NoopExecutor()
    commands = HttpCommandUseCases(
        coordinator,
        StartCollectionRunCommand(legacy),
        SubmitCollectionRunCommand(noop, execute),
    )
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=commands,
            effective_date=AS_OF,
        )
    )

    response = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "collecting"
    assert response.json()["tasks"][0]["status"] == "queued"
    assert len(noop.calls) == 1
    assert provider.calls == []
