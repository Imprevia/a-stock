from datetime import date, datetime
import copy
import json
from dataclasses import dataclass

import pytest

from src.market_environment.application.collection import SourceAdapterRegistry
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import CollectionTaskState
from src.market_environment.fuyao_config import (
    FUYAO_SECTORS_RUNTIME_REVISION,
    FuyaoCollectionConfig,
)
from src.market_environment.fuyao_market import FuyaoMarketResult
from src.market_environment.infrastructure.providers.fuyao_policy import (
    FuyaoCollectionPolicy,
)
from src.market_environment.infrastructure.providers.sectors_acquisition import (
    EastmoneySectorDelayedAdapter,
    EastmoneySectorEnrichmentAdapter,
    EastmoneySectorPrimaryAdapter,
    FuyaoSectorSourceAdapter,
    SectorsAcquisitionPlan,
)
from src.market_environment.provider_capability import ProviderCapabilityReport
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore
from src.market_environment.refresh import MARKET_TIME_ZONE, settlement_time
from src.market_environment.sector_enrichment import ENRICHMENT_MAPPING_REVISION
from src.market_environment import cli as market_cli
from src.market_environment.cli import main as cli_main


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)


@dataclass(frozen=True)
class LegacyDatasetDate:
    """Retired acquisition identity deliberately excluded from the public enum."""

    dataset: str
    as_of: date


class LegacySourceAdapterRegistry(SourceAdapterRegistry):
    """Validate the retired plan without reopening the public registry."""

    def validate_references(self, plans) -> None:
        for candidate in plans:
            assert candidate.dataset_id == "sectors"
            for step in candidate.steps:
                adapter = self.get(step.adapter_id)
                assert adapter.capability.available
                if step.capability_revision is not None:
                    assert step.capability_revision == adapter.capability.revision


class ChapterProvider:
    def __init__(self):
        self.sector_calls = 0

    def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
        return {
            "advanceCount": 2, "declineCount": 1, "flatCount": 0,
            "validCount": 3, "advanceRatio": 0.66, "medianReturn": 1.0,
            "state": "多数上涨",
            "quality": {"status": "ok", "source": "fixture", "observations": 3, "asOf": as_of.isoformat(), "warnings": []},
        }

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
        return {"rows": [], "state": "已观测", "quality": {"status": "ok", "source": "fixture", "observations": 0, "asOf": as_of.isoformat(), "warnings": []}}

    def fetch_chapter01_active_direction(self, as_of, *, allow_current_snapshot):
        return {"topStocks": [], "state": "candidate", "quality": {"status": "ok", "source": "fixture", "observations": 0, "asOf": as_of.isoformat(), "warnings": []}}

    def fetch_chapter01_limits(self, as_of):
        return {"limitUpCount": 1, "limitDownCount": 0, "failedLimitUpCount": 0, "quality": {"status": "ok", "source": "fixture", "observations": 1, "asOf": as_of.isoformat(), "warnings": []}}

    def _fetch_eastmoney_industries_from(self, url):
        self.sector_calls += 1
        return [
            {
                "f12": "BK001",
                "f14": "电子",
                "f3": 2.5,
                "f6": 1000.0,
                "f62": 88.0,
                "f184": 1.25,
                "f104": 8,
                "f105": 2,
                "f128": "样本股",
            }
        ]

    def _build_sectors(self, rows, as_of, *, source, status, warnings):
        normalized = [
            {
                "rank": index,
                "code": row["f12"],
                "name": row["f14"],
                "changePct": row["f3"],
                "amount": row["f6"],
                "mainNet": row["f62"],
                "mainNetPct": row["f184"],
                "upCount": row["f104"],
                "downCount": row["f105"],
                "leader": row["f128"],
            }
            for index, row in enumerate(rows, start=1)
        ]
        return {
            "rows": normalized,
            "state": "当日排名已观测",
            "quality": {
                "dataset": "industry-ranking",
                "source": source,
                "provider": "eastmoney",
                "status": status,
                "observations": len(normalized),
                "asOf": as_of.isoformat(),
                "warning": "；".join(warnings) if warnings else None,
                "warnings": list(warnings),
            },
        }


