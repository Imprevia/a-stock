import json
from datetime import date, datetime, timedelta

import pytest

from src.market_environment.calculations import Bar
from src.market_environment.cli import main as cli_main
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.providers import INDEX_SPECS, MarketDataProvider, ProviderResult
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 3)
AFTER_MARKET = datetime(2026, 9, 3, 15, 20, tzinfo=MARKET_TIME_ZONE)


def quality(dataset: str, as_of: date, status: str = "ok") -> dict:
    return {
        "dataset": dataset,
        "source": "fixture",
        "provider": "fixture",
        "status": status,
        "observations": 3,
        "asOf": as_of.isoformat(),
        "warning": None if status == "ok" else "fixture warning",
        "warnings": [] if status == "ok" else ["fixture warning"],
    }


def chapter_payload(dataset: str, as_of: date) -> dict:
    if dataset == "breadth":
        return {
            "advanceCount": 2,
            "declineCount": 1,
            "flatCount": 0,
            "validCount": 3,
            "advanceRatio": 0.6667,
            "medianReturn": 1.0,
            "state": "多数上涨",
            "quality": quality("market-breadth", as_of),
        }
    if dataset == "limits":
        return {
            "limitUpCount": 10,
            "limitDownCount": 2,
            "failedLimitUpCount": 3,
            "failedLimitUpRatio": 0.23,
            "maxStreak": 4,
            "state": "已观测",
            "quality": quality("limit-pools", as_of),
        }
    if dataset == "sectors":
        return {"rows": [], "state": "已观测", "quality": quality("industry-ranking", as_of)}
    return {
        "state": "candidate",
        "summary": "fixture",
        "topStocks": [],
        "quality": quality("active-direction", as_of),
    }


class CollectionProvider:
    def __init__(self, *, failing_datasets: set[str] | None = None, failing_indices: set[str] | None = None):
        self.failing_datasets = failing_datasets or set()
        self.failing_indices = failing_indices or set()
        self.calls: list[str] = []

    def fetch_quotes(self, specs):
        return {}

    def fetch(self, spec, limit=160, expected_price=None, quote=None):
        self.calls.append(spec.code)
        if spec.code in self.failing_indices:
            raise RuntimeError(f"{spec.code} unavailable")
        bars = []
        for offset in range(80):
            current = AS_OF - timedelta(days=79 - offset)
            close = 3000 + offset
            bars.append(
                Bar(
                    date=current,
                    open=close - 1,
                    high=close + 2,
                    low=close - 2,
                    close=close,
                    amount=1000000 + offset,
                )
            )
        return ProviderResult(bars=bars, source="fixture")

    def _chapter(self, dataset: str, as_of: date) -> dict:
        self.calls.append(dataset)
        if dataset in self.failing_datasets:
            raise RuntimeError(f"{dataset} unavailable")
        return chapter_payload(dataset, as_of)

    def fetch_chapter01_breadth(self, as_of, *, allow_current_snapshot):
        return self._chapter("breadth", as_of)

    def fetch_chapter01_limits(self, as_of):
        return self._chapter("limits", as_of)

    def fetch_chapter01_sectors(self, as_of, *, allow_current_snapshot):
        return self._chapter("sectors", as_of)

    def fetch_chapter01_active_direction(self, as_of, *, allow_current_snapshot):
        return self._chapter("activeDirection", as_of)


def test_full_collection_continues_after_dataset_failure(tmp_path) -> None:
    provider = CollectionProvider(failing_datasets={"sectors"})
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    rebuilt: list[date] = []
    result = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=rebuilt.append,
    ).collect(AS_OF)

    tasks = {task.dataset: task for task in result.tasks}
    assert result.run.status == "partial"
    assert tasks["sectors"].status == "failed-missing"
    assert all(tasks[name].status == "success" for name in ("core", "breadth", "limits", "activeDirection"))
    assert store.get("sectors", AS_OF) is None
    assert all(store.get(name, AS_OF) is not None for name in ("core", "breadth", "limits", "activeDirection"))
    assert rebuilt == [AS_OF, AS_OF, AS_OF, AS_OF]


def test_failed_dataset_retains_same_date_success_without_rollback(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=AS_OF,
            payload=chapter_payload("sectors", AS_OF),
            source="old",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )

    result = CollectionCoordinator(
        CollectionProvider(failing_datasets={"sectors"}),
        store,
        now=lambda: AFTER_MARKET,
    ).collect(AS_OF, ["sectors"])

    assert result.run.status == "failed"
    assert result.tasks[0].status == "failed-retained"
    assert store.get("sectors", AS_OF).source == "old"
    assert "unavailable" in store.get("sectors", AS_OF).refresh_warning


