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

    def get_core(self, as_of: date):
        return self.get(as_of)

    def get_chapter01(self, as_of: date):
        if self.error:
            raise self.error
        return {
            "asOf": as_of.isoformat(),
            "generatedAt": "2026-08-29T15:05:01+08:00",
            "chapter01": {
                "status": "insufficient",
                "coverage": 0.0,
                "documents": [],
                "breadth": _missing_evidence("breadth"),
                "limits": {
                    "limitUpCount": None,
                    "limitDownCount": None,
                    "failedLimitUpCount": None,
                    "failedLimitUpRatio": None,
                    "maxStreak": None,
                    "state": "insufficient",
                    "quality": _quality("limits"),
                },
                "sectors": {"rows": [], "state": "insufficient", "quality": _quality("sectors")},
                "activeDirection": {
                    "state": "insufficient",
                    "summary": None,
                    "topStocks": [],
                    "quality": _quality("active-direction"),
                },
                "events": {"state": "unverified", "items": [], "quality": _quality("events")},
                "combinationOverview": {
                    "strength": "数据不足",
                    "stage": "数据不足",
                    "capitalAcceptance": "数据不足",
                    "tradingMode": "保持观察",
                    "confidence": "low",
                    "evidence": [],
                },
                "assessment": {
                    "state": "insufficient",
                    "confidence": "insufficient",
                    "evidence": [],
                    "risks": [],
                    "nextConfirmation": "等待数据",
                    "invalidation": "数据失效",
                },
            },
        }


def _quality(dataset: str) -> dict:
    return {
        "dataset": dataset,
        "source": "stub",
        "provider": "stub",
        "status": "missing",
        "observations": 0,
        "asOf": "2026-08-28",
        "warning": None,
        "warnings": [],
    }


def _missing_evidence(dataset: str) -> dict:
    return {
        "advanceCount": None,
        "declineCount": None,
        "flatCount": None,
        "validCount": None,
        "advanceRatio": None,
        "medianReturn": None,
        "state": "insufficient",
        "quality": _quality(dataset),
    }


def test_api_rejects_invalid_and_future_dates() -> None:
    client = TestClient(api.app)
    future = date.today().replace(year=date.today().year + 1).isoformat()
    for path in (
        "/api/market-environment",
        "/api/market-environment/core",
        "/api/market-environment/chapter-01",
    ):
        assert client.get(f"{path}?as_of=not-a-date").status_code == 422
        assert client.get(f"{path}?as_of={future}").status_code == 422


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


def test_api_returns_progressive_core_and_chapter_payloads(monkeypatch) -> None:
    monkeypatch.setattr(api, "service", StubService())
    client = TestClient(api.app)

    core = client.get("/api/market-environment/core?as_of=2026-08-28")
    assert core.status_code == 200
    assert "chapter01" not in core.json()

    chapter = client.get("/api/market-environment/chapter-01?as_of=2026-08-28")
    assert chapter.status_code == 200
    assert chapter.json()["asOf"] == core.json()["asOf"]
    assert chapter.json()["chapter01"]["status"] == "insufficient"
