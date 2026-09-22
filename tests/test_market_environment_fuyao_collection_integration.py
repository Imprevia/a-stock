from datetime import date, datetime
import json

from src.market_environment.collection import CollectionCoordinator
from src.market_environment.fuyao_config import FuyaoCollectionConfig
from src.market_environment.fuyao_market import FuyaoMarketResult
from src.market_environment.provider_capability import ProviderCapabilityReport
from src.market_environment.snapshot_store import SnapshotStore
from src.market_environment.refresh import MARKET_TIME_ZONE
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


def test_offline_capability_probe_uses_fixture_only(tmp_path, capsys):
    fixture = "tests/fixtures/market-environment/fuyao-market-data.json"
    output = tmp_path / "capability.json"
    assert cli_main(["fuyao", "capability-probe", "--fixture", fixture, "--as-of", AS_OF.isoformat(), "--output", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "fuyao"
    assert {item["dataset"] for item in payload["reports"]} == {"core", "breadth", "sectors", "activeDirection"}
    assert "fixture-key" not in output.read_text(encoding="utf-8")
