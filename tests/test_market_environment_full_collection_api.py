"""HTTP contract tests for the sync-first full-collection trigger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.market_environment.application.commands import FullCollectionSkippedResult
from src.market_environment.collection import CollectionStartResult
from src.market_environment.domain.models import CANONICAL_FULL_COLLECTION_DATASETS
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
)
from tests.market_environment_api_support import build_test_app
from tests.test_market_environment_collection import AS_OF


NOW = datetime(2026, 9, 3, 16, 30, tzinfo=MARKET_TIME_ZONE)


def _result(status: str) -> CollectionStartResult:
    terminal = status in {"success", "partial", "failed"}
    tasks = tuple(
        CollectionTaskRecord(
            task_id=f"task-{index}",
            run_id="run-full",
            dataset=dataset,
            as_of=AS_OF,
            status="success" if terminal else "queued",
            source="fixture" if terminal else "none",
            observations=3 if terminal else 0,
            timings={},
            queued_at=NOW,
            started_at=NOW if terminal else None,
            completed_at=NOW if terminal else None,
            duration_ms=1.0 if terminal else None,
            settled=terminal,
        )
        for index, dataset in enumerate(CANONICAL_FULL_COLLECTION_DATASETS, start=1)
    )
    return CollectionStartResult(
        run=CollectionRunRecord(
            run_id="run-full",
            as_of=AS_OF,
            status=status,
            requested_datasets=CANONICAL_FULL_COLLECTION_DATASETS,
            created_at=NOW,
            started_at=NOW if status != "queued" else None,
            completed_at=NOW if terminal else None,
        ),
        tasks=tasks,
    )


@dataclass
class _FullCommands:
    result: CollectionStartResult | None = None
    skipped: bool = False

    def __post_init__(self) -> None:
        self.execute_calls: list[object] = []
        self.wait_calls: list[tuple[str, float]] = []

    def execute(self, key):
        self.execute_calls.append(key)
        if self.skipped:
            return FullCollectionSkippedResult(resolved_as_of=AS_OF)
        return SimpleNamespace(run_id="run-full")

    def wait(self, run_id: str, timeout_seconds: float):
        self.wait_calls.append((run_id, timeout_seconds))
        return self.result


class _Queries:
    def __init__(self) -> None:
        self.status_calls = 0

    def collection_status(self, as_of):
        assert as_of == AS_OF
        self.status_calls += 1
        return {
            "asOf": as_of,
            "datasets": [
                {
                    "dataset": dataset,
                    "coreIndices": [],
                    "detail": None,
                }
                for dataset in CANONICAL_FULL_COLLECTION_DATASETS
            ],
        }


def _client(commands: _FullCommands, queries: _Queries, *, enabled: bool = True):
    return TestClient(
        build_test_app(
            collection_queries=queries,
            full_collection_commands=commands,
            automation_write_enabled=enabled,
            effective_date=AS_OF,
        )
    )


def test_full_collection_terminal_response_is_http_200_with_seven_tasks() -> None:
    commands = _FullCommands(_result("success"))
    queries = _Queries()

    response = _client(commands, queries).post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "hermes-market-collection-2026-09-03-1630"},
        params={"waitTimeoutSeconds": 12},
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "run"
    assert response.json()["targetDate"] == AS_OF.isoformat()
    assert response.json()["runId"] == "run-full"
    assert response.json()["status"] == "success"
    assert len(response.json()["tasks"]) == 7
    assert commands.wait_calls == [("run-full", 12.0)]
    assert queries.status_calls == 1


def test_full_collection_active_response_is_http_202_with_polling_headers() -> None:
    commands = _FullCommands(_result("collecting"))
    queries = _Queries()

    response = _client(commands, queries).post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "hermes-market-collection-2026-09-03-1630"},
        params={"waitTimeoutSeconds": 0},
    )

    assert response.status_code == 202
    assert response.headers["location"] == response.json()["statusUrl"]
    assert response.headers["retry-after"] == "15"
    assert response.json()["status"] == "collecting"
    assert commands.wait_calls == [("run-full", 0.0)]


def test_full_collection_weekend_skip_uses_no_run_status_read() -> None:
    commands = _FullCommands(skipped=True)
    queries = _Queries()

    response = _client(commands, queries).post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "hermes-market-collection-2026-09-05-1630"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "skipped",
        "targetDate": AS_OF.isoformat(),
        "status": "skipped",
        "reason": "weekend",
        "runId": None,
        "statusUrl": None,
        "tasks": [],
    }
    assert commands.wait_calls == []
    assert queries.status_calls == 0


def test_full_collection_gate_rejects_without_command_or_status_work() -> None:
    commands = _FullCommands(_result("success"))
    queries = _Queries()

    response = _client(commands, queries, enabled=False).post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "hermes-market-collection-2026-09-03-1630"},
    )

    assert response.status_code == 403
    assert commands.execute_calls == []
    assert commands.wait_calls == []
    assert queries.status_calls == 0


def test_full_collection_request_contract_bounds_wait_and_requires_key() -> None:
    commands = _FullCommands(_result("success"))
    queries = _Queries()
    client = _client(commands, queries)

    assert client.post(
        "/api/market-environment/collection-runs/full"
    ).status_code == 422
    assert client.post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "invalid key"},
    ).status_code == 422
    assert client.post(
        "/api/market-environment/collection-runs/full",
        headers={"Idempotency-Key": "valid-key"},
        params={"waitTimeoutSeconds": 901},
    ).status_code == 422
    assert commands.execute_calls == []


def test_full_collection_openapi_has_only_server_selected_collection_inputs() -> None:
    operation = _client(_FullCommands(), _Queries()).app.openapi()["paths"][
        "/api/market-environment/collection-runs/full"
    ]["post"]

    assert "requestBody" not in operation
    parameters = {
        (parameter["in"], parameter["name"]): parameter
        for parameter in operation["parameters"]
    }
    assert set(parameters) == {
        ("header", "Idempotency-Key"),
        ("query", "waitTimeoutSeconds"),
    }
    assert parameters[("header", "Idempotency-Key")]["required"] is True
    wait_schema = parameters[("query", "waitTimeoutSeconds")]["schema"]
    assert wait_schema["default"] == 900
    assert wait_schema["minimum"] == 0
    assert wait_schema["maximum"] == 900
    assert "security" not in operation
    assert set(operation["responses"]) >= {"200", "202", "422"}