def test_failed_sector_collection_does_not_retain_another_date(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    previous_date = AS_OF - timedelta(days=1)
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=previous_date,
            payload=chapter_payload("sectors", previous_date),
            source="old",
            status="ok",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )

    result = CollectionCoordinator(
        CollectionProvider(failing_datasets={"sectors"}),
        store,
        now=lambda: AFTER_MARKET,
    ).collect(AS_OF, ["sectors"])

    assert result.tasks[0].status == "failed-missing"
    assert store.get("sectors", AS_OF) is None
    assert store.get("sectors", previous_date).source == "old"


def test_failed_active_direction_fallback_retains_same_date_success(tmp_path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=AS_OF,
            payload=chapter_payload("activeDirection", AS_OF),
            source="old",
            status="partial",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    provider = MarketDataProvider()
    calls = []

    def fail(url, _params):
        calls.append(url)
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET).collect(AS_OF, ["activeDirection"])
    retained = store.get("activeDirection", AS_OF)

    assert calls == [provider._STOCK_SNAPSHOT_URL, provider._ACTIVE_DIRECTION_FALLBACK_URL]
    assert result.run.status == "failed"
    assert result.tasks[0].status == "failed-retained"
    assert retained.source == "old"
    assert "主域失败：primary disconnected" in retained.refresh_warning
    assert "延迟域失败：delayed unavailable" in retained.refresh_warning


def test_failed_active_direction_fallback_does_not_retain_another_date(tmp_path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    previous_date = AS_OF - timedelta(days=1)
    store.put(
        SnapshotRecord(
            dataset="activeDirection",
            as_of=previous_date,
            payload=chapter_payload("activeDirection", previous_date),
            source="old",
            status="partial",
            observations=3,
            warnings=(),
            fetched_at=AFTER_MARKET - timedelta(days=1),
            settled=True,
        )
    )
    provider = MarketDataProvider()

    def fail(url, _params):
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET).collect(AS_OF, ["activeDirection"])

    assert result.tasks[0].status == "failed-missing"
    assert "主域失败：primary disconnected" in result.tasks[0].warning
    assert "延迟域失败：delayed unavailable" in result.tasks[0].warning
    assert store.get("activeDirection", AS_OF) is None
    assert store.get("activeDirection", previous_date).source == "old"


def test_duplicate_task_reuses_active_lease_without_provider_call(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, store, now=lambda: AFTER_MARKET)
    first = coordinator.start_run(AS_OF, ["breadth"])
    second = coordinator.start_run(AS_OF, ["breadth"])

    assert first.tasks[0].status == "queued"
    assert second.tasks[0].status == "busy"
    coordinator.execute_run(second.run.run_id)
    assert provider.calls == []
    coordinator.execute_run(first.run.run_id)
    assert provider.calls == ["breadth"]


def test_core_index_failure_is_isolated_and_retained(tmp_path) -> None:
    failed_code = INDEX_SPECS[0].code
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    seed = CollectionCoordinator(CollectionProvider(), store, now=lambda: AFTER_MARKET).collect(AS_OF, ["core"])
    assert seed.run.status == "success"

    result = CollectionCoordinator(
        CollectionProvider(failing_indices={failed_code}),
        store,
        now=lambda: AFTER_MARKET,
    ).collect(AS_OF, ["core"])
    task = result.tasks[0]
    index_results = {item.code: item for item in store.list_core_index_results(task.task_id)}

    assert result.run.status == "partial"
    assert task.status == "partial"
    assert index_results[failed_code].status == "failed-retained"
    assert len(store.get("core", AS_OF).payload["indices"]) == len(INDEX_SPECS)


