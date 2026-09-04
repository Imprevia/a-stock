from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier, Event
from time import monotonic, sleep

import pytest

from src.market_environment.calculations import Bar
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.providers import INDEX_SPECS, ProviderResult
from src.market_environment.schemas import Chapter01Response, MarketEnvironmentResponse
from src.market_environment.service import MARKET_TIME_ZONE, MarketEnvironmentService, market_today
from src.market_environment.snapshot_store import MaterializedAggregateRecord, SnapshotRecord, SnapshotStore


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

    def fetch(self, spec, limit=280, expected_price=None, quote=None):
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
        raise AssertionError("breadth and active direction must be collected independently")

    def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
        self.chapter_calls.append("breadth")
        return {
            "advanceCount": 2,
            "declineCount": 1,
            "flatCount": 0,
            "validCount": 3,
            "advanceRatio": 0.6667,
            "medianReturn": 1.0,
            "state": "多数上涨",
            "quality": evidence_quality("market-breadth", as_of, 3),
        }

    def fetch_chapter01_active_direction(self, as_of, *, allow_current_snapshot):
        self.chapter_calls.append("activeDirection")
        return {
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


def test_section_loading_is_isolated_by_dataset() -> None:
    provider = SectionProvider()
    service = MarketEnvironmentService(provider=provider, ttl_seconds=60)
    selected = market_today()

    breadth = service.get_chapter01(selected, "breadth")
    assert provider.chapter_calls == ["breadth"]
    assert breadth["chapter01"]["breadth"]["advanceCount"] == 2
    assert breadth["chapter01"]["activeDirection"]["quality"]["status"] == "missing"

    active = service.get_chapter01(selected, "activeDirection")
    assert provider.chapter_calls == ["breadth", "activeDirection"]
    assert active["chapter01"]["activeDirection"]["topStocks"][0]["name"] == "样本股"
    assert active["chapter01"]["breadth"]["advanceCount"] == 2
    Chapter01Response.model_validate(active)

    limits = service.get_chapter01(selected, "limits")
    assert provider.chapter_calls == ["breadth", "activeDirection", "limits"]
    assert limits["chapter01"]["breadth"]["advanceCount"] == 2
    assert limits["chapter01"]["limits"]["limitUpCount"] == 10


@pytest.mark.parametrize(
    ("section", "expected_calls"),
    [
        ("limits", ["limits"]),
        ("sectors", ["sectors"]),
        ("summary", ["breadth", "activeDirection", "limits", "sectors"]),
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

    assert provider.chapter_calls == ["breadth", "activeDirection", "limits", "sectors"]
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
    assert provider.chapter_calls == ["breadth"]
    assert all(item["chapter01"]["breadth"]["advanceCount"] == 2 for item in results)


def test_persistent_snapshots_survive_service_restart_without_chapter_provider_calls(tmp_path, caplog) -> None:
    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    provider = SectionProvider()
    seed_service = MarketEnvironmentService(provider=provider, persistent_cache=False)
    core = seed_service._get_core(selected)
    effective = core["effectiveDate"]
    breadth = provider.fetch_chapter01_breadth(effective, allow_current_snapshot=True)
    active = provider.fetch_chapter01_active_direction(effective, allow_current_snapshot=True)
    provider.chapter_calls.clear()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=effective,
            payload=breadth,
            source="fixture",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=effective,
            payload=active,
            source="fixture",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )

    first = MarketEnvironmentService(provider=provider, snapshot_store=store, now=lambda: market_now)
    second = MarketEnvironmentService(provider=provider, snapshot_store=SnapshotStore(store.path), now=lambda: market_now)
    started = monotonic()
    with caplog.at_level("INFO"):
        breadth_payload = first.get_chapter01(selected, "breadth")
        active_payload = second.get_chapter01(selected, "activeDirection")
    elapsed = monotonic() - started

    assert provider.chapter_calls == []
    assert breadth_payload["chapter01"]["breadth"]["quality"]["cacheState"] == "fresh"
    assert active_payload["chapter01"]["activeDirection"]["quality"]["cacheState"] == "fresh"
    assert elapsed < 0.5
    cache_records = [record for record in caplog.records if getattr(record, "event", None) == "market_snapshot_cache_lookup"]
    assert cache_records
    assert all(record.cache_state == "fresh" for record in cache_records)
    assert all(record.lookup_ms >= 0 for record in cache_records)


def test_persistent_cold_requests_share_one_cross_service_refresh(tmp_path) -> None:
    class BlockingProvider(SectionProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
            self.chapter_calls.append("breadth")
            self.started.set()
            assert self.release.wait(timeout=5)
            return {
                "advanceCount": 2,
                "declineCount": 1,
                "flatCount": 0,
                "validCount": 3,
                "advanceRatio": 0.6667,
                "medianReturn": 1.0,
                "state": "多数上涨",
                "quality": evidence_quality("market-breadth", as_of, 3),
            }

    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    provider = BlockingProvider()
    path = tmp_path / "snapshots.sqlite3"
    first = MarketEnvironmentService(
        provider=provider,
        snapshot_store=SnapshotStore(path),
        now=lambda: market_now,
        cold_wait_seconds=5,
    )
    second = MarketEnvironmentService(
        provider=provider,
        snapshot_store=SnapshotStore(path),
        now=lambda: market_now,
        cold_wait_seconds=5,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first.get_chapter01, selected, "breadth")
        assert provider.started.wait(timeout=5)
        second_result = executor.submit(second.get_chapter01, selected, "breadth")
        sleep(0.1)
        assert provider.chapter_calls == ["breadth"]
        provider.release.set()
        results = [first_result.result(timeout=5), second_result.result(timeout=5)]

    assert provider.chapter_calls == ["breadth"]
    assert all(item["chapter01"]["breadth"]["advanceCount"] == 2 for item in results)


def test_stale_snapshot_returns_immediately_and_refreshes_in_background(tmp_path) -> None:
    class BlockingProvider(SectionProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
            self.chapter_calls.append("breadth")
            self.started.set()
            assert self.release.wait(timeout=5)
            return super().fetch_chapter01_breadth(as_of, allow_current_snapshot=allow_current_snapshot)

    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=14)
    provider = BlockingProvider()
    seed = MarketEnvironmentService(provider=provider, persistent_cache=False)._get_core(selected)
    effective = seed["effectiveDate"]
    stale_payload = {
        "advanceCount": 1,
        "declineCount": 2,
        "flatCount": 0,
        "validCount": 3,
        "advanceRatio": 0.3333,
        "medianReturn": -1.0,
        "state": "多数下跌",
        "quality": evidence_quality("market-breadth", effective, 3),
    }
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=effective,
            payload=stale_payload,
            source="old",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=market_now - timedelta(minutes=10),
            settled=False,
        )
    )
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        snapshot_ttl_seconds=30,
        now=lambda: market_now,
    )

    started = monotonic()
    result = service.get_chapter01(selected, "breadth")
    elapsed = monotonic() - started

    assert elapsed < 0.5
    assert result["chapter01"]["breadth"]["advanceCount"] == 1
    assert result["chapter01"]["breadth"]["quality"]["cacheState"] == "stale"
    assert result["chapter01"]["breadth"]["quality"]["refreshing"] is True
    assert provider.started.wait(timeout=5)
    provider.release.set()
    deadline = monotonic() + 5
    while store.get("breadth", effective).source == "old" and monotonic() < deadline:
        sleep(0.05)
    assert store.get("breadth", effective).source == "fixture"