class FailingFuyaoAdapter:
    def fetch_breadth(self, as_of):
        raise RuntimeError("fixture Fuyao unavailable")


class FailingSectorProvider(ChapterProvider):
    def __init__(self):
        super().__init__()

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
        self.sector_calls += 1
        raise RuntimeError("Eastmoney primary disconnected; delayed unavailable")

    def _fetch_eastmoney_industries_from(self, url):
        self.sector_calls += 1
        raise RuntimeError("Eastmoney primary disconnected; delayed unavailable")


class EnrichingSectorProvider(FailingSectorProvider):
    def __init__(self, *, fail_enrichment: bool = False):
        super().__init__()
        self.fail_enrichment = fail_enrichment
        self.enrichment_calls = []

    def enrich_fuyao_sectors(self, payload, as_of, *, eligible):
        self.enrichment_calls.append((as_of, eligible))
        if self.fail_enrichment:
            raise RuntimeError("fixture dataapi unavailable")
        result = copy.deepcopy(payload)
        result["rows"][0].update(
            {
                "mainNet": 88.0,
                "mainNetPct": 1.25,
                "upCount": 8,
                "downCount": 2,
                "leader": "样本股",
            }
        )
        result["quality"]["sectorEnrichment"] = {
            "status": "complete",
            "source": "eastmoney-dataapi",
            "provider": "eastmoney",
            "sameVendor": True,
            "endpoint": "https://data.eastmoney.com/dataapi/bkzj/getbkzj",
            "requestedFields": ["f3", "f6", "f62", "f104", "f105", "f128", "f184"],
            "mappingRevision": ENRICHMENT_MAPPING_REVISION,
            "matchMethod": "normalized-name",
            "sourceRows": 1,
            "baseRows": 1,
            "matchedRows": 1,
            "unmatchedRows": 0,
            "identityCoverage": 1.0,
            "fieldCoverage": {
                "mainNet": 1.0,
                "mainNetPct": 1.0,
                "upCount": 1.0,
                "downCount": 1.0,
                "leader": 1.0,
            },
            "dateEvidence": {
                "requested": as_of.isoformat(),
                "current": as_of.isoformat(),
                "eligible": True,
                "settled": True,
                "reason": "current Shanghai market date after settlement",
            },
            "warnings": ["东方财富同供应商字段补充，不构成独立 provider 交叉确认"],
        }
        result["quality"]["warnings"] = [
            *result["quality"].get("warnings", []),
            *result["quality"]["sectorEnrichment"]["warnings"],
        ]
        return result


class FuyaoSectorAdapter:
    def __init__(self, *, fail=False, revision=FUYAO_SECTORS_RUNTIME_REVISION):
        self.calls = 0
        self.fail = fail
        self.revision = revision

    def fetch_sectors(self, as_of):
        self.calls += 1
        if self.fail:
            raise RuntimeError("fixture Fuyao unavailable")
        return FuyaoMarketResult(
            payload={
                "rows": [
                    {
                        "rank": 1,
                        "code": "881101.TI",
                        "name": "电子",
                        "changePct": 2.5,
                        "amount": 1000.0,
                        "mainNet": None,
                        "mainNetPct": None,
                        "upCount": None,
                        "downCount": None,
                        "leader": None,
                    }
                ],
                "state": "当日排名已观测",
            },
            quality={
                "dataset": "industry-ranking",
                "source": "fuyao",
                "provider": "fuyao",
                "providerRevision": self.revision,
                "status": "fallback",
                "observations": 1,
                "asOf": as_of.isoformat(),
                "warning": "扶摇行业 provider fields unavailable: mainNet, upCount, leader",
                "warnings": ["扶摇行业 provider fields unavailable: mainNet, upCount, leader"],
            },
            status="fallback",
            as_of=as_of,
            observations=1,
            warnings=("扶摇行业 provider fields unavailable: mainNet, upCount, leader",),
        )


def eligible_report(
    dataset: str,
    *,
    revision: str | None = None,
) -> ProviderCapabilityReport:
    selected_revision = revision or (
        FUYAO_SECTORS_RUNTIME_REVISION if dataset == "sectors" else "r1"
    )
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset=dataset,
        revision=selected_revision,
        status="eligible",
    )


