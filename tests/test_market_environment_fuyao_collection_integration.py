from datetime import date, datetime
import copy
import json

import pytest

from src.market_environment.collection import CollectionCoordinator
from src.market_environment.fuyao_config import FuyaoCollectionConfig
from src.market_environment.fuyao_market import FuyaoMarketResult
from src.market_environment.provider_capability import ProviderCapabilityReport
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.sector_enrichment import ENRICHMENT_MAPPING_REVISION
from src.market_environment import cli as market_cli
from src.market_environment.cli import main as cli_main


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)


class ChapterProvider:
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


class FailingFuyaoAdapter:
    def fetch_breadth(self, as_of):
        raise RuntimeError("fixture Fuyao unavailable")


class FailingSectorProvider(ChapterProvider):
    def __init__(self):
        self.sector_calls = 0

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
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
    def __init__(self, *, fail=False):
        self.calls = 0
        self.fail = fail

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
                "providerRevision": "r1",
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


def eligible_report(dataset: str) -> ProviderCapabilityReport:
    return ProviderCapabilityReport(provider="fuyao", dataset=dataset, revision="r1", status="eligible")


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


def test_sectors_prefers_eastmoney_when_it_is_healthy(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    adapter = FuyaoSectorAdapter()
    result = CollectionCoordinator(
        ChapterProvider(),
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])

    assert result.run.status == "success"
    assert result.tasks[0].source == "fixture"
    assert adapter.calls == 0


def test_sectors_shadow_failure_does_not_block_eastmoney_result(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED": "1",
        }
    )
    adapter = FuyaoSectorAdapter(fail=True)
    result = CollectionCoordinator(
        ChapterProvider(),
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])

    assert result.run.status == "success"
    assert result.tasks[0].status == "success"
    assert adapter.calls == 1
    assert result.tasks[0].timings["shadow"]["status"] == "insufficient"
    assert "shadow 不可用" in (result.tasks[0].warning or "")


def test_sectors_uses_approved_fuyao_only_after_eastmoney_chain_fails(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = FailingSectorProvider()
    adapter = FuyaoSectorAdapter()
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])
    snapshot = store.get("sectors", AS_OF)

    assert result.run.status == "partial"
    assert result.tasks[0].status == "partial"
    assert result.tasks[0].source == "fuyao"
    assert adapter.calls == 1
    assert snapshot is not None and snapshot.source == "fuyao"
    assert snapshot.payload["rows"][0]["mainNet"] is None
    assert "东方财富行业排名不可用" in (result.tasks[0].warning or "")
    assert "扶摇行业 provider fields unavailable" in (result.tasks[0].warning or "")
    assert "capability revision: r1" in (result.tasks[0].warning or "")
    warning = result.tasks[0].warning or ""
    assert warning.index("扶摇行业 provider fields unavailable") < warning.index("东方财富行业排名不可用")
    assert warning.index("东方财富行业排名不可用") < warning.index("capability revision: r1")
    assert result.tasks[0].timings["sourceRevision"] == "r1"


def test_fuyao_sector_enrichment_is_persisted_in_snapshot_and_task_metadata(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = EnrichingSectorProvider()

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(),
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])
    snapshot = store.get("sectors", AS_OF)

    assert result.tasks[0].status == "partial"
    assert provider.enrichment_calls == [(AS_OF, True)]
    assert snapshot is not None
    assert snapshot.source == "fuyao"
    assert snapshot.payload["rows"][0]["mainNet"] == 88.0
    assert snapshot.payload["rows"][0]["leader"] == "样本股"
    enrichment = snapshot.payload["quality"]["sectorEnrichment"]
    assert enrichment["sameVendor"] is True
    assert enrichment["mappingRevision"] == "fuyao-eastmoney-sector-map-v1"
    assert enrichment["matchMethod"] == "normalized-name"
    assert enrichment["matchedRows"] == 1
    assert enrichment["identityCoverage"] == 1.0
    assert result.tasks[0].timings["sectorEnrichment"] == enrichment


