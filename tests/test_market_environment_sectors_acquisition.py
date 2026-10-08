from __future__ import annotations

import copy
from datetime import date, datetime, timezone

import pytest

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.domain.models import (
    AcquisitionFailureCategory,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.providers.fuyao.market import FuyaoMarketResult
from src.market_environment.infrastructure.legacy.providers import MarketDataProvider
from src.market_environment.infrastructure.providers.sector_enrichment import (
    ENRICHMENT_MAPPING_REVISION,
)
from src.market_environment.infrastructure.providers.sectors_acquisition import (
    EASTMONEY_SECTOR_DELAYED_SOURCE_ID,
    EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID,
    EASTMONEY_SECTOR_PRIMARY_SOURCE_ID,
    FUYAO_SECTOR_SOURCE_ID,
    EastmoneySectorDelayedAdapter,
    EastmoneySectorEnrichmentAdapter,
    EastmoneySectorPrimaryAdapter,
    FuyaoSectorSourceAdapter,
    SectorsAcquisitionPlan,
)


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


def eastmoney_rows(*, change: float = 2.5) -> list[dict]:
    return [
        {
            "f12": "BK001",
            "f14": "电子",
            "f3": change,
            "f6": 1000,
            "f62": 300,
            "f184": 3.0,
            "f104": 20,
            "f105": 5,
            "f128": "领涨名称",
        }
    ]


def fuyao_result(*, revision: str = "r1", change: float = 2.5) -> FuyaoMarketResult:
    rows = [
        {
            "rank": 1,
            "code": "885001.TI",
            "name": "电子",
            "changePct": change,
            "amount": 1000,
            "mainNet": 999,
            "mainNetPct": 9.99,
            "upCount": 7,
            "downCount": 3,
            "leader": "扶摇领涨样本",
        },
        {
            "rank": 2,
            "code": "885002.TI",
            "name": "医药",
            "changePct": 1.2,
            "amount": 800,
            "mainNet": None,
            "mainNetPct": None,
            "upCount": None,
            "downCount": None,
            "leader": None,
        },
    ]
    quality = {
        "dataset": "industry-ranking",
        "source": "fuyao",
        "provider": "fuyao",
        "providerRevision": revision,
        "status": "fallback",
        "observations": len(rows),
        "asOf": AS_OF.isoformat(),
        "warning": "扶摇行业 provider fields unavailable",
        "warnings": ["扶摇行业 provider fields unavailable"],
    }
    return FuyaoMarketResult(
        payload={"rows": rows, "state": "当日排名已观测"},
        quality=quality,
        status="fallback",
        as_of=AS_OF,
        observations=len(rows),
        warnings=tuple(quality["warnings"]),
    )


class SectorProvider:
    def __init__(
        self,
        *,
        primary_error: Exception | None = None,
        delayed_error: Exception | None = None,
        enrichment_error: Exception | None = None,
    ) -> None:
        self.primary_error = primary_error
        self.delayed_error = delayed_error
        self.enrichment_error = enrichment_error
        self.calls: list[str] = []

    def _fetch_eastmoney_industries_from(self, url: str) -> list[dict]:
        if "push2delay" in url:
            self.calls.append("delayed")
            if self.delayed_error is not None:
                raise self.delayed_error
            return eastmoney_rows(change=1.2)
        self.calls.append("primary")
        if self.primary_error is not None:
            raise self.primary_error
        return eastmoney_rows()

    def _build_sectors(self, rows, as_of, *, source, status, warnings):
        normalized = [
            {
                "rank": index,
                "code": row.get("f12"),
                "name": row.get("f14"),
                "changePct": row.get("f3"),
                "amount": row.get("f6"),
                "mainNet": row.get("f62"),
                "mainNetPct": row.get("f184"),
                "upCount": row.get("f104"),
                "downCount": row.get("f105"),
                "leader": row.get("f128"),
            }
            for index, row in enumerate(rows[:10], start=1)
        ]
        quality_warnings = [
            *warnings,
            "仅反映当日行业排名和资金流，5日持续性、板块宽度与分歧承接尚未接入",
        ]
        return {
            "rows": normalized,
            "state": "当日排名已观测",
            "quality": {
                "dataset": "industry-ranking",
                "source": source,
                "provider": source,
                "status": status,
                "observations": len(rows),
                "asOf": as_of.isoformat(),
                "warning": "；".join(quality_warnings),
                "warnings": quality_warnings,
            },
        }

    def enrich_fuyao_sectors(self, payload, as_of, *, eligible):
        self.calls.append("enrichment")
        assert eligible is True
        if self.enrichment_error is not None:
            raise self.enrichment_error
        result = copy.deepcopy(payload)
        first, second = result["rows"]
        first.update(
            {
                "mainNet": -1,
                "mainNetPct": -1,
                "upCount": -1,
                "downCount": -1,
                "leader": "不得覆盖",
            }
        )
        second.update(
            {
                "mainNet": -25,
                "mainNetPct": -0.85,
                "upCount": 30,
                "downCount": 20,
                "leader": "医药样本",
            }
        )
        metadata = {
            "status": "enriched",
            "source": "eastmoney-dataapi",
            "provider": "eastmoney",
            "sameVendor": True,
            "endpoint": "https://data.eastmoney.com/dataapi/bkzj/getbkzj",
            "requestedFields": ["f3", "f6", "f62", "f104", "f105", "f128", "f184"],
            "mappingRevision": ENRICHMENT_MAPPING_REVISION,
            "matchMethod": "explicit-code-or-normalized-name",
            "sourceRows": 2,
            "baseRows": 2,
            "matchedRows": 2,
            "unmatchedRows": 0,
            "identityCoverage": 1.0,
            "fieldCoverage": {
                "mainNet": 1.0,
                "mainNetPct": 1.0,
                "upCount": 1.0,
                "downCount": 1.0,
                "leader": 1.0,
            },
            "fieldMatched": {
                "mainNet": 2,
                "mainNetPct": 2,
                "upCount": 2,
                "downCount": 2,
                "leader": 2,
            },
            "fieldFilled": {
                "mainNet": 1,
                "mainNetPct": 1,
                "upCount": 1,
                "downCount": 1,
                "leader": 1,
            },
            "dateEvidence": {
                "requested": as_of.isoformat(),
                "current": as_of.isoformat(),
                "eligible": True,
                "settled": True,
                "reason": "request-attempted",
            },
            "warnings": ["sector enrichment mapping coverage 2/2"],
        }
        quality = dict(result["quality"])
        quality["sectorEnrichment"] = metadata
        quality["warnings"] = [
            *quality.get("warnings", []),
            *metadata["warnings"],
        ]
        quality["warning"] = "；".join(quality["warnings"])
        result["quality"] = quality
        return result


class FuyaoClient:
    def __init__(
        self,
        result: FuyaoMarketResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or fuyao_result()
        self.error = error
        self.calls = 0

    def fetch_sectors(self, as_of):
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert as_of == AS_OF
        return self.result


def plan(
    provider: SectorProvider,
    fuyao: FuyaoClient,
    *,
    fuyao_enabled: bool = False,
    shadow_enabled: bool = False,
    enrichment_enabled: bool = False,
    settled: bool = True,
) -> SectorsAcquisitionPlan:
    adapters = SourceAdapterRegistry(
        (
            EastmoneySectorPrimaryAdapter(provider, now=lambda: NOW),
            EastmoneySectorDelayedAdapter(provider, now=lambda: NOW),
            FuyaoSectorSourceAdapter(fuyao, revision="r1", now=lambda: NOW),
            EastmoneySectorEnrichmentAdapter(
                provider,
                enabled=lambda: enrichment_enabled,
                now=lambda: NOW,
            ),
        )
    )
    return SectorsAcquisitionPlan(
        adapters,
        fuyao_is_enabled=lambda _dataset: fuyao_enabled,
        fuyao_gate_warning=lambda _dataset: "扶摇行业数据源未启用",
        fuyao_shadow_enabled=lambda _dataset: shadow_enabled,
        fuyao_revision=lambda _dataset: "r1",
        market_today=lambda: AS_OF,
        is_settled=lambda _as_of: settled,
    )


def test_primary_sector_candidate_stops_before_fallback_and_keeps_source():
    provider = SectorProvider()
    fuyao = FuyaoClient()

    outcome = plan(provider, fuyao).collect(DatasetDate("sectors", AS_OF))

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist"
    assert provider.calls == ["primary"]
    assert fuyao.calls == 0
    assert [(attempt.role, attempt.source) for attempt in outcome.attempts] == [
        ("formal", "eastmoney-clist")
    ]


def test_delayed_sector_candidate_retains_primary_failure_and_order():
    provider = SectorProvider(primary_error=RuntimeError("primary disconnected"))

    outcome = plan(provider, FuyaoClient()).collect(DatasetDate("sectors", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist-delay"
    assert provider.calls == ["primary", "delayed"]
    assert [attempt.role for attempt in outcome.attempts] == ["formal", "fallback"]
    assert "东方财富行业主域不可用：primary disconnected" in (outcome.warning or "")
    assert "已降级到东方财富延迟行业排名" in (outcome.warning or "")


@pytest.mark.parametrize("delayed", [False, True])
def test_eastmoney_plan_payload_matches_legacy_primary_and_delayed_fixture(
    monkeypatch,
    delayed,
):
    provider = MarketDataProvider()
    calls: list[str] = []

    def get_json(url, _params):
        calls.append(url)
        if delayed and "push2.eastmoney.com" in url:
            raise RuntimeError("fixture primary unavailable")
        return {"data": {"diff": eastmoney_rows(change=1.2 if delayed else 2.5)}}

    monkeypatch.setattr(provider.eastmoney, "get_json", get_json)
    legacy = provider.fetch_chapter01_sectors(AS_OF, allow_current_snapshot=True)
    legacy_calls = tuple(calls)
    calls.clear()

    outcome = plan(provider, FuyaoClient()).collect(DatasetDate("sectors", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.payload == legacy
    assert tuple(calls) == legacy_calls


def test_fuyao_fallback_and_dataapi_enrichment_are_ordered_and_fill_only():
    provider = SectorProvider(
        primary_error=RuntimeError("primary unavailable"),
        delayed_error=RuntimeError("delayed unavailable"),
    )
    fuyao = FuyaoClient()

    outcome = plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        enrichment_enabled=True,
    ).collect(DatasetDate("sectors", AS_OF))

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert outcome.candidate.source == "fuyao"
    assert outcome.candidate.source_revision == "r1"
    first, second = outcome.candidate.payload["rows"]
    assert {
        field: first[field]
        for field in ("mainNet", "mainNetPct", "upCount", "downCount", "leader")
    } == {
        "mainNet": 999,
        "mainNetPct": 9.99,
        "upCount": 7,
        "downCount": 3,
        "leader": "扶摇领涨样本",
    }
    assert {
        field: second[field]
        for field in ("mainNet", "mainNetPct", "upCount", "downCount", "leader")
    } == {
        "mainNet": -25,
        "mainNetPct": -0.85,
        "upCount": 30,
        "downCount": 20,
        "leader": "医药样本",
    }
    enrichment = outcome.candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["mappingRevision"] == ENRICHMENT_MAPPING_REVISION
    assert enrichment["identityCoverage"] == 1.0
    assert enrichment["fieldCoverage"]["leader"] == 1.0
    assert provider.calls == ["primary", "delayed", "enrichment"]
    assert fuyao.calls == 1
    assert [attempt.role for attempt in outcome.attempts] == [
        "formal",
        "fallback",
        "fallback",
        "enrichment",
    ]
    assert outcome.attempts[-1].source == EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID
    warning = outcome.warning or ""
    assert warning.index("扶摇行业 provider fields unavailable") < warning.index(
        "东方财富行业排名不可用"
    )
    assert warning.index("东方财富行业排名不可用") < warning.index(
        "扶摇 capability revision: r1"
    )
    assert "sector enrichment mapping coverage 2/2" in warning


def test_default_disabled_enrichment_records_metadata_without_provider_call():
    provider = SectorProvider(
        primary_error=RuntimeError("primary unavailable"),
        delayed_error=RuntimeError("delayed unavailable"),
    )

    outcome = plan(provider, FuyaoClient(), fuyao_enabled=True).collect(
        DatasetDate("sectors", AS_OF)
    )

    assert outcome.candidate is not None
    assert provider.calls == ["primary", "delayed"]
    enrichment = outcome.candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "disabled"
    assert enrichment["mappingRevision"] == ENRICHMENT_MAPPING_REVISION
    assert enrichment["dateEvidence"]["reason"] == "feature-disabled"
    assert outcome.attempts[-1].role == "enrichment"


def test_unsettled_fuyao_candidate_skips_enrichment_without_call():
    provider = SectorProvider(
        primary_error=RuntimeError("primary unavailable"),
        delayed_error=RuntimeError("delayed unavailable"),
    )

    outcome = plan(
        provider,
        FuyaoClient(),
        fuyao_enabled=True,
        enrichment_enabled=True,
        settled=False,
    ).collect(DatasetDate("sectors", AS_OF))

    assert outcome.candidate is not None
    assert provider.calls == ["primary", "delayed"]
    enrichment = outcome.candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "skipped"
    assert enrichment["mappingRevision"] is None
    assert enrichment["dateEvidence"]["eligible"] is False
    assert enrichment["dateEvidence"]["settled"] is False
    assert enrichment["dateEvidence"]["reason"] == (
        "东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用"
    )
    assert [attempt.role for attempt in outcome.attempts] == [
        "formal",
        "fallback",
        "fallback",
    ]


def test_enrichment_failure_preserves_fuyao_base_and_classifies_attempt():
    provider = SectorProvider(
        primary_error=RuntimeError("primary unavailable"),
        delayed_error=RuntimeError("delayed unavailable"),
        enrichment_error=RuntimeError("fixture dataapi unavailable"),
    )

    outcome = plan(
        provider,
        FuyaoClient(),
        fuyao_enabled=True,
        enrichment_enabled=True,
    ).collect(DatasetDate("sectors", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.source == "fuyao"
    assert outcome.candidate.payload["rows"][1]["mainNet"] is None
    enrichment = outcome.candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "failed"
    assert "fixture dataapi unavailable" in enrichment["warnings"][0]
    assert outcome.attempts[-1].role == "enrichment"
    assert outcome.attempts[-1].category is AcquisitionFailureCategory.NETWORK
    assert "fixture dataapi unavailable" in (outcome.warning or "")


def test_fuyao_gate_failure_stops_before_fallback_request():
    provider = SectorProvider(
        primary_error=RuntimeError("primary unavailable"),
        delayed_error=RuntimeError("delayed unavailable"),
    )
    fuyao = FuyaoClient()

    outcome = plan(provider, fuyao).collect(DatasetDate("sectors", AS_OF))

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.candidate is None
    assert fuyao.calls == 0
    assert "东方财富行业排名不可用" in (outcome.warning or "")
    assert "扶摇行业数据源未启用" in (outcome.warning or "")


def test_historical_sector_request_is_rejected_before_any_source_call():
    provider = SectorProvider()
    fuyao = FuyaoClient()

    outcome = plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        shadow_enabled=True,
        enrichment_enabled=True,
    ).collect(DatasetDate("sectors", date(2026, 9, 17)))

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert outcome.failure is not None
    assert outcome.failure.category is AcquisitionFailureCategory.DATE_MISMATCH
    assert outcome.attempts == ()
    assert provider.calls == []
    assert fuyao.calls == 0


def test_shadow_difference_never_changes_formal_sector_candidate():
    provider = SectorProvider()
    fuyao = FuyaoClient(fuyao_result(change=-3.0))

    outcome = plan(
        provider,
        fuyao,
        fuyao_enabled=True,
        shadow_enabled=True,
    ).collect(DatasetDate("sectors", AS_OF))

    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist"
    assert outcome.candidate.payload["rows"][0]["code"] == "BK001"
    assert outcome.candidate.payload["rows"][0]["changePct"] == 2.5
    assert fuyao.calls == 1
    assert [attempt.role for attempt in outcome.attempts] == ["formal", "shadow"]
    comparison = outcome.attempts[-1].provenance.attributes["comparison"]
    assert comparison["dataset"] == "sectors"


def test_source_ids_and_plan_steps_keep_fallback_shadow_and_enrichment_roles_distinct():
    sector_plan = plan(SectorProvider(), FuyaoClient())

    assert [(step.adapter_id, step.role) for step in sector_plan.steps] == [
        (EASTMONEY_SECTOR_PRIMARY_SOURCE_ID, "formal"),
        (EASTMONEY_SECTOR_DELAYED_SOURCE_ID, "fallback"),
        (FUYAO_SECTOR_SOURCE_ID, "fallback"),
        (EASTMONEY_SECTOR_ENRICHMENT_SOURCE_ID, "enrichment"),
        (FUYAO_SECTOR_SOURCE_ID, "shadow"),
    ]
    enrichment_step = sector_plan.steps[3]
    assert enrichment_step.approved_fields == (
        "mainNet",
        "mainNetPct",
        "upCount",
        "downCount",
        "leader",
    )