def test_persistent_cache_can_be_disabled_for_rollback(tmp_path) -> None:
    provider = SectionProvider()
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=SnapshotStore(tmp_path / "snapshots.sqlite3"),
        persistent_cache=False,
    )

    payload = service.get_chapter01(market_today(), "breadth")

    assert provider.chapter_calls == ["breadth"]
    assert payload["chapter01"]["breadth"]["quality"].get("cacheState") is None


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
    assert payload["summary"]["syncPattern"]["code"] == "synchronized_rally"
    assert payload["summary"]["bullishAlignmentRatio"] == 1
    assert payload["indices"][0]["ma20SlopePercentile"] is not None
    assert payload["indices"][0]["advanceEfficiencyPercentile"] is not None
    assert payload["chapter01"]["summarySentence"]
    assert {gap["reason"] for gap in payload["chapter01"]["dataGaps"]} <= {
        "insufficient-history",
        "missing-today",
        "provider-failed",
        "not-computable",
    }
    MarketEnvironmentResponse.model_validate(payload)


def test_service_keeps_partial_success_and_warning() -> None:
    failed = {INDEX_SPECS[0].code}
    payload = MarketEnvironmentService(provider=FakeProvider(failing=failed)).get(date(2026, 8, 28))

    assert len(payload["indices"]) == 4
    assert any(INDEX_SPECS[0].name in warning for warning in payload["summary"]["warnings"])
    assert {"field": f"indices.{INDEX_SPECS[0].code}", "reason": "provider-failed"} in payload["summary"]["dataGaps"]
    assert {"field": f"indices.{INDEX_SPECS[0].code}", "reason": "provider-failed"} in payload["chapter01"]["dataGaps"]


