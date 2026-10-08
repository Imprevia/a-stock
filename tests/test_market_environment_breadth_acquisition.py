from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.application.ports import SourceRequest
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.legacy.snapshot_store import payload_checksum
from src.market_environment.infrastructure.providers.breadth_acquisition import (
    EASTMONEY_BREADTH_SOURCE_ID,
    FUYAO_BREADTH_SOURCE_ID,
    TDX_BREADTH_SOURCE_ID,
    BreadthAcquisitionPlan,
    EastmoneyBreadthSourceAdapter,
    FuyaoBreadthSourceAdapter,
    TDXBreadthSourceAdapter,
)
from src.market_environment.infrastructure.providers.fuyao.market import (
    FuyaoMarketResult,
)
from src.market_environment.infrastructure.providers.tdx.daily_package import (
    TDXDailyPackageError,
    TDXStockUniverseClassification,
    TDXStockUniverseError,
)


AS_OF = date(2026, 9, 18)
HISTORICAL_AS_OF = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
IDENTITY = DatasetDate("breadth", AS_OF)


def _payload(
    source: str,
    *,
    status: str,
    warnings: tuple[str, ...] = (),
    as_of: date = AS_OF,
    values: tuple[int, int, int] = (2, 1, 0),
    revision: str | None = None,
) -> dict[str, Any]:
    advance, decline, flat = values
    valid = advance + decline + flat
    separator = "; " if source == "fuyao" else "；"
    quality = {
        "dataset": "market-breadth",
        "source": source,
        "provider": source,
        "status": status,
        "observations": valid,
        "asOf": as_of.isoformat(),
        "warning": separator.join(warnings) if warnings else None,
        "warnings": list(warnings),
    }
    if revision is not None:
        quality["providerRevision"] = revision
    return {
        "advanceCount": advance,
        "declineCount": decline,
        "flatCount": flat,
        "validCount": valid,
        "advanceRatio": round(advance / valid, 4),
        "medianReturn": 0.5,
        "state": "多数上涨",
        "quality": quality,
    }


def _fuyao_result(
    *,
    status: str = "ok",
    values: tuple[int, int, int] = (2, 1, 0),
    warnings: tuple[str, ...] = (),
) -> FuyaoMarketResult:
    value = _payload(
        "fuyao",
        status=status,
        values=values,
        warnings=warnings,
        revision="r1",
    )
    quality = value.pop("quality")
    return FuyaoMarketResult(
        payload=value,
        quality=quality,
        status=status,
        as_of=AS_OF,
        observations=int(quality["observations"]),
        warnings=warnings,
    )


@dataclass
class StubFuyao:
    result: FuyaoMarketResult | Exception
    calls: list[date] = field(default_factory=list)

    def fetch_breadth(self, as_of: date) -> FuyaoMarketResult:
        self.calls.append(as_of)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class StubProvider:
    tdx_result: dict[str, Any] | Exception
    eastmoney_result: dict[str, Any] | Exception | None = None
    tdx_calls: list[tuple[date, list[str]]] = field(default_factory=list)
    eastmoney_calls: list[tuple[date, str]] = field(default_factory=list)

    def _fetch_tdx_breadth(
        self,
        as_of: date,
        warnings: list[str],
    ) -> dict[str, Any]:
        self.tdx_calls.append((as_of, warnings))
        if isinstance(self.tdx_result, Exception):
            raise self.tdx_result
        return self.tdx_result

    def _fetch_eastmoney_breadth_fallback(
        self,
        as_of: date,
        primary_warning: str,
    ) -> dict[str, Any]:
        self.eastmoney_calls.append((as_of, primary_warning))
        if isinstance(self.eastmoney_result, Exception):
            raise self.eastmoney_result
        if self.eastmoney_result is not None:
            return self.eastmoney_result
        return _payload(
            "eastmoney-clist-delay",
            status="fallback",
            warnings=(
                primary_warning,
                "已按涨跌幅排序分页定位全 A 有效样本",
            ),
            as_of=as_of,
        )