def legacy_sector_plan(
    provider,
    adapter,
    store,
    config,
    *,
    now=NOW,
    enrichment_enabled=False,
):
    policy = FuyaoCollectionPolicy(config, store)
    adapters = LegacySourceAdapterRegistry(
        (
            EastmoneySectorPrimaryAdapter(provider, now=lambda: now),
            EastmoneySectorDelayedAdapter(provider, now=lambda: now),
            FuyaoSectorSourceAdapter(
                adapter,
                revision=policy.revision("sectors"),
                now=lambda: now,
            ),
            EastmoneySectorEnrichmentAdapter(
                provider,
                enabled=lambda: enrichment_enabled,
                now=lambda: now,
            ),
        )
    )
    local_now = now.astimezone(MARKET_TIME_ZONE)
    return SectorsAcquisitionPlan(
        adapters,
        fuyao_is_enabled=policy.is_enabled,
        fuyao_gate_warning=policy.gate_warning,
        fuyao_shadow_enabled=policy.shadow_enabled,
        fuyao_revision=policy.revision,
        market_today=lambda: local_now.date(),
        is_settled=lambda as_of: (
            as_of == local_now.date()
            and local_now.time().replace(tzinfo=None) >= settlement_time()
        ),
    )


def collect_legacy_sectors(plan):
    return plan.collect(LegacyDatasetDate("sectors", AS_OF))


def test_enabled_dataset_is_rejected_before_lease_when_revision_missing(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    config = FuyaoCollectionConfig.from_environment({
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED": "1",
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_APPROVED_REVISION": "r1",
    })
    result = CollectionCoordinator(ChapterProvider(), store, now=lambda: NOW, fuyao_config=config).start_run(AS_OF, ["breadth"])
    task = result.tasks[0]
    assert task.status == "failed-missing"
    assert "capability revision" in (task.warning or "")
    assert store.active_collection_task("breadth", AS_OF, now=NOW) is None


def test_enabled_dataset_falls_back_and_retains_warning(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("breadth"))
    config = FuyaoCollectionConfig.from_environment({
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED": "1",
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_APPROVED_REVISION": "r1",
    })
    result = CollectionCoordinator(
        ChapterProvider(), store, now=lambda: NOW, fuyao_config=config, fuyao_adapter=FailingFuyaoAdapter(), rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["breadth"])
    assert result.run.status == "success"
    assert result.tasks[0].source == "fixture"
    assert "扶摇采集失败" in (result.tasks[0].warning or "")
    assert store.get("breadth", AS_OF).source == "fixture"


def test_public_coordinator_rejects_retired_sectors_before_provider_io(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = ChapterProvider()
    adapter = FuyaoSectorAdapter()
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
        rebuild_aggregate=lambda _date: None,
    )

    with pytest.raises(
        ValueError,
        match="unsupported collection dataset: sectors; use industry-ranking",
    ):
        coordinator.collect(AS_OF, ["sectors"])

    assert provider.sector_calls == 0
    assert adapter.calls == 0


def test_retired_sector_plan_shadow_failure_does_not_block_eastmoney_result(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED": "1",
        }
    )
    provider = ChapterProvider()
    adapter = FuyaoSectorAdapter(fail=True)
    outcome = collect_legacy_sectors(
        legacy_sector_plan(provider, adapter, store, config)
    )

    assert outcome.state is CollectionTaskState.PARTIAL
    assert outcome.candidate is not None
    assert outcome.candidate.source == "eastmoney-clist"
    assert provider.sector_calls == 1
    assert adapter.calls == 1
    assert outcome.attempts[-1].role == "shadow"
    assert "shadow 不可用" in (outcome.warning or "")