def test_service_marks_missing_today_when_history_starts_after_request() -> None:
    class FutureProvider(FakeProvider):
        def fetch(self, spec, limit=280, expected_price=None, quote=None):
            if spec == INDEX_SPECS[0]:
                future = Bar(date(2027, 1, 4), 100, 100, 101, 99, 1000)
                return ProviderResult([future], "fixture")
            return super().fetch(spec, limit, expected_price, quote)

    payload = MarketEnvironmentService(provider=FutureProvider()).get(date(2026, 8, 28))
    assert {"field": f"indices.{INDEX_SPECS[0].code}", "reason": "missing-today"} in payload["summary"]["dataGaps"]


def test_data_gap_schema_accepts_closed_reason_set_and_rejects_unknown() -> None:
    from pydantic import ValidationError

    from src.market_environment.schemas import DataGap

    reasons = ("insufficient-history", "missing-today", "provider-failed", "not-computable")
    assert [DataGap(field="fixture", reason=reason).reason for reason in reasons] == list(reasons)
    with pytest.raises(ValidationError):
        DataGap(field="fixture", reason="unknown")


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


def test_materialized_local_read_is_provider_free_fast_and_non_blocking(tmp_path) -> None:
    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    provider = SectionProvider()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: market_now,
    )
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: market_now,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
    ).collect(selected)
    assert result.run.status == "success"
    provider.quote_calls = 0
    provider.fetch_calls = 0
    provider.chapter_calls.clear()
    store.acquire_lease("sectors", selected, "active-worker", lease_seconds=60, now=market_now)

    started = monotonic()
    payload = service.get(selected)
    elapsed = monotonic() - started

    assert elapsed < 0.5
    assert provider.quote_calls == 0
    assert provider.fetch_calls == 0
    assert provider.chapter_calls == []
    assert payload["chapter01"]["breadth"]["advanceCount"] == 2
    MarketEnvironmentResponse.model_validate(payload)


def test_failed_refresh_rebuilds_aggregate_with_retained_warning(tmp_path) -> None:
    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    provider = SectionProvider()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: market_now,
    )
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: market_now,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
    )
    coordinator.collect(selected)

    def fail_breadth(as_of, *, allow_current_snapshot):
        raise RuntimeError("breadth fixture failure")

    provider.fetch_chapter01_breadth = fail_breadth
    failed = coordinator.collect(selected, ["breadth"])
    payload = service.get(selected)

    assert failed.tasks[0].status == "failed-retained"
    assert payload["chapter01"]["breadth"]["advanceCount"] == 2
    assert payload["chapter01"]["breadth"]["quality"]["refreshWarning"] == "breadth fixture failure"


def test_materialized_assessment_uses_exact_previous_trading_day_without_provider_calls(tmp_path) -> None:
    selected = date(2026, 8, 28)
    provider = SectionProvider()
    seed_service = MarketEnvironmentService(provider=provider, persistent_cache=False)
    core = seed_service._get_core(selected)
    effective = core["effectiveDate"]
    previous = seed_service._previous_trading_date(core)
    assert previous is not None
    market_now = datetime.combine(effective, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="core",
            as_of=effective,
            payload=seed_service._core_payload(core),
            source="fixture",
            status="ok",
            observations=5,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )
    current_breadth = SectionProvider().fetch_chapter01_breadth(effective, allow_current_snapshot=True)
    previous_breadth = {
        **current_breadth,
        "advanceRatio": 0.55,
        "medianReturn": 0.2,
        "quality": evidence_quality("market-breadth", previous, 3),
    }
    for snapshot_date, snapshot_payload in ((effective, current_breadth), (previous, previous_breadth)):
        store.put(
            SnapshotRecord(
                dataset="breadth",
                as_of=snapshot_date,
                payload=snapshot_payload,
                source="fixture",
                status="ok",
                observations=3,
                warnings=(),
                fetched_at=market_now,
                settled=True,
            )
        )
    provider.quote_calls = 0
    provider.fetch_calls = 0
    provider.chapter_calls.clear()
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        local_reads_only=True,
        now=lambda: market_now,
    )

    payload = service.rebuild_materialized_aggregate(effective)
    assessment = payload["summary"]["synchronizationAssessment"]

    assert assessment["dimensions"]["breadth"]["previousAsOf"] == previous.isoformat()
    assert assessment["dimensions"]["breadth"]["comparisonStatus"] == "available"
    assert provider.quote_calls == 0
    assert provider.fetch_calls == 0
    assert provider.chapter_calls == []
    MarketEnvironmentResponse.model_validate(payload)