def _build_plan(
    provider: StubProvider,
    fuyao: StubFuyao,
    *,
    fuyao_enabled: bool = False,
    shadow_enabled: bool = False,
    tdx_enabled: bool = True,
    market_today: date = AS_OF,
) -> tuple[
    BreadthAcquisitionPlan,
    FuyaoBreadthSourceAdapter,
    TDXBreadthSourceAdapter,
    EastmoneyBreadthSourceAdapter,
]:
    fuyao_source = FuyaoBreadthSourceAdapter(fuyao, revision="r1", now=lambda: NOW)
    tdx_source = TDXBreadthSourceAdapter(provider, revision="tdx-r1", now=lambda: NOW)
    eastmoney_source = EastmoneyBreadthSourceAdapter(
        provider,
        revision="eastmoney-r1",
        now=lambda: NOW,
    )
    registry = SourceAdapterRegistry(
        (fuyao_source, tdx_source, eastmoney_source)
    )
    plan = BreadthAcquisitionPlan(
        adapters=registry,
        fuyao_is_enabled=lambda dataset: dataset == "breadth" and fuyao_enabled,
        fuyao_shadow_enabled=lambda dataset: dataset == "breadth" and shadow_enabled,
        fuyao_revision=lambda _dataset: "r1",
        tdx_is_enabled=lambda: tdx_enabled,
        market_today=lambda: market_today,
        is_settled=lambda requested: requested <= market_today,
    )
    return plan, fuyao_source, tdx_source, eastmoney_source


def test_fuyao_primary_preserves_payload_source_observations_and_warnings() -> None:
    raw = _fuyao_result(warnings=("fixture warning",))
    fuyao = StubFuyao(raw)
    provider = StubProvider(AssertionError("TDX must not run"))
    plan, *_sources = _build_plan(provider, fuyao, fuyao_enabled=True)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.payload == raw.as_dict()
    assert outcome.candidate.source == "fuyao"
    assert outcome.candidate.status == "ok"
    assert outcome.candidate.observations == 3
    assert outcome.candidate.warnings == ("fixture warning",)
    assert outcome.warning == "fixture warning"
    assert [attempt.role for attempt in outcome.attempts] == ["formal"]
    assert fuyao.calls == [AS_OF]
    assert provider.tdx_calls == []
    assert provider.eastmoney_calls == []


def test_fuyao_exception_falls_back_to_tdx_with_legacy_warning_order() -> None:
    tdx_warnings = (
        "已使用通达信盘后包的精确日期和过滤后的普通 A 股样本",
        "已按 tdx-stock-universe-v1 过滤普通 A 股：原始 3，保留 3，排除 0，未分类 0",
    )
    raw_tdx = _payload(
        "tdx-daily-package",
        status="fallback",
        warnings=tdx_warnings,
    )
    provider = StubProvider(raw_tdx)
    plan, *_sources = _build_plan(
        provider,
        StubFuyao(RuntimeError("fixture Fuyao unavailable")),
        fuyao_enabled=True,
    )

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.payload == raw_tdx
    assert outcome.candidate.source == "tdx-daily-package"
    assert outcome.candidate.status == "fallback"
    assert outcome.candidate.warnings == tdx_warnings
    assert outcome.warning == (
        f"{'；'.join(tdx_warnings)}; "
        "扶摇采集失败，已回退现有 provider：fixture Fuyao unavailable"
    )
    assert [attempt.role for attempt in outcome.attempts] == ["formal", "fallback"]
    assert outcome.attempts[0].warning == (
        "扶摇采集失败，已回退现有 provider：fixture Fuyao unavailable"
    )
    assert provider.eastmoney_calls == []


def test_fuyao_insufficient_quality_falls_back_without_publishing_candidate() -> None:
    raw_tdx = _payload("tdx-daily-package", status="fallback")
    provider = StubProvider(raw_tdx)
    plan, *_sources = _build_plan(
        provider,
        StubFuyao(_fuyao_result(status="insufficient")),
        fuyao_enabled=True,
    )

    outcome = plan.collect(IDENTITY)

    assert outcome.candidate is not None
    assert outcome.candidate.source == "tdx-daily-package"
    assert outcome.warning == "扶摇采集质量为 insufficient，已回退现有 provider"
    assert outcome.attempts[0].category is AcquisitionFailureCategory.INSUFFICIENT
    assert outcome.attempts[0].warning == outcome.warning


