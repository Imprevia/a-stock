from datetime import date

from fastapi.testclient import TestClient

from src.market_environment import api
from src.market_environment.service import MarketEnvironmentService


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
