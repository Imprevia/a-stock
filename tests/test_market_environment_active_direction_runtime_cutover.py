from __future__ import annotations

import copy
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from src.market_environment.application.mappers import candidate_to_snapshot_fields
from src.market_environment.bootstrap.app import create_app
from src.market_environment.bootstrap.container import ContainerAdapters, build_container
from src.market_environment.bootstrap.settings import MarketEnvironmentSettings
from src.market_environment.infrastructure.collection import (
    AcquisitionPlanCollector,
    StandardSnapshotCommitter,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)
STANDARD_WARNING = (
    "仅有当日成交额、涨跌幅和收盘位置；"
    "20日成交放大、超额收益与连续2日确认尚未接入"
)


def _rows(count: int = 30) -> list[dict]:
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


class RuntimeProvider:
    _STOCK_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    _ACTIVE_DIRECTION_FALLBACK_URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
    )

    def __init__(self) -> None:
        self.primary: list[dict] | Exception = _rows()
        self.delayed: list[dict] | Exception = _rows()
        self.tdx: tuple[list[dict], dict] | Exception = (_rows(), {"derived": True})
        self.eastmoney_calls: list[str] = []
        self.tdx_calls: list[date] = []
        self.legacy_active_direction_calls = 0

    def fetch_chapter01_active_direction(self, *_args, **_kwargs):
        self.legacy_active_direction_calls += 1
        raise AssertionError("legacy active-direction collector facade was invoked")

    def _fetch_eastmoney_active_direction_rows(self, url: str) -> list[dict]:
        self.eastmoney_calls.append(url)
        value = self.primary if url == self._STOCK_SNAPSHOT_URL else self.delayed
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def _fetch_tdx_active_direction_rows(self, as_of: date) -> tuple[list[dict], dict]:
        self.tdx_calls.append(as_of)
        if isinstance(self.tdx, Exception):
            raise self.tdx
        return copy.deepcopy(self.tdx)

    def _build_active_direction(
        self,
        rows: list[dict],
        as_of: date,
        *,
        source: str,
        status: str,
        warnings: list[str],
        preserve_order: bool = False,
        quality_metadata=None,
    ) -> dict:
        del preserve_order
        metadata = dict(quality_metadata or {})
        combined_warnings = [*warnings, STANDARD_WARNING]
        quality = {
            "dataset": "active-direction",
            "source": source,
            "provider": source,
            "status": status,
            "observations": len(rows),
            "asOf": as_of.isoformat(),
            "warning": "；".join(combined_warnings),
            "warnings": combined_warnings,
            **metadata,
        }
        return {
            "state": "candidate",
            "summary": "成交额前30中形成方向聚集线索",
            "topStocks": [
                {
                    "code": str(row["f12"]),
                    "name": str(row["f14"]),
                    "industry": str(row["f100"]),
                    "changePct": float(row["f3"]),
                    "amount": float(row["f6"]),
                    "closePosition": 0.5,
                }
                for row in rows[:10]
            ],
            "quality": quality,
        }

    def close(self) -> None:
        pass


class FuyaoClient:
    def close(self) -> None:
        pass


