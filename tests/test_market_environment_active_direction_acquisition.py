from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping
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
from src.market_environment.infrastructure.providers.active_direction_acquisition import (
    EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID,
    EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
    TDX_ACTIVE_DIRECTION_SOURCE_ID,
    ActiveDirectionAcquisitionPlan,
    EastmoneyActiveDirectionDelayedAdapter,
    EastmoneyActiveDirectionPrimaryAdapter,
    TDXDerivedActiveDirectionAdapter,
)
from src.market_environment.infrastructure.providers.tdx.daily_package import (
    TDXStockUniverseClassification,
    TDXStockUniverseError,
)


AS_OF = date(2026, 9, 18)
HISTORICAL_AS_OF = date(2026, 9, 17)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
IDENTITY = DatasetDate("activeDirection", AS_OF)
STANDARD_WARNING = "仅有当日成交额、涨跌幅和收盘位置；20日成交放大、超额收益与连续2日确认尚未接入"


def _rows(count: int = 30) -> list[dict[str, Any]]:
    return [
        {
            "f12": f"300{index:03d}",
            "f14": f"样本{index}",
            "f2": 10.0,
            "f3": 1.0,
            "f6": float(30_000 - index),
            "f15": 11.0,
            "f16": 9.0,
            "f100": "算力" if index < 4 else "其他",
        }
        for index in range(count)
    ]