def test_sector_enrichment_failure_commits_fuyao_base_and_does_not_fail_siblings(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = EnrichingSectorProvider(fail_enrichment=True)

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(),
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors", "breadth"])
    tasks = {task.dataset: task for task in result.tasks}
    snapshot = store.get("sectors", AS_OF)

    assert result.run.status == "partial"
    assert tasks["sectors"].status == "partial"
    assert tasks["breadth"].status == "success"
    assert snapshot is not None
    assert snapshot.payload["rows"][0]["mainNet"] is None
    assert snapshot.payload["quality"]["sectorEnrichment"]["status"] == "failed"
    assert "fixture dataapi unavailable" in (tasks["sectors"].warning or "")


def test_sector_enrichment_is_skipped_before_settlement_without_provider_call(tmp_path):
    before_settlement = datetime(2026, 9, 18, 14, 30, tzinfo=MARKET_TIME_ZONE)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = EnrichingSectorProvider()

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: before_settlement,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(),
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])
    snapshot = store.get("sectors", AS_OF)

    assert result.tasks[0].status == "partial"
    assert provider.enrichment_calls == []
    assert snapshot is not None
    enrichment = snapshot.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "skipped"
    assert enrichment["dateEvidence"]["eligible"] is False


def test_sector_enrichment_is_skipped_for_historical_date_without_provider_call(tmp_path):
    historical_now = datetime(2026, 9, 21, 16, 0, tzinfo=MARKET_TIME_ZONE)
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(eligible_report("sectors"))
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = EnrichingSectorProvider()

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: historical_now,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(),
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"], allow_historical_latest_only=True)
    snapshot = store.get("sectors", AS_OF)

    assert result.tasks[0].status == "partial"
    assert provider.enrichment_calls == []
    assert snapshot is not None
    enrichment = snapshot.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == "skipped"
    assert enrichment["dateEvidence"]["reason"] == "东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用"
    assert enrichment["dateEvidence"]["requested"] == AS_OF.isoformat()
    assert enrichment["dateEvidence"]["current"] == "2026-09-21"


@pytest.mark.parametrize(
    ("clock_time", "expected_calls", "expected_status", "expected_reason"),
    [
        ("15:09", 0, "skipped", "东方财富 dataapi 行业字段补充仅允许当前上海交易日且结算后调用"),
        ("15:10", 1, "complete", "current Shanghai market date after settlement"),
    ],
)
def test_sector_enrichment_settlement_boundary_is_inclusive(
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
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    provider = EnrichingSectorProvider()

    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: at_boundary,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(),
        rebuild_aggregate=lambda _date: None,
    ).collect(AS_OF, ["sectors"])
    snapshot = store.get("sectors", AS_OF)

    assert provider.enrichment_calls == ([(AS_OF, True)] if expected_calls else [])
    assert snapshot is not None
    enrichment = snapshot.payload["quality"]["sectorEnrichment"]
    assert enrichment["status"] == expected_status
    assert enrichment["dateEvidence"]["reason"] == expected_reason
    assert enrichment["dateEvidence"]["current"] == AS_OF.isoformat()
    assert enrichment["dateEvidence"]["settled"] is (expected_calls == 1)


def test_sectors_capability_gate_blocks_fuyao_after_eastmoney_failure(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    adapter = FuyaoSectorAdapter()
    result = CollectionCoordinator(
        FailingSectorProvider(),
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
    ).collect(AS_OF, ["sectors"])

    assert result.tasks[0].status == "failed-missing"
    assert adapter.calls == 0
    assert "缺少批准报告" in (result.tasks[0].warning or "")


@pytest.mark.parametrize(
    ("report", "expected_warning"),
    [
        (ProviderCapabilityReport(provider="fuyao", dataset="sectors", revision="r1", status="ineligible"), "状态为 ineligible"),
        (ProviderCapabilityReport(provider="fuyao", dataset="sectors", revision="r2", status="eligible"), "revision 不匹配"),
    ],
)
def test_sectors_capability_status_or_revision_mismatch_blocks_provider(tmp_path, report, expected_warning):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put_capability_report(report)
    config = FuyaoCollectionConfig.from_environment(
        {
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    adapter = FuyaoSectorAdapter()
    result = CollectionCoordinator(
        FailingSectorProvider(),
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=adapter,
    ).collect(AS_OF, ["sectors"])

    assert result.tasks[0].status == "failed-missing"
    assert adapter.calls == 0
    assert expected_warning in (result.tasks[0].warning or "")


def test_sectors_fallback_failure_retains_only_same_date_snapshot(tmp_path):
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
            "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION": "r1",
        }
    )
    result = CollectionCoordinator(
        FailingSectorProvider(),
        store,
        now=lambda: NOW,
        fuyao_config=config,
        fuyao_adapter=FuyaoSectorAdapter(fail=True),
    ).collect(AS_OF, ["sectors"])

    assert result.tasks[0].status == "failed-retained"
    assert store.get("sectors", AS_OF).source == "old-fuyao"
    assert "扶摇行业 fallback 不可用" in (result.tasks[0].warning or "")


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
        ]
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
    current_now = datetime(2026, 9, 29, 16, 31, tzinfo=MARKET_TIME_ZONE)
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
