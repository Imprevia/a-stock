"""Focused contracts for collection response mapping."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import (
    CollectionFailureCategory,
    StructuredTaskFailure,
)
from src.market_environment.interfaces.http.schemas import (
    map_collection_failure,
    map_collection_run,
    map_full_collection_run,
    map_full_collection_skipped,
)
from src.market_environment.interfaces.http.schemas.models import (
    FullCollectionResponse,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotStore
from tests.market_environment_api_support import FakeCollectionCommands, build_test_app
from tests.test_market_environment_collection import AS_OF, CollectionProvider


class _NoopExecutor:
    def submit(self, function, *args):
        del function, args
        return None


def _task_payload(*, status: str, failure=None) -> dict:
    return {
        "taskId": f"task-{status}",
        "dataset": "breadth",
        "asOf": AS_OF,
        "status": status,
        "source": "fixture",
        "observations": 3,
        "warning": None,
        "failure": failure,
        "timings": {"providerCollectionMs": 1.25},
        "queuedAt": None,
        "startedAt": None,
        "completedAt": None,
        "durationMs": 1.25,
        "settled": True,
    }


def _run_payload(*tasks: dict) -> dict:
    now = datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE)
    return {
        "runId": "run-fixture",
        "asOf": AS_OF,
        "status": "partial",
        "requestedDatasets": ["breadth"],
        "completedTasks": len(tasks),
        "totalTasks": len(tasks),
        "createdAt": now,
        "startedAt": now,
        "completedAt": now,
        "tasks": list(tasks),
    }


def test_collection_failure_mapper_exposes_every_persisted_safe_field() -> None:
    failure = StructuredTaskFailure(
        category=CollectionFailureCategory.DEPENDENCY,
        message="upstream catalog unavailable",
        retryable=True,
        retained=False,
        source="fuyao-ths",
        stage="dependency-validation",
        code="THS_DEPENDENCY_INSUFFICIENT",
        blocked_by=("industry-ranking",),
    )

    assert map_collection_failure(failure) == {
        "category": "dependency",
        "message": "upstream catalog unavailable",
        "retryable": True,
        "retained": False,
        "source": "fuyao-ths",
        "stage": "dependency-validation",
        "code": "THS_DEPENDENCY_INSUFFICIENT",
        "blockedBy": ["industry-ranking"],
    }


def test_collection_run_success_and_partial_keep_nullable_failure_compatible() -> None:
    payload = _run_payload(
        _task_payload(status="success"),
        _task_payload(status="partial"),
    )

    result = map_collection_run(payload)

    assert [task["failure"] for task in result["tasks"]] == [None, None]


def test_full_collection_envelopes_extend_without_changing_shared_run_fields() -> None:
    payload = _run_payload(_task_payload(status="partial"))

    run = map_full_collection_run(
        payload,
        status_url="/api/market-environment/collection-runs/run-fixture",
    )
    skipped = map_full_collection_skipped(
        target_date=AS_OF,
        reason="Shanghai market date falls on a weekend",
    )

    assert {key: run[key] for key in payload} == map_collection_run(payload)
    assert run["outcome"] == "run"
    assert run["targetDate"] == AS_OF
    assert run["statusUrl"].endswith("/run-fixture")
    assert skipped == {
        "outcome": "skipped",
        "targetDate": AS_OF,
        "status": "skipped",
        "reason": "Shanghai market date falls on a weekend",
        "runId": None,
        "statusUrl": None,
        "tasks": [],
    }
    assert TypeAdapter(FullCollectionResponse).json_schema()["discriminator"] == {
        "mapping": {
            "run": "#/$defs/FullCollectionRunResponse",
            "skipped": "#/$defs/FullCollectionSkippedResponse",
        },
        "propertyName": "outcome",
    }


def test_manual_async_get_and_exact_date_status_share_persisted_failure_after_restart(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    database_path = tmp_path / "collection-response.sqlite3"
    current = [datetime(2026, 9, 3, 16, tzinfo=MARKET_TIME_ZONE)]
    coordinator = CollectionCoordinator(
        CollectionProvider(),
        SnapshotStore(database_path),
        now=lambda: current[0],
    )
    client = TestClient(
        build_test_app(
            collection_queries=coordinator,
            collection_commands=FakeCollectionCommands(coordinator, _NoopExecutor()),
            effective_date=AS_OF,
        )
    )

    queued = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )
    assert queued.status_code == 202
    assert queued.json()["tasks"][0]["failure"] is None

    current[0] += timedelta(minutes=1)
    busy = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )
    assert busy.status_code == 202
    persisted_failure = busy.json()["tasks"][0]["failure"]
    assert persisted_failure == {
        "category": "concurrency",
        "message": "another active task already holds the dataset/date lease",
        "retryable": True,
        "retained": False,
        "source": None,
        "stage": "lease-acquisition",
        "code": None,
        "blockedBy": [],
    }

    restarted_provider = CollectionProvider()
    restarted = CollectionCoordinator(
        restarted_provider,
        SnapshotStore(database_path),
        now=lambda: current[0],
    )
    restarted_client = TestClient(
        build_test_app(
            collection_queries=restarted,
            effective_date=AS_OF,
        )
    )
    run = restarted_client.get(
        f"/api/market-environment/collection-runs/{busy.json()['runId']}"
    )
    status = restarted_client.get(
        "/api/market-environment/data-collection",
        params={"as_of": AS_OF.isoformat()},
    )

    breadth = next(
        item for item in status.json()["datasets"] if item["dataset"] == "breadth"
    )
    assert run.status_code == 200
    assert status.status_code == 200
    assert run.json()["tasks"][0]["failure"] == persisted_failure
    assert breadth["latestAttempt"]["failure"] == persisted_failure
    assert restarted_provider.calls == []
