from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

from src.market_environment import cli
from src.market_environment.refresh import MARKET_TIME_ZONE, SnapshotRefresher
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 2)
AFTER_MARKET = datetime(2026, 9, 2, 15, 20, tzinfo=MARKET_TIME_ZONE)


def quality(dataset: str, status: str = "ok", observations: int = 3, *, as_of: date = AS_OF) -> dict:
    return {
        "dataset": dataset,
        "source": "fixture",
        "provider": "fixture",
        "status": status,
        "observations": observations,
        "asOf": as_of.isoformat(),
        "warning": None if status in {"ok", "partial", "fallback"} else "fixture failure",
        "warnings": [] if status in {"ok", "partial", "fallback"} else ["fixture failure"],
    }


class RefreshProvider:
    def __init__(self, *, fail_active: bool = False) -> None:
        self.fail_active = fail_active
        self.calls: list[str] = []

    def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
        self.calls.append("breadth")
        return {
            "advanceCount": 2,
            "declineCount": 1,
            "flatCount": 0,
            "validCount": 3,
            "advanceRatio": 0.6667,
            "medianReturn": 1.0,
            "state": "多数上涨",
            "quality": quality("market-breadth", "fallback", as_of=as_of),
        }

    def fetch_chapter01_active_direction(self, as_of, *, allow_current_snapshot):
        self.calls.append("activeDirection")
        status = "failed" if self.fail_active else "partial"
        return {
            "state": "insufficient" if self.fail_active else "candidate",
            "summary": None if self.fail_active else "fixture direction",
            "topStocks": [],
            "quality": quality("active-direction", status, as_of=as_of),
        }


def test_refresh_stores_successful_datasets_as_settled(tmp_path, caplog) -> None:
    provider = RefreshProvider()
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    with caplog.at_level("INFO"):
        result = SnapshotRefresher(provider, store, now=lambda: AFTER_MARKET).refresh(AS_OF)

    assert result["status"] == "ok"
    assert provider.calls == ["breadth", "activeDirection"]
    assert store.get("breadth", AS_OF).settled is True
    assert store.get("activeDirection", AS_OF).settled is True
    assert all(item["cacheResult"] == "stored" for item in result["datasets"])
    assert all("providerCollectionMs" in item["timings"] for item in result["datasets"])
    assert all("derivationMs" in item["timings"] for item in result["datasets"])
    refresh_records = [record for record in caplog.records if getattr(record, "event", None) == "market_snapshot_refresh"]
    assert len(refresh_records) == 2
    assert all(record.cache_result == "stored" for record in refresh_records)
    assert all("providerCollectionMs" in record.phase_timings for record in refresh_records)


def test_partial_refresh_keeps_previous_success(tmp_path, caplog) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    existing_payload = RefreshProvider().fetch_chapter01_active_direction(AS_OF, allow_current_snapshot=True)
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=AS_OF,
            payload=existing_payload,
            source="old",
            status="partial",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )

    with caplog.at_level("INFO"):
        result = SnapshotRefresher(
            RefreshProvider(fail_active=True),
            store,
            now=lambda: AFTER_MARKET,
        ).refresh(AS_OF)

    active = next(item for item in result["datasets"] if item["dataset"] == "activeDirection")
    assert result["status"] == "partial"
    assert active["cacheResult"] == "retained"
    assert store.get("activeDirection", AS_OF).source == "old"
    assert store.get("activeDirection", AS_OF).refresh_warning == "fixture failure"
    failure_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "market_snapshot_refresh"
        and record.dataset == "activeDirection"
    ]
    assert failure_records[0].cache_result == "retained"
    assert failure_records[0].quality_status == "failed"


def test_refresh_boundary_requires_current_date_and_settlement_unless_forced(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    before_market = AFTER_MARKET.replace(hour=14)
    refresher = SnapshotRefresher(RefreshProvider(), store, now=lambda: before_market)

    try:
        refresher.refresh(AS_OF)
    except ValueError as exc:
        assert "settlement" in str(exc)
    else:
        raise AssertionError("pre-settlement refresh must be rejected")

    result = refresher.refresh(AS_OF - timedelta(days=1), ["breadth"], force=True)
    assert result["status"] == "ok"
    assert store.get("breadth", AS_OF - timedelta(days=1)).settled is False


def test_busy_lease_prevents_duplicate_collection(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.acquire_lease(
        "breadth",
        AS_OF,
        "other-worker",
        lease_seconds=60,
        now=AFTER_MARKET.astimezone(timezone.utc),
    )
    provider = RefreshProvider()

    result = SnapshotRefresher(provider, store, now=lambda: AFTER_MARKET).refresh(AS_OF, ["breadth"])

    assert result["status"] == "failed"
    assert result["datasets"][0]["cacheResult"] == "busy"
    assert provider.calls == []


def test_cli_outputs_structured_refresh_result(monkeypatch, capsys) -> None:
    class FakeCoordinator:
        def collect(self, as_of, datasets):
            return SimpleNamespace(
                run=SimpleNamespace(run_id="run-1", as_of=as_of, status="success"),
                tasks=(
                    SimpleNamespace(
                        task_id="task-1",
                        dataset="breadth",
                        source="fixture",
                        observations=3,
                        duration_ms=1.0,
                        status="success",
                        warning=None,
                    ),
                ),
            )

    monkeypatch.setattr(cli, "CollectionCoordinator", FakeCoordinator)
    exit_code = cli.main(["snapshots", "refresh", "--as-of", AS_OF.isoformat(), "--dataset", "breadth"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["datasets"][0]["source"] == "fixture"
    assert output["datasets"][0]["status"] == "success"