def test_assessment_does_not_substitute_older_breadth_snapshot(tmp_path) -> None:
    selected = date(2026, 8, 28)
    provider = SectionProvider()
    seed_service = MarketEnvironmentService(provider=provider, persistent_cache=False)
    core = seed_service._get_core(selected)
    effective = core["effectiveDate"]
    previous = seed_service._previous_trading_date(core)
    history_dates = sorted(
        date.fromisoformat(point["date"])
        for point in core["indices"][0]["history"]
        if date.fromisoformat(point["date"]) < previous
    )
    older = history_dates[-1]
    market_now = datetime.combine(effective, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="core",
            as_of=effective,
            payload=seed_service._core_payload(core),
            source="fixture",
            status="ok",
            observations=5,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )
    for snapshot_date in (effective, older):
        snapshot_payload = SectionProvider().fetch_chapter01_breadth(snapshot_date, allow_current_snapshot=True)
        store.put(
            SnapshotRecord(
                dataset="breadth",
                as_of=snapshot_date,
                payload=snapshot_payload,
                source="fixture",
                status="ok",
                observations=3,
                warnings=(),
                fetched_at=market_now,
                settled=True,
            )
        )
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        local_reads_only=True,
        now=lambda: market_now,
    )

    payload = service.rebuild_materialized_aggregate(effective)
    breadth_dimension = payload["summary"]["synchronizationAssessment"]["dimensions"]["breadth"]

    assert breadth_dimension["previousAsOf"] is None
    assert breadth_dimension["comparisonStatus"] == "insufficient"
    assert breadth_dimension["comparisonReason"] == "previous-breadth-unavailable"


def test_chapter_response_returns_updated_synchronization_summary() -> None:
    provider = SectionProvider()
    payload = MarketEnvironmentService(provider=provider).get_chapter01(market_today(), "breadth")

    assert payload["summary"]["synchronizationAssessment"] is not None
    assert payload["summary"]["synchronizationAssessment"]["patternCode"] == "synchronized_rally"
    Chapter01Response.model_validate(payload)


def test_local_chapter_response_refreshes_missing_materialized_synchronization_without_provider_calls(tmp_path) -> None:
    selected = market_today()
    market_now = datetime.combine(selected, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    provider = SectionProvider()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: market_now,
    )
    CollectionCoordinator(
        provider,
        store,
        now=lambda: market_now,
        rebuild_aggregate=service.rebuild_materialized_aggregate,
    ).collect(selected)
    materialized = store.get_materialized_aggregate(selected)
    assert materialized is not None
    legacy_payload = materialized.payload
    legacy_payload["summary"]["synchronizationAssessment"] = None
    store.put_materialized_aggregate(
        MaterializedAggregateRecord(
            as_of=selected,
            payload=legacy_payload,
            generated_at=market_now,
        )
    )
    provider.quote_calls = 0
    provider.fetch_calls = 0
    provider.chapter_calls.clear()

    payload = service.get_chapter01(selected, "summary")

    assert payload["summary"]["synchronizationAssessment"] is not None
    assert payload["chapter01"]["combinationOverview"]["strength"] == payload["summary"]["synchronizationAssessment"]["conclusion"]
    assert provider.quote_calls == 0
    assert provider.fetch_calls == 0
    assert provider.chapter_calls == []
    Chapter01Response.model_validate(payload)


def test_local_core_uses_existing_breadth_snapshot_for_synchronization_without_provider_calls(tmp_path) -> None:
    selected = date(2026, 8, 28)
    provider = SectionProvider()
    seed_service = MarketEnvironmentService(provider=provider, persistent_cache=False)
    core = seed_service._get_core(selected)
    effective = core["effectiveDate"]
    market_now = datetime.combine(effective, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="core",
            as_of=effective,
            payload=seed_service._core_payload(core),
            source="fixture",
            status="ok",
            observations=5,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )
    breadth = provider.fetch_chapter01_breadth(effective, allow_current_snapshot=True)
    store.put(
        SnapshotRecord(
            dataset="breadth",
            as_of=effective,
            payload=breadth,
            source="fixture",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=market_now,
            settled=True,
        )
    )
    service = MarketEnvironmentService(
        provider=provider,
        snapshot_store=store,
        persistent_cache=True,
        local_reads_only=True,
        now=lambda: market_now,
    )
    provider.quote_calls = 0
    provider.fetch_calls = 0
    provider.chapter_calls.clear()

    payload = service.get_core(effective)

    breadth = payload["summary"]["synchronizationAssessment"]["dimensions"]["breadth"]
    assert breadth["reason"] is None
    assert breadth["advanceRatio"] is not None
    assert provider.quote_calls == 0
    assert provider.fetch_calls == 0
    assert provider.chapter_calls == []
    MarketEnvironmentResponse.model_validate(payload)
