from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from src.market_environment import api
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.service import MarketEnvironmentService
from src.market_environment.snapshot_store import SnapshotStore
from tests.test_market_environment_collection import AS_OF, CollectionProvider


class StubService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    def get(self, as_of: date):
        self.calls.append(("aggregate", None))
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
        }

    def get_core(self, as_of: date):
        self.calls.append(("core", None))
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
        }

    def get_chapter01(self, as_of: date, section: str):
        self.calls.append(("chapter01", section))
        if self.error:
            raise self.error
        builder = MarketEnvironmentService(provider=object())
        core = {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
            "requestedAsOf": as_of,
            "effectiveDate": as_of,
        }
        provider_data = builder._missing_chapter_provider_data(as_of, "fixture", status="missing")
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": core["generatedAt"],
            "chapter01": builder._build_chapter01(core, provider_data),
        }


def test_api_rejects_invalid_and_future_dates() -> None:
    client = TestClient(api.app)
    assert client.get("/api/market-environment?as_of=not-a-date").status_code == 422
    future = date.today().replace(year=date.today().year + 1).isoformat()
    assert client.get(f"/api/market-environment?as_of={future}").status_code == 422


def test_api_returns_503_for_provider_failure(monkeypatch) -> None:
    monkeypatch.setattr(api, "service", StubService(RuntimeError("全部指数数据源不可用")))
    response = TestClient(api.app).get("/api/market-environment?as_of=2026-08-28")
    assert response.status_code == 503
    assert "全部指数数据源不可用" in response.json()["detail"]


def test_api_returns_schema_payload(monkeypatch) -> None:
    monkeypatch.setattr(api, "service", StubService())
    response = TestClient(api.app).get("/api/market-environment?as_of=2026-08-28")
    assert response.status_code == 200
    assert response.json()["asOf"] == "2026-08-28"


def test_api_exposes_core_and_section_endpoints(monkeypatch) -> None:
    service = StubService()
    monkeypatch.setattr(api, "service", service)
    client = TestClient(api.app)

    core = client.get("/api/market-environment/core?as_of=2026-08-28")
    chapter = client.get("/api/market-environment/chapter-01?as_of=2026-08-28&section=breadth")

    assert core.status_code == 200
    assert chapter.status_code == 200
    assert chapter.json()["chapter01"]["breadth"]["quality"]["status"] == "missing"
    assert service.calls == [("core", None), ("chapter01", "breadth")]


def test_api_rejects_unknown_chapter_section(monkeypatch) -> None:
    service = StubService()
    monkeypatch.setattr(api, "service", service)

    response = TestClient(api.app).get(
        "/api/market-environment/chapter-01?as_of=2026-08-28&section=unknown"
    )

    assert response.status_code == 422
    assert service.calls == []


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class NoopExecutor:
    def submit(self, function, *args):
        return None


def collection_coordinator(tmp_path, provider=None) -> CollectionCoordinator:
    market_now = datetime.combine(AS_OF, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    return CollectionCoordinator(
        provider or CollectionProvider(),
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: market_now,
    )


def test_collection_post_can_be_explicitly_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "0")
    monkeypatch.setattr(api, "collection_coordinator", collection_coordinator(tmp_path))

    response = TestClient(api.app).post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )

    assert response.status_code == 403


def test_collection_status_is_provider_free_and_reports_exact_date(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", raising=False)
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    coordinator.collect(AS_OF, ["breadth"])
    provider.calls.clear()
    monkeypatch.setattr(api, "collection_coordinator", coordinator)

    response = TestClient(api.app).get(
        f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
    )

    assert response.status_code == 200
    assert response.json()["manualRefreshEnabled"] is True
    assert provider.calls == []
    rows = {item["dataset"]: item for item in response.json()["datasets"]}
    assert rows["breadth"]["available"] is True
    assert rows["core"]["available"] is False


def test_collection_single_run_is_enabled_by_default_and_can_be_polled(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", raising=False)
    coordinator = collection_coordinator(tmp_path)
    monkeypatch.setattr(api, "collection_coordinator", coordinator)
    monkeypatch.setattr(api, "collection_executor", ImmediateExecutor())
    client = TestClient(api.app)

    started = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat(), "datasets": ["breadth"]},
    )
    polled = client.get(
        f"/api/market-environment/collection-runs/{started.json()['runId']}"
    )

    assert started.status_code == 202
    assert started.json()["requestedDatasets"] == ["breadth"]
    assert polled.status_code == 200
    assert polled.json()["status"] == "success"
    assert polled.json()["completedTasks"] == 1


def test_collection_full_run_reports_partial_and_keeps_successes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "true")
    coordinator = collection_coordinator(
        tmp_path,
        CollectionProvider(failing_datasets={"sectors"}),
    )
    monkeypatch.setattr(api, "collection_coordinator", coordinator)
    monkeypatch.setattr(api, "collection_executor", ImmediateExecutor())
    client = TestClient(api.app)

    started = client.post(
        "/api/market-environment/collection-runs",
        json={"asOf": AS_OF.isoformat()},
    )
    polled = client.get(
        f"/api/market-environment/collection-runs/{started.json()['runId']}"
    )

    tasks = {item["dataset"]: item for item in polled.json()["tasks"]}
    assert polled.json()["status"] == "partial"
    assert tasks["sectors"]["status"] == "failed-missing"
    assert tasks["breadth"]["status"] == "success"


def test_collection_duplicate_post_reports_busy_without_provider_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    provider = CollectionProvider()
    coordinator = collection_coordinator(tmp_path, provider)
    monkeypatch.setattr(api, "collection_coordinator", coordinator)
    monkeypatch.setattr(api, "collection_executor", NoopExecutor())
    client = TestClient(api.app)
    request = {"asOf": AS_OF.isoformat(), "datasets": ["breadth"]}

    first = client.post("/api/market-environment/collection-runs", json=request)
    second = client.post("/api/market-environment/collection-runs", json=request)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["tasks"][0]["status"] == "busy"
    assert provider.calls == []


def test_collection_rejects_historical_latest_only_dataset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1")
    monkeypatch.setattr(api, "collection_coordinator", collection_coordinator(tmp_path))

    response = TestClient(api.app).post(
        "/api/market-environment/collection-runs",
        json={
            "asOf": (AS_OF - timedelta(days=1)).isoformat(),
            "datasets": ["breadth"],
        },
    )

    assert response.status_code == 422
    assert "latest-only" in response.json()["detail"]


def test_collection_poll_recovers_task_after_expired_lease(monkeypatch, tmp_path) -> None:
    coordinator = collection_coordinator(tmp_path)
    started = coordinator.start_run(AS_OF, ["breadth"])
    task = started.tasks[0]
    coordinator.store.release_lease("breadth", AS_OF, task.task_id)
    monkeypatch.setattr(api, "collection_coordinator", coordinator)

    response = TestClient(api.app).get(
        f"/api/market-environment/collection-runs/{started.run.run_id}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["tasks"][0]["status"] == "failed-missing"