def test_retired_sector_plan_uses_approved_fuyao_after_eastmoney_chain_fails(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = FailingSectorProvider()
    adapter = FuyaoSectorAdapter()
    outcome = collect_legacy_sectors(
        legacy_sector_plan(provider, adapter, store, config)
    )
    candidate = outcome.candidate

    assert outcome.state is CollectionTaskState.PARTIAL
    assert candidate is not None and candidate.source == "fuyao"
    assert adapter.calls == 1
    assert candidate.payload["rows"][0]["mainNet"] is None
    assert "东方财富行业排名不可用" in (outcome.warning or "")
    assert "扶摇行业 provider fields unavailable" in (outcome.warning or "")
    assert f"capability revision: {FUYAO_SECTORS_RUNTIME_REVISION}" in (outcome.warning or "")
    warning = outcome.warning or ""
    assert warning.index("扶摇行业 provider fields unavailable") < warning.index("东方财富行业排名不可用")
    assert warning.index("东方财富行业排名不可用") < warning.index(
        f"capability revision: {FUYAO_SECTORS_RUNTIME_REVISION}"
    )
    assert candidate.source_revision == FUYAO_SECTORS_RUNTIME_REVISION


def test_retired_sector_v2_fallback_preserves_exact_date_and_partial_field_contract(tmp_path):
    revision = "fuyao-market-v2"
    store = SnapshotStore(tmp_path / "snapshots-v2.sqlite3")
    store.put_capability_report(eligible_report("sectors", revision=revision))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": revision,
        }
    )
    provider = FailingSectorProvider()
    adapter = FuyaoSectorAdapter(revision=revision)

    outcome = collect_legacy_sectors(
        legacy_sector_plan(provider, adapter, store, config)
    )
    candidate = outcome.candidate

    assert outcome.state is CollectionTaskState.PARTIAL
    assert candidate is not None and candidate.source == "fuyao"
    assert candidate.source_revision == revision
    assert adapter.calls == 1
    assert candidate.identity.as_of == AS_OF
    assert candidate.payload["quality"]["asOf"] == AS_OF.isoformat()
    row = candidate.payload["rows"][0]
    assert {field: row[field] for field in ("code", "name", "changePct", "amount")} == {
        "code": "881101.TI",
        "name": "电子",
        "changePct": 2.5,
        "amount": 1000.0,
    }
    assert all(
        row[field] is None
        for field in ("mainNet", "mainNetPct", "upCount", "downCount", "leader")
    )
    warning = outcome.warning or ""
    assert warning.index("扶摇行业 provider fields unavailable") < warning.index(
        "东方财富行业排名不可用"
    )
    assert warning.index("东方财富行业排名不可用") < warning.index(
        f"capability revision: {revision}"
    )


def test_retired_fuyao_sector_enrichment_is_kept_in_candidate_metadata(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = EnrichingSectorProvider()

    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            provider,
            FuyaoSectorAdapter(),
            store,
            config,
            enrichment_enabled=True,
        )
    )
    candidate = outcome.candidate

    assert outcome.state is CollectionTaskState.PARTIAL
    assert provider.enrichment_calls == [(AS_OF, True)]
    assert candidate is not None and candidate.source == "fuyao"
    assert candidate.payload["rows"][0]["mainNet"] == 88.0
    assert candidate.payload["rows"][0]["leader"] == "样本股"
    enrichment = candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["sameVendor"] is True
    assert enrichment["mappingRevision"] == "fuyao-eastmoney-sector-map-v1"
    assert enrichment["matchMethod"] == "normalized-name"
    assert enrichment["matchedRows"] == 1
    assert enrichment["identityCoverage"] == 1.0
    assert candidate.quality is not None
    assert candidate.quality.extra["sectorEnrichment"] == enrichment


def test_retired_sector_enrichment_failure_preserves_base_and_not_supported_sibling(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = EnrichingSectorProvider(fail_enrichment=True)

    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            provider,
            FuyaoSectorAdapter(),
            store,
            config,
            enrichment_enabled=True,
        )
    )
    candidate = outcome.candidate
    sibling = CollectionCoordinator(
        provider,
        store,
        now=lambda: NOW,
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["breadth"])

    assert outcome.state is CollectionTaskState.PARTIAL
    assert candidate is not None
    assert candidate.payload["rows"][0]["mainNet"] is None
    assert candidate.payload["quality"]["sectorEnrichment"]["status"] == "failed"
    assert "fixture dataapi unavailable" in (outcome.warning or "")
    assert sibling.tasks[0].status == "success"