def test_tdx_gate_skips_eastmoney_after_exact_package_success() -> None:
    raw_tdx = _payload(
        "tdx-daily-package",
        status="fallback",
        warnings=("已使用通达信盘后包的精确日期和过滤后的普通 A 股样本",),
    )
    provider = StubProvider(raw_tdx)
    plan, *_sources = _build_plan(provider, StubFuyao(_fuyao_result()))

    outcome = plan.collect(IDENTITY)

    assert outcome.candidate is not None
    assert outcome.candidate.payload == raw_tdx
    assert outcome.candidate.actual_as_of == AS_OF
    assert outcome.candidate.provenance.attributes["dateEvidenceKind"] == "package"
    assert provider.tdx_calls == [(AS_OF, [])]
    assert provider.eastmoney_calls == []


def _universe_error() -> TDXStockUniverseError:
    classification = TDXStockUniverseClassification(
        rows=(),
        policy_version="tdx-stock-universe-v1",
        raw_count=1,
        retained_count=0,
        excluded_count=0,
        unclassified_count=1,
        retained_by_market={},
        excluded_by_reason={},
        unclassified_by_reason={"unknown": 1},
    )
    return TDXStockUniverseError("retained sample is below minimum", classification)


@pytest.mark.parametrize(
    ("tdx_error", "tdx_warning"),
    [
        (
            _universe_error(),
            "通达信普通 A 股 universe 不足：retained sample is below minimum",
        ),
        (
            TDXDailyPackageError("package missing"),
            "通达信盘后包不可用：package missing",
        ),
    ],
)
def test_tdx_failures_fall_back_to_eastmoney_with_exact_warning_chain(
    tdx_error: Exception,
    tdx_warning: str,
) -> None:
    provider = StubProvider(tdx_error)
    plan, *_sources = _build_plan(provider, StubFuyao(_fuyao_result()))

    outcome = plan.collect(IDENTITY)

    primary_warning = (
        f"{tdx_warning}；已降级到东方财富市场广度涨跌幅排序分页统计"
    )
    assert provider.eastmoney_calls == [(AS_OF, primary_warning)]
    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist-delay"
    assert outcome.candidate.status == "fallback"
    assert outcome.candidate.observations == 3
    assert outcome.candidate.warnings == (
        primary_warning,
        "已按涨跌幅排序分页定位全 A 有效样本",
    )
    assert outcome.warning == (
        f"{primary_warning}；已按涨跌幅排序分页定位全 A 有效样本"
    )


def test_all_sources_failed_returns_classified_failure_without_candidate() -> None:
    provider = StubProvider(
        TDXDailyPackageError("package unavailable"),
        RuntimeError("delay host unavailable"),
    )
    plan, *_sources = _build_plan(provider, StubFuyao(_fuyao_result()))

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.candidate is None
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.NETWORK
    assert outcome.warning == (
        "通达信盘后包不可用：package unavailable；"
        "东方财富市场广度不可用：delay host unavailable"
    )
    assert [attempt.category for attempt in outcome.attempts] == [
        AcquisitionFailureCategory.INSUFFICIENT,
        AcquisitionFailureCategory.NETWORK,
    ]


def test_historical_request_uses_only_tdx_exact_date_capability() -> None:
    raw_tdx = _payload(
        "tdx-daily-package",
        status="fallback",
        as_of=HISTORICAL_AS_OF,
    )
    provider = StubProvider(raw_tdx)
    fuyao = StubFuyao(_fuyao_result())
    plan, *_sources = _build_plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        shadow_enabled=True,
    )
    identity = DatasetDate("breadth", HISTORICAL_AS_OF)

    outcome = plan.collect(identity)

    assert outcome.candidate is not None
    assert outcome.candidate.actual_as_of == HISTORICAL_AS_OF
    assert outcome.candidate.source == "tdx-daily-package"
    assert provider.tdx_calls == [(HISTORICAL_AS_OF, [])]
    assert provider.eastmoney_calls == []
    assert fuyao.calls == []


def test_historical_latest_only_adapters_reject_before_io() -> None:
    provider = StubProvider(AssertionError("TDX is not part of this adapter test"))
    fuyao = StubFuyao(AssertionError("Fuyao must not run"))
    _plan, fuyao_source, _tdx_source, eastmoney_source = _build_plan(
        provider,
        fuyao,
        tdx_enabled=False,
    )
    identity = DatasetDate("breadth", HISTORICAL_AS_OF)
    common = {
        "identity": identity,
        "current_market_date": AS_OF,
        "settled": True,
    }

    fuyao_result = fuyao_source.acquire(
        SourceRequest(
            source_id=FUYAO_BREADTH_SOURCE_ID,
            capability_revision="r1",
            **common,
        )
    )
    eastmoney_result = eastmoney_source.acquire(
        SourceRequest(
            source_id=EASTMONEY_BREADTH_SOURCE_ID,
            capability_revision="eastmoney-r1",
            params={"primary_warning": "unused"},
            **common,
        )
    )

    assert isinstance(fuyao_result, AcquisitionFailure)
    assert isinstance(eastmoney_result, AcquisitionFailure)
    assert fuyao_result.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert eastmoney_result.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert fuyao.calls == []
    assert provider.eastmoney_calls == []


