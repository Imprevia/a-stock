from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.domain.analysis import Bar
from src.market_environment.domain.models import (
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.providers.core_acquisition import (
    BAIDU_CORE_HISTORY_SOURCE_ID,
    CORE_HISTORY_SOURCE_ORDER,
    EASTMONEY_CORE_HISTORY_SOURCE_ID,
    FUYAO_CORE_HISTORY_SOURCE_ID,
    MOOTDX_CORE_HISTORY_SOURCE_ID,
    SINA_CORE_HISTORY_SOURCE_ID,
    TENCENT_CORE_HISTORY_SOURCE_ID,
    TENCENT_CORE_QUOTE_SOURCE_ID,
    BaiduCoreHistorySourceAdapter,
    CoreAcquisitionPlan,
    EastmoneyCoreHistorySourceAdapter,
    FuyaoCoreHistorySourceAdapter,
    MootdxCoreHistorySourceAdapter,
    SinaCoreHistorySourceAdapter,
    TencentCoreHistorySourceAdapter,
    TencentCoreQuoteSourceAdapter,
)
from src.market_environment.infrastructure.providers.fuyao.market import FuyaoMarketResult
from src.market_environment.providers import INDEX_SPECS


AS_OF = date(2026, 9, 18)
HISTORICAL = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _bars(as_of: date = AS_OF, count: int = 280, *, offset: float = 0) -> list[Bar]:
    values: list[Bar] = []
    for index in range(count):
        day = as_of - timedelta(days=count - index - 1)
        close = 3000.0 + index + offset
        values.append(
            Bar(
                date=day,
                open=close - 1,
                close=close,
                high=close + 2,
                low=close - 2,
                amount=1_000_000 + index,
            )
        )
    return values


@dataclass
class FakeLegacyProvider:
    calls: list[tuple[str, str]] = field(default_factory=list)
    failing: set[tuple[str, str]] = field(default_factory=set)
    quote_calls: int = 0

    def fetch_quotes(self, specs):
        self.quote_calls += 1
        return {
            spec.code: {
                "name": spec.name,
                "price": 3279.0,
                "last_close": 3278.0,
                "change_pct": 0.03,
                "amount": 1_000_000,
                "is_stale": False,
            }
            for spec in specs
        }

    def _result(self, source: str, spec, *, offset: float = 0):
        key = (source, spec.code)
        self.calls.append(key)
        if key in self.failing:
            raise RuntimeError(f"{source} unavailable for {spec.code}")
        return _bars(offset=offset)

    def _fetch_mootdx(self, spec, limit):
        return self._result("mootdx", spec)

    def _fetch_baidu_kline(self, spec, limit):
        return self._result("baidu", spec)

    def _fetch_sina_kline(self, spec, limit, quote):
        return self._result("sina", spec)

    def _fetch_tencent_kline(self, spec, limit):
        return self._result("tencent", spec)

    def _fetch_eastmoney_kline(self, spec, limit):
        return self._result("eastmoney", spec)


@dataclass
class FakeFuyao:
    calls: list[tuple[date, tuple[str, ...], dict[str, Any]]] = field(default_factory=list)
    status: str = "ok"
    warnings: tuple[str, ...] = ()
    failing_codes: set[str] = field(default_factory=set)

    def fetch_core(self, as_of, *, codes=None, limit=280, quotes_by_code=None):
        selected = tuple(codes or ())
        self.calls.append((as_of, selected, dict(quotes_by_code or {})))
        result: dict[str, FuyaoMarketResult] = {}
        for code in selected:
            payload = {"code": code, "bars": _bars(as_of)}
            if code in self.failing_codes:
                result[code] = FuyaoMarketResult(
                    payload=payload,
                    quality={
                        "providerRevision": "fuyao-market-v2",
                        "status": "insufficient",
                        "asOf": as_of.isoformat(),
                        "warnings": ["fixture Fuyao history unavailable"],
                    },
                    status="insufficient",
                    as_of=as_of,
                    observations=0,
                    warnings=("fixture Fuyao history unavailable",),
                )
            else:
                result[code] = FuyaoMarketResult(
                    payload=payload,
                    quality={
                        "providerRevision": "fuyao-market-v2",
                        "status": self.status,
                        "asOf": as_of.isoformat(),
                        "warnings": list(self.warnings),
                    },
                    status=self.status,
                    as_of=as_of,
                    observations=280,
                    warnings=self.warnings,
                )
        return result


def _plan(
    provider: FakeLegacyProvider,
    fuyao: FakeFuyao | None = None,
    *,
    fuyao_enabled: bool = False,
    shadow_enabled: bool = False,
    current_date: date = AS_OF,
    retained=None,
):
    fuyao = fuyao or FakeFuyao()
    adapters = SourceAdapterRegistry(
        (
            TencentCoreQuoteSourceAdapter(provider, now=lambda: NOW),
            FuyaoCoreHistorySourceAdapter(fuyao, now=lambda: NOW),
            MootdxCoreHistorySourceAdapter(provider, now=lambda: NOW),
            BaiduCoreHistorySourceAdapter(provider, now=lambda: NOW),
            SinaCoreHistorySourceAdapter(provider, now=lambda: NOW),
            TencentCoreHistorySourceAdapter(provider, now=lambda: NOW),
            EastmoneyCoreHistorySourceAdapter(provider, now=lambda: NOW),
        )
    )
    return CoreAcquisitionPlan(
        adapters=adapters,
        index_specs=tuple(INDEX_SPECS),
        fuyao_is_enabled=lambda dataset: dataset == "core" and fuyao_enabled,
        fuyao_shadow_enabled=lambda dataset: dataset == "core" and shadow_enabled,
        fuyao_revision=lambda _dataset: "fuyao-market-v2",
        retained_indices=retained or (lambda _identity: {}),
        market_today=lambda: current_date,
        is_settled=lambda _as_of: True,
        now=lambda: NOW,
    )


def test_core_plan_declares_order_and_keeps_mootdx_non_http() -> None:
    provider = FakeLegacyProvider()
    plan = _plan(provider)

    assert tuple(step.adapter_id for step in plan.steps[1:]) == CORE_HISTORY_SOURCE_ORDER
    assert plan.adapters.get(MOOTDX_CORE_HISTORY_SOURCE_ID).capability.provider == "mootdx"
    assert plan.adapters.get(MOOTDX_CORE_HISTORY_SOURCE_ID).capability.methods == ("TCP",)


def test_current_date_quote_cross_check_is_one_shared_quote_attempt() -> None:
    provider = FakeLegacyProvider()
    fuyao = FakeFuyao()
    outcome = _plan(provider, fuyao, fuyao_enabled=True).collect(DatasetDate("core", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert provider.quote_calls == 1
    assert len(fuyao.calls) == 5
    assert all(call[0] == AS_OF for call in fuyao.calls)
    assert [tuple(call[1]) for call in fuyao.calls] == [
        (spec.code,) for spec in INDEX_SPECS
    ]
    assert {attempt.source for attempt in outcome.attempts} >= {
        "tencent-realtime-quote",
        "fuyao",
    }


def test_historical_core_is_quote_free_and_retains_exact_request_identity() -> None:
    provider = FakeLegacyProvider()
    fuyao = FakeFuyao()
    outcome = _plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        current_date=AS_OF,
    ).collect(DatasetDate("core", HISTORICAL))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert provider.quote_calls == 0
    assert all(call[0] == HISTORICAL and call[2] == {} for call in fuyao.calls)
    assert outcome.candidate is not None
    assert outcome.candidate.identity == DatasetDate("core", HISTORICAL)


def test_each_index_falls_back_independently_and_preserves_source_attribution() -> None:
    failed_code = INDEX_SPECS[0].code
    provider = FakeLegacyProvider(
        failing={
            (source, failed_code)
            for source in ("mootdx", "baidu", "sina", "tencent", "eastmoney")
        }
    )
    outcome = _plan(provider).collect(DatasetDate("core", AS_OF))

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert len(outcome.candidate.payload["indices"]) == 4
    assert provider.calls[:5] == [
        ("mootdx", failed_code),
        ("baidu", failed_code),
        ("sina", failed_code),
        ("tencent", failed_code),
        ("eastmoney", failed_code),
    ]
    assert any(
        item["code"] == failed_code
        and item["status"] == CollectionTaskState.FAILED_MISSING.value
        and item["source"] == "none"
        for item in outcome.candidate.quality.extra["indexResults"]
    )
    assert any(attempt.source == TENCENT_CORE_HISTORY_SOURCE_ID for attempt in outcome.attempts)


def test_one_index_can_fallback_to_tencent_without_downgrading_complete_core() -> None:
    fallback_code = INDEX_SPECS[0].code
    provider = FakeLegacyProvider(
        failing={
            (source, fallback_code)
            for source in ("mootdx", "baidu", "sina")
        }
    )
    outcome = _plan(provider).collect(DatasetDate("core", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    evidence = {
        item["code"]: item for item in outcome.candidate.quality.extra["indexResults"]
    }
    assert evidence[fallback_code]["source"] == "tencent-kline"
    assert evidence[fallback_code]["status"] == CollectionTaskState.SUCCESS.value
    assert provider.calls[:4] == [
        ("mootdx", fallback_code),
        ("baidu", fallback_code),
        ("sina", fallback_code),
        ("tencent", fallback_code),
    ]


def test_same_date_retained_index_survives_all_sources_failing_for_one_sibling() -> None:
    failed_code = INDEX_SPECS[0].code
    seed = _plan(FakeLegacyProvider()).collect(DatasetDate("core", AS_OF))
    assert seed.candidate is not None
    retained = {
        failed_code: next(
            item
            for item in seed.candidate.payload["indices"]
            if item["code"] == failed_code
        )
    }
    provider = FakeLegacyProvider(
        failing={(source, failed_code) for source in ("mootdx", "baidu", "sina", "tencent", "eastmoney")}
    )
    outcome = _plan(provider, retained=lambda _identity: retained).collect(
        DatasetDate("core", AS_OF)
    )

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    evidence = {
        item["code"]: item for item in outcome.candidate.quality.extra["indexResults"]
    }
    assert evidence[failed_code]["status"] == CollectionTaskState.FAILED_RETAINED.value
    assert evidence[failed_code]["retained"] is True
    assert retained[failed_code] in outcome.candidate.payload["indices"]
    assert outcome.candidate.quality.extra["tradingSession"]["previousAsOf"] == (
        AS_OF - timedelta(days=1)
    ).isoformat()


def test_all_sources_failed_without_retention_is_failed_missing() -> None:
    failing = {
        (source, spec.code)
        for source in ("mootdx", "baidu", "sina", "tencent", "eastmoney")
        for spec in INDEX_SPECS
    }
    outcome = _plan(FakeLegacyProvider(failing=failing)).collect(
        DatasetDate("core", AS_OF)
    )

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.candidate is None
    assert outcome.failure is not None
    assert "全部指数数据源不可用" in outcome.failure.message


def test_all_sources_failed_with_same_date_retention_is_failed_retained() -> None:
    seed = _plan(FakeLegacyProvider()).collect(DatasetDate("core", AS_OF))
    assert seed.candidate is not None
    retained = {
        item["code"]: item for item in seed.candidate.payload["indices"]
    }
    failing = {
        (source, spec.code)
        for source in ("mootdx", "baidu", "sina", "tencent", "eastmoney")
        for spec in INDEX_SPECS
    }
    outcome = _plan(
        FakeLegacyProvider(failing=failing),
        retained=lambda _identity: retained,
    ).collect(DatasetDate("core", AS_OF))

    assert outcome.state is CollectionTaskState.FAILED_RETAINED
    assert outcome.retained is True
    assert outcome.candidate is not None
    assert outcome.candidate.source == "mootdx"
    assert outcome.candidate.payload["indices"] == list(retained.values())


def test_fuyao_failure_fallback_is_partial_and_keeps_ordered_attempt_evidence() -> None:
    provider = FakeLegacyProvider()
    fuyao = FakeFuyao(failing_codes={spec.code for spec in INDEX_SPECS})
    outcome = _plan(provider, fuyao, fuyao_enabled=True).collect(
        DatasetDate("core", AS_OF)
    )

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert all(
        item["dataQuality"]["source"] == "mootdx"
        for item in outcome.candidate.payload["indices"]
    )
    first_sources = [attempt.source for attempt in outcome.attempts[:3]]
    assert first_sources == ["tencent-realtime-quote", FUYAO_CORE_HISTORY_SOURCE_ID, "mootdx"]
    assert any("扶摇失败并回退" in warning for warning in outcome.candidate.warnings)


def test_stale_history_keeps_subresults_but_marks_missing_session_evidence() -> None:
    provider = FakeLegacyProvider()
    old_date = AS_OF - timedelta(days=1)
    original = _bars(old_date)
    provider._fetch_mootdx = lambda spec, limit: original
    outcome = _plan(provider).collect(DatasetDate("core", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.payload["asOf"] == old_date.isoformat()
    assert outcome.candidate.quality.extra["tradingSession"] is None
    assert "could not prove" in (outcome.candidate.quality.extra["sessionWarning"] or "")


def test_stale_current_quotes_are_preserved_as_quality_evidence() -> None:
    provider = FakeLegacyProvider()
    original = provider.fetch_quotes

    def stale_quotes(specs):
        quotes = original(specs)
        for quote in quotes.values():
            quote["is_stale"] = True
        return quotes

    provider.fetch_quotes = stale_quotes
    outcome = _plan(provider).collect(DatasetDate("core", AS_OF))

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert all(
        item["dataQuality"]["isStale"] is True
        and "停牌或过期" in item["dataQuality"]["warning"]
        for item in outcome.candidate.payload["indices"]
    )