def test_retired_sector_enrichment_is_skipped_before_settlement_without_provider_call(tmp_path):
    before_settlement = datetime(2026, 9, 18, 14, 30, tzinfo=MARKET_TIME_ZONE)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = EnrichingSectorProvider()

    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            provider,
            FuyaoSectorAdapter(),
            store,
            config,
            now=before_settlement,
            enrichment_enabled=True,
        )
    )
    candidate = outcome.candidate

    assert outcome.state is CollectionTaskState.PARTIAL
    assert provider.enrichment_calls == []
    assert candidate is not None
    enrichment = candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "skipped"
    assert enrichment["dateEvidence"]["eligible"] is False


def test_retired_sector_plan_rejects_historical_date_without_provider_call(tmp_path):
    historical_now = datetime(2026, 9, 21, 16, 0, tzinfo=MARKET_TIME_ZONE)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = EnrichingSectorProvider()
    adapter = FuyaoSectorAdapter()

    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            provider,
            adapter,
            store,
            config,
            now=historical_now,
            enrichment_enabled=True,
        )
    )

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert provider.enrichment_calls == []
    assert provider.sector_calls == 0
    assert adapter.calls == 0
    assert "历史日期不使用当前数据回填" in (outcome.warning or "")


@pytest.mark.parametrize(
    ("clock_time", "expected_calls", "expected_status", "expected_reason"),
    [
        ("15:09", 0, "skipped", "东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用"),
        ("15:10", 1, "complete", "current Shanghai market date after settlement"),
    ],
)
def test_retired_sector_enrichment_settlement_boundary_is_inclusive(
    tmp_path,
    clock_time,
    expected_calls,
    expected_status,
    expected_reason,
):
    hour, minute = (int(part) for part in clock_time.split(":"))
    at_boundary = datetime(2026, 9, 18, hour, minute, tzinfo=MARKET_TIME_ZONE)
    store = SnapshotStore(tmp_path / f"snapshots-{clock_time.replace(':', '')}.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    provider = EnrichingSectorProvider()

    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            provider,
            FuyaoSectorAdapter(),
            store,
            config,
            now=at_boundary,
            enrichment_enabled=True,
        )
    )
    candidate = outcome.candidate

    assert provider.enrichment_calls == ([(AS_OF, True)] if expected_calls else [])
    assert candidate is not None
    enrichment = candidate.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == expected_status
    assert enrichment["dateEvidence"]["reason"] == expected_reason
    assert enrichment["dateEvidence"]["current"] == AS_OF.isoformat()
    assert enrichment["dateEvidence"]["settled"] is (expected_calls == 1)


def test_retired_sectors_capability_gate_blocks_fuyao_after_eastmoney_failure(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    adapter = FuyaoSectorAdapter()
    outcome = collect_legacy_sectors(
        legacy_sector_plan(FailingSectorProvider(), adapter, store, config)
    )

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert adapter.calls == 0
    assert "缺少批准报告" in (outcome.warning or "")


@pytest.mark.parametrize("revision", ["fuyao-market-v1", "unknown-revision"])
def test_retired_sectors_matching_eligible_non_v2_report_still_blocks_fuyao_io(
    tmp_path,
    revision,
):
    store = SnapshotStore(tmp_path / f"snapshots-{revision}.sqlite3")
    store.put_capability_report(eligible_report("sectors", revision=revision))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": revision,
        }
    )
    adapter = FuyaoSectorAdapter(revision=revision)

    outcome = collect_legacy_sectors(
        legacy_sector_plan(FailingSectorProvider(), adapter, store, config)
    )

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert adapter.calls == 0
    warning = outcome.warning or ""
    assert f"仅接受 capability revision {FUYAO_SECTORS_RUNTIME_REVISION}" in warning
    assert revision in warning


@pytest.mark.parametrize(
    ("report", "expected_warning"),
    [
        (ProviderCapabilityReport(provider="fuyao", dataset="sectors", revision=FUYAO_SECTORS_RUNTIME_REVISION, status="ineligible"), "状态为 ineligible"),
        (ProviderCapabilityReport(provider="fuyao", dataset="sectors", revision="r2", status="eligible"), "revision 不匹配"),
    ],
)
def test_retired_sectors_capability_status_or_revision_mismatch_blocks_provider(tmp_path, report, expected_warning):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(report)
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    adapter = FuyaoSectorAdapter()
    outcome = collect_legacy_sectors(
        legacy_sector_plan(FailingSectorProvider(), adapter, store, config)
    )

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert adapter.calls == 0
    assert expected_warning in (outcome.warning or "")