def _payload(
    source: str,
    *,
    status: str,
    as_of: date = AS_OF,
    observations: int = 30,
    warnings: tuple[str, ...] = (STANDARD_WARNING,),
    revision: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    top = [
        {
            "code": f"300{index:03d}",
            "name": f"样本{index}",
            "industry": "算力" if index < 4 else "其他",
            "changePct": 1.0,
            "amount": float(30_000 - index),
            "closePosition": 0.5,
        }
        for index in range(10)
    ]
    quality = {
        "dataset": "active-direction",
        "source": source,
        "provider": source,
        "status": status,
        "observations": observations,
        "asOf": as_of.isoformat(),
        "warning": "；".join(warnings) if warnings else None,
        "warnings": list(warnings),
        **dict(metadata or {}),
    }
    if revision is not None:
        quality["sourceRevision"] = revision
    return {
        "state": "candidate",
        "summary": "成交额前30中 算力 有 4 只，形成方向聚集线索，尚未完成连续性确认",
        "topStocks": top,
        "quality": quality,
    }


@dataclass
class StubProvider:
    primary: list[dict[str, Any]] | Exception = field(default_factory=_rows)
    delayed: list[dict[str, Any]] | Exception = field(default_factory=_rows)
    tdx: tuple[list[dict[str, Any]], dict[str, Any]] | Exception = field(
        default_factory=lambda: (
            _rows(),
            {
                "derived": True,
                "rankingMethod": "local-turnover-desc-identity-asc",
                "sourceRevision": "2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7",
                "industryMappingRevision": "industry-map-fixture-v1",
                "industryMappingCoverage": 1.0,
                "industryMappingCovered": 30,
                "industryMappingTotal": 30,
            },
        )
    )
    payload_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    eastmoney_calls: list[str] = field(default_factory=list)
    tdx_calls: list[date] = field(default_factory=list)
    build_calls: list[dict[str, Any]] = field(default_factory=list)

    _STOCK_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    _ACTIVE_DIRECTION_FALLBACK_URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
    )

    def _fetch_eastmoney_active_direction_rows(
        self,
        url: str,
    ) -> list[dict[str, Any]]:
        self.eastmoney_calls.append(url)
        value = self.primary if url == self._STOCK_SNAPSHOT_URL else self.delayed
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def _fetch_tdx_active_direction_rows(
        self,
        as_of: date,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.tdx_calls.append(as_of)
        if isinstance(self.tdx, Exception):
            raise self.tdx
        return copy.deepcopy(self.tdx)

    def _build_active_direction(
        self,
        rows: list[dict[str, Any]],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
        preserve_order: bool = False,
        quality_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.build_calls.append(
            {
                "rows": copy.deepcopy(rows),
                "as_of": as_of,
                "source": source,
                "status": status,
                "warnings": tuple(warnings),
                "preserve_order": preserve_order,
                "quality_metadata": copy.deepcopy(dict(quality_metadata or {})),
            }
        )
        if source in self.payload_overrides:
            return copy.deepcopy(self.payload_overrides[source])
        metadata = dict(quality_metadata or {})
        quality_warnings = [*warnings, STANDARD_WARNING]
        if metadata.get("derived") and metadata.get("industryMappingCoverage") != 1.0:
            quality_warnings.append(
                "行业映射覆盖不足：仅展示股票榜，不生成方向聚集结论"
            )
        revision = (
            str(metadata["sourceRevision"])
            if metadata.get("sourceRevision")
            else None
        )
        return _payload(
            source,
            status=status,
            as_of=as_of,
            warnings=tuple(quality_warnings),
            revision=revision,
            metadata={
                key: value
                for key, value in metadata.items()
                if key != "sourceRevision"
            },
        )


def _build_plan(
    provider: StubProvider,
    *,
    tdx_enabled: bool = False,
    market_today: date = AS_OF,
) -> tuple[
    ActiveDirectionAcquisitionPlan,
    EastmoneyActiveDirectionPrimaryAdapter,
    EastmoneyActiveDirectionDelayedAdapter,
    TDXDerivedActiveDirectionAdapter,
]:
    primary = EastmoneyActiveDirectionPrimaryAdapter(provider, now=lambda: NOW)
    delayed = EastmoneyActiveDirectionDelayedAdapter(provider, now=lambda: NOW)
    tdx = TDXDerivedActiveDirectionAdapter(provider, now=lambda: NOW)
    registry = SourceAdapterRegistry((primary, delayed, tdx))
    plan = ActiveDirectionAcquisitionPlan(
        adapters=registry,
        tdx_derived_is_enabled=lambda: tdx_enabled,
        market_today=lambda: market_today,
        is_settled=lambda requested: requested <= market_today,
    )
    return plan, primary, delayed, tdx


def test_primary_adapter_preserves_payload_source_quality_and_top_n() -> None:
    provider = StubProvider(
        delayed=AssertionError("delayed source must not run"),
        tdx=AssertionError("TDX must not run"),
    )
    plan, *_sources = _build_plan(provider)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    expected = provider._build_active_direction(
        _rows(),
        AS_OF,
        source="eastmoney-clist",
        status="partial",
        warnings=[],
    )
    assert outcome.candidate.payload == expected
    assert outcome.candidate.source == "eastmoney-clist"
    assert outcome.candidate.status == "partial"
    assert outcome.candidate.observations == 30
    assert outcome.candidate.warnings == (STANDARD_WARNING,)
    assert outcome.warning == STANDARD_WARNING
    assert len(outcome.candidate.payload["topStocks"]) == 10
    assert provider.eastmoney_calls == [provider._STOCK_SNAPSHOT_URL]
    assert provider.tdx_calls == []
    assert [attempt.role for attempt in outcome.attempts] == ["formal"]


def test_delayed_adapter_is_explicit_fallback_with_legacy_warnings() -> None:
    provider = StubProvider(
        primary=RuntimeError("primary disconnected"),
        tdx=AssertionError("TDX must not run after delayed success"),
    )
    plan, *_sources = _build_plan(provider)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist-delay"
    assert outcome.candidate.status == "fallback"
    assert outcome.candidate.warnings == (
        "东方财富容量方向主域不可用：primary disconnected",
        "已降级到东方财富延迟容量方向",
        STANDARD_WARNING,
    )
    assert outcome.warning == "；".join(outcome.candidate.warnings)
    assert provider.eastmoney_calls == [
        provider._STOCK_SNAPSHOT_URL,
        provider._ACTIVE_DIRECTION_FALLBACK_URL,
    ]
    assert provider.tdx_calls == []
    assert outcome.attempts[0].warning == (
        "东方财富容量方向主域不可用：primary disconnected"
    )
    assert [attempt.role for attempt in outcome.attempts] == ["formal", "fallback"]


def test_both_eastmoney_endpoints_fail_without_tdx_gate() -> None:
    provider = StubProvider(
        primary=RuntimeError("primary disconnected"),
        delayed=RuntimeError("delayed unavailable"),
        tdx=AssertionError("TDX gate is disabled"),
    )
    plan, *_sources = _build_plan(provider)

    outcome = plan.collect(IDENTITY)

    expected = (
        "东方财富容量方向不可用：主域失败：primary disconnected；"
        "延迟域失败：delayed unavailable"
    )
    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.candidate is None
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.NETWORK
    assert outcome.failure.message == expected
    assert outcome.warning == expected
    assert provider.tdx_calls == []


def test_invalid_delayed_candidate_retains_primary_and_delayed_failure_chain() -> None:
    provider = StubProvider(primary=RuntimeError("primary disconnected"))
    invalid = _payload(
        "eastmoney-clist-delay",
        status="fallback",
        observations=29,
    )
    provider.payload_overrides["eastmoney-clist-delay"] = invalid
    plan, *_sources = _build_plan(provider)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.INSUFFICIENT
    assert outcome.warning == (
        "东方财富容量方向不可用：主域失败：primary disconnected；延迟域失败："
        "active-direction requires at least 30 observations; received 29"
    )


def test_tdx_derived_gate_runs_only_after_both_eastmoney_sources_fail() -> None:
    provider = StubProvider(
        primary=RuntimeError("primary disconnected"),
        delayed=RuntimeError("delayed unavailable"),
    )
    plan, *_sources = _build_plan(provider, tdx_enabled=True)

    outcome = plan.collect(IDENTITY)

    eastmoney_warning = (
        "东方财富容量方向不可用：主域失败：primary disconnected；"
        "延迟域失败：delayed unavailable"
    )
    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert outcome.candidate.source == "tdx-daily-package-derived"
    assert outcome.candidate.status == "fallback-derived"
    assert outcome.candidate.observations == 30
    assert outcome.candidate.warnings == (
        eastmoney_warning,
        "已降级到通达信盘后包并进行本地成交额排序",
        STANDARD_WARNING,
    )
    assert outcome.candidate.quality is not None
    assert outcome.candidate.quality.extra["rankingMethod"] == (
        "local-turnover-desc-identity-asc"
    )
    assert provider.tdx_calls == [AS_OF]
    assert provider.build_calls[-1]["preserve_order"] is True
    assert [attempt.role for attempt in outcome.attempts] == [
        "formal",
        "fallback",
        "fallback",
    ]


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


def test_tdx_universe_failure_retains_full_failure_chain_and_metadata() -> None:
    provider = StubProvider(
        primary=RuntimeError("primary disconnected"),
        delayed=RuntimeError("delayed unavailable"),
        tdx=_universe_error(),
    )
    plan, *_sources = _build_plan(provider, tdx_enabled=True)

    outcome = plan.collect(IDENTITY)

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.candidate is None
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.INSUFFICIENT
    assert outcome.warning == (
        "东方财富容量方向不可用：主域失败：primary disconnected；"
        "延迟域失败：delayed unavailable；通达信普通 A 股 universe 不足："
        "retained sample is below minimum"
    )
    assert outcome.failure.provenance.attributes["stockUniversePolicyVersion"] == (
        "tdx-stock-universe-v1"
    )
    assert outcome.failure.provenance.attributes["stockUniverseUnclassifiedCount"] == 1


@pytest.mark.parametrize("invalid_case", ["sample", "field", "order"])
def test_adapter_rejects_invalid_top_n_contract(invalid_case: str) -> None:
    provider = StubProvider()
    invalid = _payload("eastmoney-clist", status="partial")
    if invalid_case == "sample":
        invalid["quality"]["observations"] = 29
    elif invalid_case == "field":
        invalid["topStocks"][0]["name"] = None
    else:
        invalid["topStocks"][1]["amount"] = 40_000.0
    provider.payload_overrides["eastmoney-clist"] = invalid
    _plan, primary, _delayed, _tdx = _build_plan(provider)

    result = primary.acquire(
        SourceRequest(
            identity=IDENTITY,
            source_id=EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
            capability_revision=primary.capability.revision,
            current_market_date=AS_OF,
            settled=True,
        )
    )

    assert isinstance(result, AcquisitionFailure)
    assert result.category is AcquisitionFailureCategory.INSUFFICIENT


def test_historical_plan_rejects_all_sources_before_io_and_has_no_fuyao_step() -> None:
    provider = StubProvider(
        primary=AssertionError("primary must not run"),
        delayed=AssertionError("delayed must not run"),
        tdx=AssertionError("TDX must not run"),
    )
    plan, *_sources = _build_plan(provider, tdx_enabled=True)

    outcome = plan.collect(DatasetDate("activeDirection", HISTORICAL_AS_OF))

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert outcome.warning == "该数据源仅提供最新市场快照，历史日期不使用当前数据回填"
    assert outcome.attempts == ()
    assert provider.eastmoney_calls == []
    assert provider.tdx_calls == []
    assert all("fuyao" not in step.adapter_id.lower() for step in plan.steps)


def test_each_adapter_rejects_historical_request_before_provider_io() -> None:
    provider = StubProvider(
        primary=AssertionError("primary must not run"),
        delayed=AssertionError("delayed must not run"),
        tdx=AssertionError("TDX must not run"),
    )
    _plan, primary, delayed, tdx = _build_plan(provider, tdx_enabled=True)
    identity = DatasetDate("activeDirection", HISTORICAL_AS_OF)
    requests = (
        (
            primary,
            SourceRequest(
                identity,
                EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
                current_market_date=AS_OF,
                settled=True,
            ),
        ),
        (
            delayed,
            SourceRequest(
                identity,
                EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID,
                params={"primary_error": "unused"},
                current_market_date=AS_OF,
                settled=True,
            ),
        ),
        (
            tdx,
            SourceRequest(
                identity,
                TDX_ACTIVE_DIRECTION_SOURCE_ID,
                params={"primary_warning": "unused"},
                current_market_date=AS_OF,
                settled=True,
            ),
        ),
    )

    for adapter, request in requests:
        result = adapter.acquire(request)
        assert isinstance(result, AcquisitionFailure)
        assert result.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert provider.eastmoney_calls == []
    assert provider.tdx_calls == []


def test_adapter_rejects_mismatched_quality_date() -> None:
    provider = StubProvider()
    provider.payload_overrides["eastmoney-clist"] = _payload(
        "eastmoney-clist",
        status="partial",
        as_of=HISTORICAL_AS_OF,
    )
    _plan, primary, _delayed, _tdx = _build_plan(provider)

    result = primary.acquire(
        SourceRequest(
            identity=IDENTITY,
            source_id=EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
            capability_revision=primary.capability.revision,
            current_market_date=AS_OF,
            settled=True,
        )
    )

    assert isinstance(result, AcquisitionFailure)
    assert result.category is AcquisitionFailureCategory.DATE_MISMATCH


def test_active_direction_adapters_expose_no_collection_or_persistence_ports() -> None:
    _plan, *sources = _build_plan(StubProvider())

    for source in sources:
        assert not any(
            hasattr(source, attribute)
            for attribute in ("store", "coordinator", "lease", "committer", "rebuild")
        )
    assert {source.source_id for source in sources} == {
        EASTMONEY_ACTIVE_DIRECTION_PRIMARY_SOURCE_ID,
        EASTMONEY_ACTIVE_DIRECTION_DELAYED_SOURCE_ID,
        TDX_ACTIVE_DIRECTION_SOURCE_ID,
    }