def test_all_core_failures_do_not_overwrite_retained_success(tmp_path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    CollectionCoordinator(CollectionProvider(), store, now=lambda: AFTER_MARKET).collect(AS_OF, ["core"])
    retained = store.get("core", AS_OF)

    result = CollectionCoordinator(
        CollectionProvider(failing_indices={spec.code for spec in INDEX_SPECS}),
        store,
        now=lambda: AFTER_MARKET + timedelta(minutes=5),
    ).collect(AS_OF, ["core"])
    after_failure = store.get("core", AS_OF)

    assert result.run.status == "failed"
    assert result.tasks[0].status == "failed-retained"
    assert after_failure.payload == retained.payload
    assert after_failure.fetched_at == retained.fetched_at
    assert "unavailable" in after_failure.refresh_warning


def test_latest_only_historical_collection_is_rejected_before_provider_calls(tmp_path) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(provider, SnapshotStore(tmp_path / "snapshots.sqlite3"), now=lambda: AFTER_MARKET)

    with pytest.raises(ValueError, match="latest-only"):
        coordinator.start_run(AS_OF - timedelta(days=1), ["breadth"])

    historical = coordinator.collect(AS_OF - timedelta(days=1), ["limits"])
    assert historical.run.status == "success"
    assert historical.tasks[0].settled is True
    assert provider.calls == ["limits"]


def test_scheduled_refresh_collects_all_datasets_and_emits_structured_success(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh"],
        coordinator=coordinator,
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["trigger"] == "scheduled"
    assert payload["asOf"] == AS_OF.isoformat()
    assert payload["status"] == "success"
    assert {item["dataset"] for item in payload["datasets"]} == {
        "core",
        "breadth",
        "limits",
        "sectors",
        "activeDirection",
    }
    assert all(
        {"taskId", "source", "observations", "durationMs", "status", "warning"} <= item.keys()
        for item in payload["datasets"]
    )


def test_scheduled_refresh_supports_explicit_dataset_selection(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh", "--dataset", "breadth"],
        coordinator=coordinator,
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [item["dataset"] for item in payload["datasets"]] == ["breadth"]
    assert provider.calls == ["breadth"]


def test_scheduled_refresh_skips_weekend_without_provider_calls(tmp_path, capsys) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        rebuild_aggregate=lambda _as_of: None,
    )
    saturday = datetime(2026, 9, 5, 16, 30, tzinfo=MARKET_TIME_ZONE)

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh"],
        coordinator=coordinator,
        now=lambda: saturday,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == {
        "asOf": "2026-09-05",
        "datasets": [],
        "reason": "weekend",
        "status": "skipped",
        "trigger": "scheduled",
    }
    assert provider.calls == []


def test_scheduled_refresh_rejects_pre_settlement_without_provider_calls(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        rebuild_aggregate=lambda _as_of: None,
    )
    before_settlement = AFTER_MARKET.replace(hour=15, minute=9)

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh"],
        coordinator=coordinator,
        now=lambda: before_settlement,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "rejected"
    assert "settlement" in payload["error"]
    assert payload["datasets"] == []
    assert provider.calls == []


def test_scheduled_refresh_partial_persists_successes_and_status_is_provider_free(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider(failing_datasets={"sectors"})
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh"],
        coordinator=coordinator,
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)
    calls_after_collection = list(provider.calls)
    status = coordinator.collection_status(AS_OF)

    tasks = {item["dataset"]: item for item in payload["datasets"]}
    rows = {item["dataset"]: item for item in status["datasets"]}
    assert exit_code == 2
    assert payload["status"] == "partial"
    assert tasks["sectors"]["status"] == "failed-missing"
    assert all(store.get(name, AS_OF) is not None for name in ("core", "breadth", "limits", "activeDirection"))
    assert rows["sectors"]["available"] is False
    assert rows["sectors"]["latestAttempt"].status == "failed-missing"
    assert provider.calls == calls_after_collection


def test_scheduled_refresh_all_failures_return_nonzero_without_snapshots(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider(
        failing_datasets={"breadth", "limits", "sectors", "activeDirection"},
        failing_indices={spec.code for spec in INDEX_SPECS},
    )
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh"],
        coordinator=coordinator,
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert all(item["status"] == "failed-missing" for item in payload["datasets"])
    assert all(store.get(dataset, AS_OF) is None for dataset in ("core", "breadth", "limits", "sectors", "activeDirection"))


def test_scheduled_refresh_reuses_manual_active_lease_without_duplicate_provider_call(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )
    manual = coordinator.start_run(AS_OF, ["breadth"])

    exit_code = cli_main(
        ["snapshots", "scheduled-refresh", "--dataset", "breadth"],
        coordinator=coordinator,
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["datasets"][0]["status"] == "busy"
    assert provider.calls == []
    coordinator.execute_run(manual.run.run_id)
    assert provider.calls == ["breadth"]


def test_snapshot_refresh_output_remains_backward_compatible(tmp_path, capsys) -> None:
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "snapshots.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    exit_code = cli_main(
        ["snapshots", "refresh", "--as-of", AS_OF.isoformat(), "--dataset", "breadth", "--force"],
        coordinator=coordinator,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["asOf"] == AS_OF.isoformat()
    assert payload["forced"] is True
    assert payload["status"] == "success"
    assert "trigger" not in payload
    assert [item["dataset"] for item in payload["datasets"]] == ["breadth"]