class TimezoneRepository:
    def get(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None

    def close(self) -> None:
        pass


class Executor:
    def submit(self, function, *args):
        return function(*args)

    def shutdown(self, *, wait=True, cancel_futures=False) -> None:
        pass


class SnapshotRepository:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.lease = None

    def put(self, candidate):
        fields = candidate_to_snapshot_fields(candidate, fetched_at=NOW)
        self.store.put(
            SnapshotRecord(**fields),
            lease=self.lease,
            now=NOW.astimezone(timezone.utc),
        )
        return candidate


class LeaseRepository:
    def __init__(self, snapshots: SnapshotRepository) -> None:
        self.snapshots = snapshots

    def execute_fenced(
        self,
        lease,
        _operation,
        writer,
        *,
        expected_identity=None,
    ):
        assert expected_identity.dataset == lease.dataset
        assert expected_identity.as_of == lease.as_of
        self.snapshots.lease = lease
        try:
            return writer(object())
        finally:
            self.snapshots.lease = None


class UnitOfWork:
    def __init__(self, store: SnapshotStore) -> None:
        self.snapshots = SnapshotRepository(store)
        self.leases = LeaseRepository(self.snapshots)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def commit(self) -> None:
        self.committed = True


class UnitOfWorkFactory:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store
        self.units: list[UnitOfWork] = []

    def __call__(self) -> UnitOfWork:
        unit = UnitOfWork(self.store)
        self.units.append(unit)
        return unit


def _runtime_container(tmp_path, *, settings_env: dict[str, str] | None = None):
    store = SnapshotStore(tmp_path / "active-direction-runtime.sqlite3")
    provider = RuntimeProvider()
    unit_of_work_factory = UnitOfWorkFactory(store)
    environment = {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
    environment.update(settings_env or {})
    container = build_container(
        MarketEnvironmentSettings.from_environment(environment),
        adapters=ContainerAdapters(
            repository=store,
            collector=provider,
            clock=lambda: NOW,
            task_executor=Executor(),
            refresh_executor=Executor(),
            timezone_repository=TimezoneRepository(),
            fuyao_adapter=FuyaoClient(),
            unit_of_work_factory=unit_of_work_factory,
        ),
    )
    container.reads.collection.coordinator.rebuild_aggregate = (
        lambda _as_of, **_kwargs: None
    )
    return container, store, provider, unit_of_work_factory


def test_default_runtime_collects_active_direction_through_typed_boundaries(
    tmp_path,
) -> None:
    container, store, provider, unit_of_work_factory = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator

    result = coordinator.collect(AS_OF, ("activeDirection",))

    assert coordinator.typed_cutover_datasets == frozenset(
        {"core", "breadth", "limits", "sectors", "activeDirection"}
    )
    assert isinstance(
        container.registries.collectors.get("activeDirection"),
        AcquisitionPlanCollector,
    )
    assert isinstance(
        container.registries.committers.get("activeDirection"),
        StandardSnapshotCommitter,
    )
    assert result.run.status == "partial"
    assert result.tasks[0].status == "partial"
    assert result.tasks[0].source == "eastmoney-clist"
    assert result.tasks[0].observations == 30
    assert result.tasks[0].warning == STANDARD_WARNING
    assert "providerCollectionMs" in result.tasks[0].timings
    assert provider.legacy_active_direction_calls == 0
    assert provider.eastmoney_calls == [provider._STOCK_SNAPSHOT_URL]
    assert provider.tdx_calls == []
    snapshot = store.get("activeDirection", AS_OF)
    assert snapshot is not None
    assert snapshot.source == "eastmoney-clist"
    assert snapshot.status == "partial"
    assert snapshot.observations == 30
    assert snapshot.payload["quality"]["asOf"] == AS_OF.isoformat()
    assert unit_of_work_factory.units[0].committed is True
    container.close()


def test_runtime_preserves_delayed_then_optional_tdx_order(tmp_path) -> None:
    container, _store, provider, _factory = _runtime_container(
        tmp_path,
        settings_env={
            "MARKET_ENVIRONMENT_TDX_DERIVED_ACTIVE_DIRECTION_ENABLED": "1"
        },
    )
    provider.primary = RuntimeError("primary unavailable")
    provider.delayed = RuntimeError("delayed unavailable")

    result = container.reads.collection.coordinator.collect(
        AS_OF,
        ("activeDirection",),
    )

    assert result.tasks[0].status == "partial"
    assert result.tasks[0].source == "tdx-daily-package-derived"
    assert "东方财富容量方向不可用" in result.tasks[0].warning
    assert "已降级到通达信盘后包" in result.tasks[0].warning
    assert provider.eastmoney_calls == [
        provider._STOCK_SNAPSHOT_URL,
        provider._ACTIVE_DIRECTION_FALLBACK_URL,
    ]
    assert provider.tdx_calls == [AS_OF]
    assert provider.legacy_active_direction_calls == 0
    container.close()


def test_runtime_uses_delayed_source_before_disabled_tdx(tmp_path) -> None:
    container, _store, provider, _factory = _runtime_container(tmp_path)
    provider.primary = RuntimeError("primary unavailable")

    result = container.reads.collection.coordinator.collect(
        AS_OF,
        ("activeDirection",),
    )

    assert result.tasks[0].status == "success"
    assert result.tasks[0].source == "eastmoney-clist-delay"
    assert result.tasks[0].observations == 30
    assert "东方财富容量方向主域不可用：primary unavailable" in (
        result.tasks[0].warning
    )
    assert "已降级到东方财富延迟容量方向" in result.tasks[0].warning
    assert provider.eastmoney_calls == [
        provider._STOCK_SNAPSHOT_URL,
        provider._ACTIVE_DIRECTION_FALLBACK_URL,
    ]
    assert provider.tdx_calls == []
    assert provider.legacy_active_direction_calls == 0
    container.close()


def test_default_runtime_does_not_construct_legacy_active_direction_collector(
    monkeypatch,
    tmp_path,
) -> None:
    from src.market_environment.bootstrap import container as container_module

    def reject_legacy_active_direction(*_args, **_kwargs):
        raise AssertionError("legacy ActiveDirectionCollector was constructed")

    monkeypatch.setattr(
        container_module,
        "ActiveDirectionCollector",
        reject_legacy_active_direction,
    )

    container, _store, _provider, _factory = _runtime_container(tmp_path)

    assert isinstance(
        container.registries.collectors.get("activeDirection"),
        AcquisitionPlanCollector,
    )
    container.close()


def test_active_direction_failure_retains_same_date_and_polling_is_provider_free(
    tmp_path,
) -> None:
    container, store, provider, _factory = _runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator
    first = coordinator.collect(AS_OF, ("activeDirection",))
    provider.primary = RuntimeError("primary unavailable")
    provider.delayed = RuntimeError("delayed unavailable")

    second = coordinator.collect(AS_OF, ("activeDirection",))
    eastmoney_calls_after_collection = list(provider.eastmoney_calls)

    assert first.tasks[0].status == "partial"
    assert second.tasks[0].status == "failed-retained"
    assert "delayed unavailable" in second.tasks[0].warning
    assert provider.tdx_calls == []
    retained = store.get("activeDirection", AS_OF)
    assert retained is not None
    assert retained.source == "eastmoney-clist"

    def provider_call_is_forbidden(*_args, **_kwargs):
        raise AssertionError("provider called while polling local collection state")

    provider._fetch_eastmoney_active_direction_rows = provider_call_is_forbidden
    with TestClient(create_app(overrides=container)) as client:
        run_response = client.get(
            f"/api/market-environment/collection-runs/{second.run.run_id}"
        )
        status_response = client.get(
            f"/api/market-environment/data-collection?as_of={AS_OF.isoformat()}"
        )

    assert run_response.status_code == 200
    assert run_response.json()["tasks"][0]["status"] == "failed-retained"
    assert status_response.status_code == 200
    active_direction = next(
        item
        for item in status_response.json()["datasets"]
        if item["dataset"] == "activeDirection"
    )
    assert active_direction["available"] is True
    assert active_direction["source"] == "eastmoney-clist"
    assert "delayed unavailable" in active_direction["refreshWarning"]
    assert provider.eastmoney_calls == eastmoney_calls_after_collection