def test_historical_without_tdx_returns_explicit_rejection_without_latest_io() -> None:
    provider = StubProvider(AssertionError("TDX disabled"))
    fuyao = StubFuyao(AssertionError("Fuyao must not run"))
    plan, *_sources = _build_plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        shadow_enabled=True,
        tdx_enabled=False,
    )

    outcome = plan.collect(DatasetDate("breadth", HISTORICAL_AS_OF))

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert outcome.warning == "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
    assert outcome.attempts == ()
    assert fuyao.calls == []
    assert provider.tdx_calls == []
    assert provider.eastmoney_calls == []


def test_shadow_comparison_never_changes_formal_payload_source_or_checksum() -> None:
    provider = StubProvider(
        AssertionError("TDX disabled"),
        _payload("eastmoney-clist-delay", status="fallback"),
    )
    fuyao = StubFuyao(_fuyao_result(values=(1, 2, 0)))
    plan, *_sources = _build_plan(
        provider,
        fuyao,
        shadow_enabled=True,
        tdx_enabled=False,
    )
    expected = provider.eastmoney_result
    assert isinstance(expected, dict)
    expected_checksum = payload_checksum(expected)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.payload == expected
    assert outcome.candidate.source == "eastmoney-clist-delay"
    assert payload_checksum(outcome.candidate.payload) == expected_checksum
    assert [attempt.role for attempt in outcome.attempts] == ["fallback", "shadow"]
    comparison = outcome.attempts[-1].provenance.attributes["comparison"]
    assert comparison["status"] == "mismatch"
    assert outcome.attempts[-1].warning == "扶摇 shadow: mismatch"
    assert outcome.warning == "扶摇 shadow: mismatch"


def test_breadth_adapters_have_no_collection_or_persistence_side_effect_ports() -> None:
    provider = StubProvider(_payload("tdx-daily-package", status="fallback"))
    _plan, *sources = _build_plan(provider, StubFuyao(_fuyao_result()))

    for source in sources:
        assert not any(
            hasattr(source, attribute)
            for attribute in ("store", "coordinator", "lease", "committer", "rebuild")
        )
    assert {source.source_id for source in sources} == {
        FUYAO_BREADTH_SOURCE_ID,
        TDX_BREADTH_SOURCE_ID,
        EASTMONEY_BREADTH_SOURCE_ID,
    }


def test_tdx_adapter_rejects_mismatched_quality_date() -> None:
    provider = StubProvider(
        _payload(
            "tdx-daily-package",
            status="fallback",
            as_of=HISTORICAL_AS_OF,
        )
    )
    _plan, _fuyao_source, tdx_source, _eastmoney_source = _build_plan(
        provider,
        StubFuyao(_fuyao_result()),
    )

    result = tdx_source.acquire(
        SourceRequest(
            identity=IDENTITY,
            source_id=TDX_BREADTH_SOURCE_ID,
            capability_revision="tdx-r1",
            current_market_date=AS_OF,
            settled=True,
        )
    )

    assert isinstance(result, AcquisitionFailure)
    assert result.category is AcquisitionFailureCategory.DATE_MISMATCH


def test_adapter_classifies_malformed_quality_instead_of_raising() -> None:
    malformed = _payload("tdx-daily-package", status="fallback")
    malformed["quality"]["observations"] = "not-a-number"
    provider = StubProvider(malformed)
    _plan, _fuyao_source, tdx_source, _eastmoney_source = _build_plan(
        provider,
        StubFuyao(_fuyao_result()),
    )

    result = tdx_source.acquire(
        SourceRequest(
            identity=IDENTITY,
            source_id=TDX_BREADTH_SOURCE_ID,
            capability_revision="tdx-r1",
            current_market_date=AS_OF,
            settled=True,
        )
    )

    assert isinstance(result, AcquisitionFailure)
    assert result.category is AcquisitionFailureCategory.CONTRACT
    assert "normalization failed" in result.message
