from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest

from src.market_environment.calculations import Bar
from src.market_environment.providers import INDEX_SPECS, ProviderResult
from src.market_environment.schemas import Chapter01Response, MarketEnvironmentResponse
from src.market_environment.service import MarketEnvironmentService, market_today


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


def evidence_quality(dataset: str, as_of: date, observations: int = 1) -> dict:
    return {
        "dataset": dataset,
        "source": "fixture",
        "provider": "fixture",
        "status": "ok",
        "observations": observations,
        "asOf": as_of.isoformat(),
        "warning": None,
        "warnings": [],
    }


class SectionProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.chapter_calls: list[str] = []

    def fetch_chapter01(self, as_of, *, allow_current_snapshot):
        raise AssertionError("section-aware service must not call the aggregate provider")

    def fetch_chapter01_stock(self, as_of, *, allow_current_snapshot):
        self.chapter_calls.append("stock")
        return {
            "breadth": {
                "advanceCount": 2,
                "declineCount": 1,
                "flatCount": 0,
                "validCount": 3,
                "advanceRatio": 0.6667,
                "medianReturn": 1.0,
                "state": "多数上涨",
                "quality": evidence_quality("market-breadth", as_of, 3),
            },
            "activeDirection": {
                "state": "candidate",
                "summary": "fixture direction",
                "topStocks": [
                    {
                        "code": "000001",
                        "name": "样本股",
                        "industry": "电子",
                        "changePct": 2.0,
                        "amount": 1000.0,
                        "closePosition": 0.8,
                    }
                ],
                "quality": evidence_quality("active-direction", as_of),
            },
        }

    def fetch_chapter01_limits(self, as_of):
        self.chapter_calls.append("limits")
        return {
            "limitUpCount": 10,
            "limitDownCount": 2,
            "failedLimitUpCount": 3,
            "failedLimitUpRatio": 0.2308,
            "maxStreak": 4,
            "state": "已观测",
            "quality": evidence_quality("limit-pools", as_of, 15),
        }

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
        self.chapter_calls.append("sectors")
        return {
            "rows": [],
            "state": "当日排名已观测",
            "quality": evidence_quality("industry-ranking", as_of),
        }


def test_service_falls_back_to_last_trading_day_and_caches() -> None:
    provider = FakeProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)
    selected = date(2026, 8, 1)  # After the fixture's latest trading day.

    first = service.get(selected)
    second = service.get(selected)

    assert first["asOf"] == "2026-07-31"
    assert len(first["indices"]) == len(INDEX_SPECS)
    assert second == first
    assert provider.quote_calls == 1
    assert provider.fetch_calls == len(INDEX_SPECS)


def test_core_does_not_call_chapter_providers() -> None:
    provider = SectionProvider()
    payload = MarketEnvironmentService(provider=provider).get_core(market_today())

    assert provider.chapter_calls == []
    assert payload["chapter01"]["breadth"]["quality"]["status"] == "missing"
    assert payload["chapter01"]["limits"]["quality"]["status"] == "missing"
    MarketEnvironmentResponse.model_validate(payload)


def test_section_loading_is_isolated_and_stock_snapshot_is_shared() -> None:
    provider = SectionProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)
    selected = market_today()

    breadth = service.get_chapter01(selected, "breadth")
    assert provider.chapter_calls == ["stock"]
    assert breadth["chapter01"]["breadth"]["advanceCount"] == 2
    assert breadth["chapter01"]["activeDirection"]["topStocks"][0]["name"] == "样本股"

    active = service.get_chapter01(selected, "activeDirection")
    assert provider.chapter_calls == ["stock"]
    assert active["chapter01"]["activeDirection"]["topStocks"][0]["name"] == "样本股"
    assert active["chapter01"]["breadth"]["advanceCount"] == 2
    Chapter01Response.model_validate(active)

    limits = service.get_chapter01(selected, "limits")
    assert provider.chapter_calls == ["stock", "limits"]
    assert limits["chapter01"]["breadth"]["advanceCount"] == 2
    assert limits["chapter01"]["limits"]["limitUpCount"] == 10


@pytest.mark.parametrize(
    ("section", "expected_calls"),
    [
        ("limits", ["limits"]),
        ("sectors", ["sectors"]),
        ("summary", ["stock", "limits", "sectors"]),
    ],
)
def test_section_loading_only_calls_required_provider_groups(section: str, expected_calls: list[str]) -> None:
    provider = SectionProvider()
    payload = MarketEnvironmentService(provider=provider).get_chapter01(market_today(), section)

    assert provider.chapter_calls == expected_calls
    Chapter01Response.model_validate(payload)


def test_legacy_aggregate_composes_all_section_groups_and_reuses_caches() -> None:
    provider = SectionProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)

    first = service.get(market_today())
    second = service.get(market_today())

    assert provider.chapter_calls == ["stock", "limits", "sectors"]
    assert provider.quote_calls == 1
    assert provider.fetch_calls == len(INDEX_SPECS)
    assert second == first
    assert first["chapter01"]["breadth"]["advanceCount"] == 2
    assert first["chapter01"]["limits"]["limitUpCount"] == 10
    MarketEnvironmentResponse.model_validate(first)


def test_cache_ttl_starts_after_slow_core_fetch_completes() -> None:
    ticks = [0.0]

    class SlowProvider(FakeProvider):
        def fetch(self, spec, limit=160, expected_price=None, quote=None):
            ticks[0] += 10
            return super().fetch(spec, limit, expected_price, quote)

    provider = SlowProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=30, clock=lambda: ticks[0])

    service.get_core(date(2026, 8, 28))
    service.get_core(date(2026, 8, 28))

    assert provider.quote_calls == 1
    assert provider.fetch_calls == len(INDEX_SPECS)


def test_concurrent_section_requests_share_one_provider_load() -> None:
    provider = SectionProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)
    barrier = Barrier(4)

    def load_breadth() -> dict:
        barrier.wait()
        return service.get_chapter01(market_today(), "breadth")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: load_breadth(), range(4)))

    assert provider.quote_calls == 1
    assert provider.fetch_calls == len(INDEX_SPECS)
    assert provider.chapter_calls == ["stock"]
    assert all(item["chapter01"]["breadth"]["advanceCount"] == 2 for item in results)


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
