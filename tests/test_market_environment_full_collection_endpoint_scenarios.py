"""Scenario coverage for the sync-first full-collection HTTP endpoint."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timezone
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from src.market_environment.application.commands import FullCollectionCommand
from src.market_environment.collection import CollectionCoordinator, CollectionStartResult
from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    CollectionFailureCategory,
    StructuredTaskFailure,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    SnapshotStore,
)
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 16, 30, tzinfo=MARKET_TIME_ZONE)
RUN_ID = "run-full-scenarios"
ENDPOINT = "/api/market-environment/collection-runs/full"
HEADERS = {"Idempotency-Key": "hermes-market-collection-2026-10-15-1630"}


def _failure(
    category: CollectionFailureCategory,
    message: str,
    *,
    retained: bool = False,
    stage: str = "acquisition",
    blocked_by: tuple[str, ...] = (),
) -> StructuredTaskFailure:
    return StructuredTaskFailure(
        category=category,
        message=message,
        retryable=True,
        retained=retained,
        source="fixture-provider" if category is not CollectionFailureCategory.DEPENDENCY else None,
        stage=stage,
        blocked_by=blocked_by,
    )


def _result(
    parent_status: str,
    overrides: dict[str, dict[str, object]] | None = None,
    *,
    run_id: str = RUN_ID,
) -> CollectionStartResult:
    overrides = overrides or {}
    tasks: list[CollectionTaskRecord] = []
    for index, dataset in enumerate(CANONICAL_FULL_COLLECTION_DATASETS, start=1):
        values = overrides.get(dataset, {})
        task_status = str(values.get("status", "success"))
        succeeded = task_status in {"success", "partial"}
        failure = values.get("failure")
        tasks.append(
            CollectionTaskRecord(
                task_id=f"task-{index}-{dataset}",
                run_id=run_id,
                dataset=dataset,
                as_of=AS_OF,
                status=task_status,  # type: ignore[arg-type]
                source=str(values.get("source", "fixture" if succeeded else "none")),
                observations=int(values.get("observations", 3 if succeeded else 0)),
                warning=(
                    str(values["warning"])
                    if values.get("warning") is not None
                    else None
                ),
                failure=(
                    failure if isinstance(failure, StructuredTaskFailure) else None
                ),
                timings={"providerCollectionMs": float(index)},
                queued_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                duration_ms=float(index),
                settled=succeeded,
            )
        )
    return CollectionStartResult(
        run=CollectionRunRecord(
            run_id=run_id,
            as_of=AS_OF,
            status=parent_status,  # type: ignore[arg-type]
            requested_datasets=CANONICAL_FULL_COLLECTION_DATASETS,
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW if parent_status in {"success", "partial", "failed"} else None,
        ),
        tasks=tuple(tasks),
    )


class _ScenarioCommands:
    def __init__(self, result: CollectionStartResult) -> None:
        self.result = result
        self.execute_calls = 0
        self.wait_calls: list[tuple[str, float]] = []

    def execute(self, _key):
        self.execute_calls += 1
        return SimpleNamespace(run_id=self.result.run.run_id)

    def wait(self, run_id: str, timeout_seconds: float):
        self.wait_calls.append((run_id, timeout_seconds))
        return self.result


class _ScenarioQueries:
    def __init__(self, result: CollectionStartResult) -> None:
        self.result = result
        self.status_reads: list[date] = []
        self.run_reads: list[str] = []

    def collection_status(self, as_of: date):
        self.status_reads.append(as_of)
        return {
            "asOf": as_of,
            "datasets": [
                {"dataset": dataset, "coreIndices": [], "detail": None}
                for dataset in CANONICAL_FULL_COLLECTION_DATASETS
            ],
        }

    def get_run(self, run_id: str):
        self.run_reads.append(run_id)
        return self.result if run_id == self.result.run.run_id else None


def _client(result: CollectionStartResult) -> tuple[TestClient, _ScenarioCommands, _ScenarioQueries]:
    commands = _ScenarioCommands(result)
    queries = _ScenarioQueries(result)
    client = TestClient(
        build_test_app(
            collection_queries=queries,
            full_collection_commands=commands,
            automation_write_enabled=True,
            effective_date=AS_OF,
        )
    )
    return client, commands, queries


def _post(result: CollectionStartResult):
    client, commands, queries = _client(result)
    return client.post(ENDPOINT, headers=HEADERS), commands, queries


def test_full_endpoint_returns_all_success_in_canonical_order() -> None:
    response, commands, queries = _post(_result("success"))

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert [task["dataset"] for task in response.json()["tasks"]] == list(
        CANONICAL_FULL_COLLECTION_DATASETS
    )
    assert {task["status"] for task in response.json()["tasks"]} == {"success"}
    assert all(task["failure"] is None for task in response.json()["tasks"])
    assert commands.execute_calls == 1
    assert commands.wait_calls == [(RUN_ID, 900.0)]
    assert queries.status_reads == [AS_OF]


def test_full_endpoint_preserves_mixed_partial_and_failed_task_results() -> None:
    response, _, _ = _post(
        _result(
            "partial",
            {
                "breadth": {
                    "status": "partial",
                    "warning": "accepted partial breadth evidence",
                    "observations": 2,
                },
                "limits": {
                    "status": "failed-missing",
                    "warning": "limits provider disconnected",
                    "failure": _failure(
                        CollectionFailureCategory.NETWORK,
                        "limits provider disconnected",
                    ),
                },
            },
        )
    )

    tasks = {task["dataset"]: task for task in response.json()["tasks"]}
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert tasks["core"]["status"] == "success"
    assert tasks["breadth"]["status"] == "partial"
    assert tasks["breadth"]["failure"] is None
    assert tasks["limits"]["status"] == "failed-missing"
    assert tasks["limits"]["failure"] == {
        "category": "network",
        "message": "limits provider disconnected",
        "retryable": True,
        "retained": False,
        "source": "fixture-provider",
        "stage": "acquisition",
        "code": None,
        "blockedBy": [],
    }


def test_full_endpoint_returns_all_failed_business_result_as_http_200() -> None:
    failed = {
        dataset: {
            "status": "failed-missing",
            "failure": _failure(
                CollectionFailureCategory.NETWORK,
                f"{dataset} provider unavailable",
            ),
        }
        for dataset in CANONICAL_FULL_COLLECTION_DATASETS
    }

    response, _, _ = _post(_result("failed", failed))

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert len(response.json()["tasks"]) == 7
    assert {task["status"] for task in response.json()["tasks"]} == {
        "failed-missing"
    }
    assert all(task["failure"] is not None for task in response.json()["tasks"])


def test_full_endpoint_reports_ths_dependency_blocking_without_stopping_siblings() -> None:
    response, _, _ = _post(
        _result(
            "partial",
            {
                "industry-ranking": {
                    "status": "failed-missing",
                    "warning": "same-date THS catalog evidence is insufficient",
                    "failure": _failure(
                        CollectionFailureCategory.INSUFFICIENT,
                        "same-date THS catalog evidence is insufficient",
                    ),
                },
                "sector-turnover": {
                    "status": "blocked",
                    "failure": _failure(
                        CollectionFailureCategory.DEPENDENCY,
                        "blocked by industry-ranking",
                        stage="dependency-coordination",
                        blocked_by=("industry-ranking",),
                    ),
                },
                "sector-breadth": {
                    "status": "blocked",
                    "failure": _failure(
                        CollectionFailureCategory.DEPENDENCY,
                        "blocked by sector-turnover",
                        stage="dependency-coordination",
                        blocked_by=("industry-ranking", "sector-turnover"),
                    ),
                },
            },
        )
    )

    tasks = {task["dataset"]: task for task in response.json()["tasks"]}
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert tasks["core"]["status"] == "success"
    assert tasks["activeDirection"]["status"] == "success"
    assert tasks["sector-turnover"]["status"] == "blocked"
    assert tasks["sector-turnover"]["failure"]["category"] == "dependency"
    assert tasks["sector-turnover"]["failure"]["blockedBy"] == [
        "industry-ranking"
    ]
    assert tasks["sector-breadth"]["failure"]["blockedBy"] == [
        "industry-ranking",
        "sector-turnover",
    ]


def test_full_endpoint_reports_dataset_date_lease_contention_as_busy() -> None:
    response, _, _ = _post(
        _result(
            "partial",
            {
                "breadth": {
                    "status": "busy",
                    "failure": _failure(
                        CollectionFailureCategory.CONCURRENCY,
                        "another task owns the dataset/date lease",
                        stage="lease-acquisition",
                    ),
                }
            },
        )
    )

    breadth = next(
        task for task in response.json()["tasks"] if task["dataset"] == "breadth"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert breadth["status"] == "busy"
    assert breadth["failure"]["category"] == "concurrency"
    assert breadth["failure"]["retryable"] is True


@pytest.mark.parametrize(
    ("task_status", "retained"),
    (("failed-retained", True), ("failed-missing", False)),
)
def test_full_endpoint_keeps_failed_retention_semantics(
    task_status: str,
    retained: bool,
) -> None:
    response, _, _ = _post(
        _result(
            "partial",
            {
                "limits": {
                    "status": task_status,
                    "failure": _failure(
                        CollectionFailureCategory.RATE_LIMIT,
                        "provider rate limited the request",
                        retained=retained,
                    ),
                }
            },
        )
    )

    limits = next(
        task for task in response.json()["tasks"] if task["dataset"] == "limits"
    )
    assert response.status_code == 200
    assert limits["status"] == task_status
    assert limits["failure"]["retained"] is retained
    assert limits["failure"]["category"] == "rate-limit"


class _IoBomb:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *_args, **_kwargs):
        self.calls.append("unit-of-work")
        raise AssertionError("weekend/pre-settlement path performed persistence I/O")

    def __getattr__(self, name: str):
        def fail(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(
                f"weekend/pre-settlement path performed unexpected I/O: {name}"
            )

        return fail


def _boundary_client(now: datetime) -> tuple[TestClient, _IoBomb]:
    io_bomb = _IoBomb()
    command = FullCollectionCommand(
        unit_of_work_factory=io_bomb,
        submission_service=io_bomb,  # type: ignore[arg-type]
        queries=io_bomb,  # type: ignore[arg-type]
        clock=lambda: now,
        settlement_boundary=time(15, 10),
    )
    client = TestClient(
        build_test_app(
            collection_queries=io_bomb,
            full_collection_commands=command,
            automation_write_enabled=True,
            effective_date=now.date(),
        )
    )
    return client, io_bomb


def test_full_endpoint_weekend_skip_performs_zero_persistence_or_provider_io() -> None:
    client, io_bomb = _boundary_client(
        datetime(2026, 10, 17, 16, 30, tzinfo=MARKET_TIME_ZONE)
    )

    response = client.post(ENDPOINT, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["outcome"] == "skipped"
    assert response.json()["targetDate"] == "2026-10-17"
    assert response.json()["runId"] is None
    assert response.json()["tasks"] == []
    assert io_bomb.calls == []


def test_full_endpoint_pre_settlement_rejects_before_any_io() -> None:
    client, io_bomb = _boundary_client(
        datetime(2026, 10, 15, 15, 9, 59, tzinfo=MARKET_TIME_ZONE)
    )

    response = client.post(ENDPOINT, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "before-settlement"
    assert response.json()["detail"]["targetDate"] == AS_OF.isoformat()
    assert io_bomb.calls == []


class _DisconnectCommands:
    def __init__(self, terminal: CollectionStartResult) -> None:
        self.terminal = terminal
        self.execute_calls = 0
        self.wait_calls = 0
        self.worker_starts = 0
        self.provider_calls = 0
        self.wait_started = Event()
        self.worker_started = Event()
        self.release_worker = Event()
        self.worker_finished = Event()
        self.worker: Thread | None = None

    def execute(self, _key):
        self.execute_calls += 1

        def collect_independently() -> None:
            self.worker_starts += 1
            self.provider_calls += 1
            self.worker_started.set()
            self.release_worker.wait(timeout=5)
            self.worker_finished.set()

        self.worker = Thread(target=collect_independently, daemon=True)
        self.worker.start()
        return SimpleNamespace(run_id=self.terminal.run.run_id)

    def wait(self, _run_id: str, _timeout_seconds: float):
        self.wait_calls += 1
        self.wait_started.set()
        if not self.worker_finished.wait(timeout=5):
            raise AssertionError("independent collection worker did not finish")
        return self.terminal


def test_client_disconnect_after_submission_does_not_cancel_or_replace_run() -> None:
    terminal = _result("success", run_id="run-survives-disconnect")
    commands = _DisconnectCommands(terminal)
    queries = _ScenarioQueries(terminal)
    app = build_test_app(
        collection_queries=queries,
        full_collection_commands=commands,
        automation_write_enabled=True,
        effective_date=AS_OF,
    )

    async def disconnect_client() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            request = asyncio.create_task(client.post(ENDPOINT, headers=HEADERS))
            assert await asyncio.to_thread(commands.wait_started.wait, 2)
            assert commands.worker_started.is_set()
            request.cancel()
            commands.release_worker.set()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(request, timeout=2)
            assert await asyncio.to_thread(commands.worker_finished.wait, 2)

    asyncio.run(disconnect_client())
    if commands.worker is not None:
        commands.worker.join(timeout=2)

    assert commands.execute_calls == 1
    assert commands.wait_calls == 1
    assert commands.worker_starts == 1
    assert commands.provider_calls == 1
    assert commands.worker_finished.is_set()


class _ProviderBomb:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def fail(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(f"provider call during persisted status read: {name}")

        return fail


class _PersistedCommands:
    def __init__(self, queries: CollectionCoordinator) -> None:
        self.queries = queries
        self.execute_calls = 0
        self.wait_calls: list[tuple[str, float]] = []

    def execute(self, _key):
        self.execute_calls += 1
        return SimpleNamespace(run_id=RUN_ID)

    def wait(self, run_id: str, timeout_seconds: float):
        self.wait_calls.append((run_id, timeout_seconds))
        return self.queries.get_run(run_id)


def test_wait_timeout_then_terminal_get_reads_only_persisted_state(tmp_path) -> None:
    database_path = tmp_path / "full-endpoint-timeout.sqlite3"
    store = SnapshotStore(database_path)
    store.create_collection_run(
        RUN_ID,
        AS_OF,
        CANONICAL_FULL_COLLECTION_DATASETS,
        created_at=NOW,
    )
    store.update_collection_run(RUN_ID, "collecting", started_at=NOW)
    leases = {}
    for dataset in CANONICAL_FULL_COLLECTION_DATASETS:
        task_id = f"task-{dataset}"
        store.create_collection_task(task_id, RUN_ID, dataset, AS_OF, queued_at=NOW)
        leases[dataset] = store.acquire_lease(
            dataset,
            AS_OF,
            task_id,
            lease_seconds=1800,
            now=NOW.astimezone(timezone.utc),
        )

    provider = _ProviderBomb()
    coordinator = CollectionCoordinator(provider, store, now=lambda: NOW)
    commands = _PersistedCommands(coordinator)
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            full_collection_commands=commands,
            automation_write_enabled=True,
            effective_date=AS_OF,
        )
    )

    accepted = client.post(
        ENDPOINT,
        headers=HEADERS,
        params={"waitTimeoutSeconds": 0},
    )

    assert accepted.status_code == 202
    assert accepted.headers["location"] == accepted.json()["statusUrl"]
    assert accepted.json()["runId"] == RUN_ID
    assert accepted.json()["status"] == "collecting"
    assert commands.execute_calls == 1
    assert commands.wait_calls == [(RUN_ID, 0.0)]

    for dataset in CANONICAL_FULL_COLLECTION_DATASETS:
        task_id = f"task-{dataset}"
        store.transition_collection_task(
            task_id,
            "success",
            source="fixture",
            observations=3,
            completed_at=NOW,
            duration_ms=1.0,
            settled=True,
        )
        assert store.release_lease(dataset, AS_OF, lease=leases[dataset])
    store.update_collection_run(RUN_ID, "success", completed_at=NOW)

    restarted_provider = _ProviderBomb()
    restarted = CollectionCoordinator(restarted_provider, SnapshotStore(database_path), now=lambda: NOW)
    read_client = TestClient(
        build_test_app(collection_queries=restarted, effective_date=AS_OF)
    )
    terminal = read_client.get(accepted.json()["statusUrl"])

    assert terminal.status_code == 200
    assert terminal.json()["runId"] == RUN_ID
    assert terminal.json()["status"] == "success"
    assert len(terminal.json()["tasks"]) == 7
    assert {task["status"] for task in terminal.json()["tasks"]} == {"success"}
    assert provider.calls == []
    assert restarted_provider.calls == []