def test_retired_sectors_failure_leaves_same_date_audit_snapshot_unchanged(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=AS_OF,
            payload={"rows": [], "quality": {"status": "fallback", "asOf": AS_OF.isoformat()}},
            source="old-fuyao",
            status="fallback",
            observations=0,
            warnings=(),
            fetched_at=NOW,
            settled=True,
        )
    )
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": FUYAO_SECTORS_RUNTIME_REVISION,
        }
    )
    before = store.get("sectors", AS_OF)
    outcome = collect_legacy_sectors(
        legacy_sector_plan(
            FailingSectorProvider(),
            FuyaoSectorAdapter(fail=True),
            store,
            config,
        )
    )
    after = store.get("sectors", AS_OF)

    assert outcome.state is CollectionTaskState.FAILED_MISSING
    assert "扶摇行业 fallback 不可用" in (outcome.warning or "")
    assert before is not None and after is not None
    assert after.checksum == before.checksum
    assert after.source == "old-fuyao"


def test_offline_capability_probe_uses_fixture_only(monkeypatch, tmp_path, capsys):
    def fail_builder(*args, **kwargs):
        raise AssertionError("offline capability fixture must not construct runtime dependencies")

    monkeypatch.setattr(market_cli, "build_cli_container", fail_builder)
    fixture = "tests/fixtures/market-environment/fuyao-market-data.json"
    output = tmp_path / "capability.json"
    assert cli_main(["fuyao", "capability-probe", "--fixture", fixture, "--as-of", AS_OF.isoformat(), "--output", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "fuyao"
    assert {item["dataset"] for item in payload["reports"]} == {"core", "breadth", "sectors", "activeDirection"}
    assert "fixture-key" not in output.read_text(encoding="utf-8")


def test_real_probe_dispatches_to_fuyao_and_persists_redacted_reports(monkeypatch, tmp_path, capsys):
    class EmptyQuoteProvider:
        def fetch_quotes(self, specs):
            return {}

    class ProbeAdapter:
        def __init__(self, client):
            assert client is not None

        def _result(self, dataset, status="ok"):
            quality = {
                "status": status,
                "provider": "fuyao",
                "providerRevision": "fuyao-market-v1",
                "asOf": AS_OF.isoformat(),
                "fieldCoverage": {"fields": ["code", "name"]},
            }
            return FuyaoMarketResult(
                payload={"rows": []},
                quality=quality,
                status=status,
                as_of=AS_OF,
                observations=1,
                warnings=(),
            )

        def fetch_breadth(self, as_of):
            assert as_of == AS_OF
            return self._result("breadth")

        def fetch_core(self, as_of):
            assert as_of == AS_OF
            result = self._result("core")
            return {code: result for code in ("sh000001", "sz399001", "sz399006", "sh000300", "sh000905")}

        def fetch_active_direction(self, as_of):
            assert as_of == AS_OF
            return self._result("activeDirection")

        def fetch_sectors(self, as_of):
            assert as_of == AS_OF
            return self._result("sectors", status="fallback")

    monkeypatch.setenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "probe-secret")
    monkeypatch.setattr(market_cli, "MarketDataProvider", EmptyQuoteProvider)
    monkeypatch.setattr(market_cli, "FuyaoMarketAdapter", ProbeAdapter)
    monkeypatch.setattr(market_cli, "FuyaoMarketClient", lambda: object())
    output = tmp_path / "real-probe.json"
    store_path = tmp_path / "real-probe.sqlite3"

    exit_code = cli_main(
        [
            "fuyao",
            "real-probe",
            "--as-of",
            AS_OF.isoformat(),
            "--output",
            str(output),
            "--path",
            str(store_path),
            "--allow-real",
        ],
        now=lambda: NOW,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "fuyao"
    assert {item["dataset"] for item in payload["reports"]} == {"core", "breadth", "activeDirection", "sectors"}
    assert payload["reports"][-1]["revision"] == "fuyao-market-v1"
    assert "probe-secret" not in output.read_text(encoding="utf-8")
    store = SnapshotStore(store_path)
    assert store.get_capability_report("fuyao", "sectors", "fuyao-market-v1") is not None


def test_current_real_probe_passes_independent_quotes_to_core(monkeypatch, tmp_path, capsys):
    current_as_of = date(2026, 9, 29)
    current_now = datetime(2026, 9, 29, 15, 10, tzinfo=MARKET_TIME_ZONE)
    quote_calls = []
    core_quote_args = []

    class QuoteProvider:
        def fetch_quotes(self, specs):
            quote_calls.append(tuple(spec.code for spec in specs))
            return {spec.code: {"price": 100.0} for spec in specs}

    class CurrentProbeAdapter:
        source_revision = "fuyao-market-v2"

        def __init__(self, client):
            assert client is not None

        def _result(self, dataset):
            return FuyaoMarketResult(
                payload={"rows": []},
                quality={
                    "status": "ok",
                    "provider": "fuyao",
                    "providerRevision": self.source_revision,
                    "asOf": current_as_of.isoformat(),
                },
                status="ok",
                as_of=current_as_of,
                observations=1,
                warnings=(),
            )

        def fetch_core(self, as_of, *, quotes_by_code=None):
            assert as_of == current_as_of
            core_quote_args.append(quotes_by_code)
            result = self._result("core")
            return {code: result for code in ("sh000001", "sz399001", "sz399006", "sh000300", "sh000905")}

        def fetch_breadth(self, as_of):
            return self._result("breadth")

        def fetch_active_direction(self, as_of):
            return self._result("activeDirection")

        def fetch_sectors(self, as_of):
            return self._result("sectors")

    monkeypatch.setenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "probe-secret")
    monkeypatch.setattr(market_cli, "MarketDataProvider", QuoteProvider)
    monkeypatch.setattr(market_cli, "FuyaoMarketAdapter", CurrentProbeAdapter)
    monkeypatch.setattr(market_cli, "FuyaoMarketClient", lambda: object())
    output = tmp_path / "current-real-probe.json"
    store_path = tmp_path / "current-real-probe.sqlite3"

    exit_code = cli_main(
        [
            "fuyao",
            "real-probe",
            "--as-of",
            current_as_of.isoformat(),
            "--output",
            str(output),
            "--path",
            str(store_path),
            "--allow-real",
        ],
        now=lambda: current_now,
    )

    assert exit_code == 0
    assert quote_calls == [("sh000001", "sz399001", "sz399006", "sh000300", "sh000905")]
    assert core_quote_args and set(core_quote_args[0]) == set(quote_calls[0])
    assert "probe-secret" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("requested", "current", "expected_error"),
    (
        (
            date(2026, 9, 18),
            datetime(2026, 9, 18, 15, 9, tzinfo=MARKET_TIME_ZONE),
            "after the configured settlement time",
        ),
        (
            date(2026, 9, 17),
            datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE),
            "current effective Shanghai market date",
        ),
        (
            date(2026, 9, 18),
            datetime(2026, 9, 19, 16, 0, tzinfo=MARKET_TIME_ZONE),
            "Shanghai market weekday",
        ),
    ),
)
def test_real_probe_rejects_invalid_market_boundary_before_io(
    monkeypatch,
    tmp_path,
    capsys,
    requested,
    current,
    expected_error,
):
    provider_construction = []

    def fail_provider(*args, **kwargs):
        provider_construction.append((args, kwargs))
        raise AssertionError("provider construction must remain zero")

    monkeypatch.setenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "probe-secret")
    monkeypatch.setattr(market_cli, "FuyaoMarketClient", fail_provider)
    monkeypatch.setattr(market_cli, "MarketDataProvider", fail_provider)
    output = tmp_path / "real-probe.json"
    store_path = tmp_path / "real-probe.sqlite3"

    exit_code = cli_main(
        [
            "fuyao",
            "real-probe",
            "--as-of",
            requested.isoformat(),
            "--output",
            str(output),
            "--path",
            str(store_path),
            "--allow-real",
        ],
        now=lambda: current,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert expected_error in payload["error"]
    assert "probe-secret" not in json.dumps(payload)
    assert provider_construction == []
    assert not output.exists()
    assert not store_path.exists()
