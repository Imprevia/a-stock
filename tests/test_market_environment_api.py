from datetime import date

from fastapi.testclient import TestClient

from src.market_environment import api


class StubService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def get(self, as_of: date):
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:00+08:00",
            "indices": [],
            "summary": {"synchronization": "无可用数据", "dominantTrend": "数据不足", "warnings": []},
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
