from datetime import date, timedelta

import pytest

from src.market_environment.calculations import Bar
from src.market_environment.providers import INDEX_SPECS, ProviderResult
from src.market_environment.schemas import MarketEnvironmentResponse
from src.market_environment.service import MarketEnvironmentService


def make_bars(count: int = 130) -> list[Bar]:
    start = date(2026, 2, 2)
    bars: list[Bar] = []
    current = start
    while len(bars) < count:
        if current.weekday() < 5:
            close = 3000 + len(bars) * 2
            bars.append(Bar(current, close - 2, close, close + 5, close - 5, 1_000_000 + len(bars) * 1000))
        current += timedelta(days=1)
    return bars


class FakeProvider:
    def __init__(self, failing: set[str] | None = None, stale: bool = False) -> None:
        self.failing = failing or set()
        self.stale = stale
        self.quote_calls = 0
        self.fetch_calls = 0

    def fetch_quotes(self, specs):
        self.quote_calls += 1
        return {
            spec.code: {
                "name": spec.name,
                "price": 3258.0,
                "change_pct": 1.1,
                "is_stale": self.stale,
            }
            for spec in specs
        }

    def fetch(self, spec, limit=160, expected_price=None, quote=None):
        self.fetch_calls += 1
        if spec.code in self.failing:
            raise RuntimeError("fixture source unavailable")
        return ProviderResult(make_bars(), "fixture")


def test_service_falls_back_to_last_trading_day_and_caches() -> None:
    provider = FakeProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)
    selected = date(2026, 8, 1)  # After the fixture's latest trading day.

    first = service.get(selected)
    second = service.get(selected)

    assert first["asOf"] == "2026-07-31"
    assert len(first["indices"]) == len(INDEX_SPECS)
    assert second is first
    assert provider.quote_calls == 1
    assert provider.fetch_calls == len(INDEX_SPECS)


def test_service_history_exposes_real_ohlc() -> None:
    payload = MarketEnvironmentService(provider=FakeProvider()).get(date(2026, 8, 28))
    history = payload["indices"][0]["history"]

    assert len(history) == 60
    assert history[-1]["open"] == history[-1]["close"] - 2
    assert history[-1]["high"] == history[-1]["close"] + 5
    assert history[-1]["low"] == history[-1]["close"] - 5
    MarketEnvironmentResponse.model_validate(payload)


def test_service_exposes_index_combination_and_market_overview() -> None:
    payload = MarketEnvironmentService(provider=FakeProvider()).get(date(2026, 8, 28))

    combination = payload["indices"][0]["combination"]
    assert set(combination) == {"key", "state", "matched", "tone", "evidence", "tradingMode"}
    assert combination["evidence"]
    overview = payload["chapter01"]["combinationOverview"]
    assert set(overview) == {"strength", "stage", "capitalAcceptance", "tradingMode", "confidence", "evidence"}
    assert overview["evidence"]
    MarketEnvironmentResponse.model_validate(payload)


def test_service_keeps_partial_success_and_warning() -> None:
    failed = {INDEX_SPECS[0].code}
    payload = MarketEnvironmentService(provider=FakeProvider(failing=failed)).get(date(2026, 8, 28))

    assert len(payload["indices"]) == 4
    assert any(INDEX_SPECS[0].name in warning for warning in payload["summary"]["warnings"])


def test_service_marks_stale_quote() -> None:
    payload = MarketEnvironmentService(provider=FakeProvider(stale=True)).get(date(2026, 8, 28))

    assert all(item["dataQuality"]["isStale"] for item in payload["indices"])
    assert all("停牌或过期" in (item["dataQuality"]["warning"] or "") for item in payload["indices"])


def test_service_raises_when_all_indices_fail() -> None:
    provider = FakeProvider(failing={spec.code for spec in INDEX_SPECS})
    with pytest.raises(RuntimeError, match="全部指数数据源不可用"):
        MarketEnvironmentService(provider=provider).get(date(2026, 8, 28))


def test_service_adds_null_safe_chapter01_contract_when_extended_provider_is_missing() -> None:
    payload = MarketEnvironmentService(provider=FakeProvider()).get(date(2026, 8, 28))

    assert len(payload["chapter01"]["documents"]) == 9
    assert payload["chapter01"]["breadth"]["advanceCount"] is None
    assert payload["chapter01"]["limits"]["limitUpCount"] is None
    assert payload["chapter01"]["events"]["state"] == "unverified"
    assert payload["chapter01"]["assessment"]["confidence"] == "insufficient"
    MarketEnvironmentResponse.model_validate(payload)
