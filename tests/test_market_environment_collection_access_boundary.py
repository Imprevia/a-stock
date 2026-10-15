"""Access-boundary regression tests for the full-collection endpoint."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.market_environment.collection import CollectionStartResult
from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    CollectionFailureCategory,
    StructuredTaskFailure,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
)
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 16, 30, tzinfo=MARKET_TIME_ZONE)
FULL_ROUTE = "/api/market-environment/collection-runs/full"
MANUAL_ROUTE = "/api/market-environment/collection-runs"


def _terminal_result(*, busy: bool = False) -> CollectionStartResult:
    tasks = []
    for index, dataset in enumerate(CANONICAL_FULL_COLLECTION_DATASETS, start=1):
        is_busy = busy and index == 1
        tasks.append(
            CollectionTaskRecord(
                task_id=f"task-{index}",
                run_id="run-access-boundary",
                dataset=dataset,
                as_of=AS_OF,
                status="busy" if is_busy else "success",
                source="none" if is_busy else "fixture",
                observations=0 if is_busy else 3,
                warning="同日期数据集租约已由另一任务持有" if is_busy else None,
                failure=(
                    StructuredTaskFailure(
                        category=CollectionFailureCategory.CONCURRENCY,
                        message="同日期数据集租约已由另一任务持有",
                        retryable=True,
                        retained=False,
                        stage="lease",
                    )
                    if is_busy
                    else None
                ),
                timings={},
                queued_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                duration_ms=1.0,
                settled=True,
            )
        )
    return CollectionStartResult(
        run=CollectionRunRecord(
            run_id="run-access-boundary",
            as_of=AS_OF,
            status="partial" if busy else "success",
            requested_datasets=CANONICAL_FULL_COLLECTION_DATASETS,
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
        ),
        tasks=tuple(tasks),
    )


class _FullCommands:
    def __init__(self, result: CollectionStartResult) -> None:
        self.result = result
        self.execute_calls: list[object] = []
        self.wait_calls: list[tuple[str, float]] = []

    def execute(self, key):
        self.execute_calls.append(key)
        return SimpleNamespace(run_id=self.result.run.run_id)

    def wait(self, run_id: str, timeout_seconds: float):
        self.wait_calls.append((run_id, timeout_seconds))
        return self.result


class _ManualCommands:
    def __init__(self) -> None:
        self.start_calls: list[tuple[date, object]] = []
        self.submit_calls: list[str] = []

    def start_run(self, as_of: date, datasets=None):
        self.start_calls.append((as_of, datasets))
        raise AssertionError("disabled manual collection must not create a run")

    def submit_run(self, run_id: str):
        self.submit_calls.append(run_id)
        raise AssertionError("disabled manual collection must not submit work")


class _CollectionQueries:
    def __init__(self) -> None:
        self.status_calls = 0

    def collection_status(self, as_of: date):
        assert as_of == AS_OF
        self.status_calls += 1
        return {
            "asOf": as_of,
            "datasets": [
                {"dataset": dataset, "coreIndices": [], "detail": None}
                for dataset in CANONICAL_FULL_COLLECTION_DATASETS
            ],
        }


class _DisabledGateWorkProbe:
    """Count every work layer that would become reachable after the gate."""

    def __init__(self) -> None:
        self.command_calls = 0
        self.run_creation_calls = 0
        self.provider_calls = 0
        self.wait_calls = 0

    def execute(self, key):
        self.command_calls += 1
        self.run_creation_calls += 1
        self.provider_calls += 1
        raise AssertionError("disabled automation gate must stop before command work")

    def wait(self, run_id: str, timeout_seconds: float):
        self.wait_calls += 1
        raise AssertionError("disabled automation gate must not wait on a run")


def _client(
    *,
    full_commands,
    queries: _CollectionQueries,
    automation_enabled: bool,
    manual_commands=None,
) -> TestClient:
    return TestClient(
        build_test_app(
            collection_queries=queries,
            collection_commands=manual_commands,
            full_collection_commands=full_commands,
            automation_write_enabled=automation_enabled,
            effective_date=AS_OF,
        )
    )


def test_automation_can_be_enabled_while_manual_collection_stays_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "0")
    full_commands = _FullCommands(_terminal_result())
    manual_commands = _ManualCommands()
    queries = _CollectionQueries()
    client = _client(
        full_commands=full_commands,
        queries=queries,
        automation_enabled=True,
        manual_commands=manual_commands,
    )

    # No Origin or Authorization header is required: network reachability plus
    # the enabled server-side gate is the accepted boundary.
    full_response = client.post(
        FULL_ROUTE,
        headers={"Idempotency-Key": "arbitrary-routed-client-key"},
        params={"waitTimeoutSeconds": 0},
    )
    manual_response = client.post(
        MANUAL_ROUTE,
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )

    assert full_response.status_code == 200
    assert full_response.json()["runId"] == "run-access-boundary"
    assert "www-authenticate" not in full_response.headers
    assert manual_response.status_code == 403
    assert manual_response.json() == {"detail": "手工数据采集未启用"}
    assert "www-authenticate" not in manual_response.headers
    assert len(full_commands.execute_calls) == 1
    assert full_commands.wait_calls == [("run-access-boundary", 0.0)]
    assert manual_commands.start_calls == []
    assert manual_commands.submit_calls == []


def test_disabled_automation_gate_performs_no_command_run_or_provider_work() -> None:
    work = _DisabledGateWorkProbe()
    queries = _CollectionQueries()
    response = _client(
        full_commands=work,
        queries=queries,
        automation_enabled=False,
    ).post(
        FULL_ROUTE,
        headers={"Idempotency-Key": "disabled-gate-probe"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "自动化全量数据采集未启用"}
    assert "www-authenticate" not in response.headers
    assert work.command_calls == 0
    assert work.run_creation_calls == 0
    assert work.provider_calls == 0
    assert work.wait_calls == 0
    assert queries.status_calls == 0


def test_openapi_and_busy_response_do_not_present_reliability_as_authentication() -> None:
    commands = _FullCommands(_terminal_result(busy=True))
    queries = _CollectionQueries()
    client = _client(
        full_commands=commands,
        queries=queries,
        automation_enabled=True,
    )
    schema = client.app.openapi()
    operation = schema["paths"][FULL_ROUTE]["post"]
    header = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    )

    assert "security" not in operation
    assert "securitySchemes" not in schema.get("components", {})
    assert header["name"] == "Idempotency-Key"
    assert "可靠性键" in header["description"]
    assert "不是身份凭据" in header["description"]

    response = client.post(
        FULL_ROUTE,
        headers={"Idempotency-Key": "lease-is-not-authentication"},
        params={"waitTimeoutSeconds": 0},
    )

    assert response.status_code == 200
    assert "www-authenticate" not in response.headers
    busy_task = next(task for task in response.json()["tasks"] if task["status"] == "busy")
    assert busy_task["failure"]["category"] == "concurrency"
    assert busy_task["failure"]["stage"] == "lease"


def test_canonical_docs_explicitly_disclose_that_reliability_is_not_authentication() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    required_disclosures = {
        "docs/architecture.md": (
            "当前没有应用身份认证、TLS 或请求级授权",
            "idempotency、CORS、UI 隐藏和 dataset lease 都不是鉴权",
        ),
        "docs/product-specs/market-environment-dashboard.md": (
            "NodePort、CORS、幂等 key、前端按钮和 lease 都不提供身份认证或客户端授权",
        ),
        "docs/repository-guide.md": (
            "Idempotency-Key、CORS、UI 和 lease 是可靠性机制，不是鉴权",
        ),
        "docs/runbooks.md": (
            "该内网接口不鉴权",
            "幂等、CORS、前端按钮和 lease 都不是访问控制",
        ),
    }

    for relative_path, expected_phrases in required_disclosures.items():
        normalized = "".join((repo_root / relative_path).read_text().split()).replace(
            "`", ""
        )
        for phrase in expected_phrases:
            compact_phrase = "".join(phrase.split())
            assert compact_phrase in normalized, (
                f"{relative_path} 缺少安全边界声明: {phrase}"
            )
