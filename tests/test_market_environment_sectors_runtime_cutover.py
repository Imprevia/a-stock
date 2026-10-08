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
from src.market_environment.infrastructure.providers.sectors_acquisition import (
    SectorsAcquisitionPlan,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 18)
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=MARKET_TIME_ZONE)
STANDARD_WARNING = (
    "仅反映当日行业排名和资金流，5日持续性、板块宽度与分歧承接尚未接入"
)


def _rows(*, change: float = 2.5) -> list[dict]:
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


class RuntimeProvider:
    def __init__(self) -> None:
        self.primary: list[dict] | Exception = _rows()
        self.delayed: list[dict] | Exception = _rows(change=1.2)
        self.eastmoney_calls: list[str] = []
        self.enrichment_calls = 0
        self.legacy_sectors_calls = 0

    def fetch_chapter01_sectors(self, *_args, **_kwargs):
        self.legacy_sectors_calls += 1
        raise AssertionError("legacy sectors collector facade was invoked")

    def _fetch_eastmoney_industries_from(self, url: str) -> list[dict]:
        delayed = "push2delay" in url
        self.eastmoney_calls.append("delayed" if delayed else "primary")
        value = self.delayed if delayed else self.primary
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

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
        quality_warnings = [*warnings, STANDARD_WARNING]
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

    def enrich_fuyao_sectors(self, *_args, **_kwargs):
        self.enrichment_calls += 1
        raise AssertionError("default-disabled sector enrichment was invoked")

    def close(self) -> None:
        pass


class FuyaoClient:
    def __init__(self) -> None:
        self.calls: list[date] = []

    def fetch_sectors(self, as_of: date):
        self.calls.append(as_of)
        raise AssertionError("default-disabled Fuyao sectors source was invoked")

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


def _runtime_container(tmp_path):
    store = SnapshotStore(tmp_path / "sectors-runtime.sqlite3")
    provider = RuntimeProvider()
    fuyao = FuyaoClient()
    unit_of_work_factory = UnitOfWorkFactory(store)
    container = build_container(
        MarketEnvironmentSettings.from_environment(
            {"MARKET_ENVIRONMENT_PERSISTENT_CACHE": "0"}
        ),
        adapters=ContainerAdapters(
            repository=store,
            collector=provider,
            clock=lambda: NOW,
            task_executor=Executor(),
            refresh_executor=Executor(),
            timezone_repository=TimezoneRepository(),
            fuyao_adapter=fuyao,
            unit_of_work_factory=unit_of_work_factory,
        ),
    )
    rebuilds: list[date] = []
    container.reads.collection.coordinator.rebuild_aggregate = (
        lambda as_of, **_kwargs: rebuilds.append(as_of)
    )
    return container, store, provider, fuyao, unit_of_work_factory, rebuilds


def test_default_runtime_collects_sectors_through_typed_boundaries(tmp_path) -> None:
    container, store, provider, fuyao, unit_of_work_factory, rebuilds = (
        _runtime_container(tmp_path)
    )
    coordinator = container.reads.collection.coordinator

    result = coordinator.collect(AS_OF, ("sectors",))

    assert coordinator.typed_cutover_datasets == frozenset(
        {"core", "breadth", "limits", "sectors", "activeDirection"}
    )
    assert isinstance(
        container.registries.acquisition_plans.get("sectors"),
        SectorsAcquisitionPlan,
    )
    assert isinstance(
        container.registries.collectors.get("sectors"),
        AcquisitionPlanCollector,
    )
    assert isinstance(
        container.registries.committers.get("sectors"),
        StandardSnapshotCommitter,
    )
    assert isinstance(
        container.registries.collectors.get("core"),
        AcquisitionPlanCollector,
    )
    assert isinstance(
        container.registries.collectors.get("limits"),
        AcquisitionPlanCollector,
    )
    assert result.run.status == "partial"
    assert result.tasks[0].status == "partial"
    assert result.tasks[0].source == "eastmoney-clist"
    assert result.tasks[0].observations == 1
    assert result.tasks[0].warning == STANDARD_WARNING
    assert "providerCollectionMs" in result.tasks[0].timings
    assert provider.legacy_sectors_calls == 0
    assert provider.eastmoney_calls == ["primary"]
    assert provider.enrichment_calls == 0
    assert fuyao.calls == []
    assert container.settings.sector_enrichment_enabled is False
    snapshot = store.get("sectors", AS_OF)
    assert snapshot is not None
    assert snapshot.source == "eastmoney-clist"
    assert snapshot.status == "partial"
    assert snapshot.observations == 1
    assert snapshot.payload["quality"]["asOf"] == AS_OF.isoformat()
    assert len(unit_of_work_factory.units) == 1
    assert unit_of_work_factory.units[0].committed is True
    assert rebuilds == [AS_OF]
    container.close()


def test_runtime_preserves_primary_then_delayed_order(tmp_path) -> None:
    container, _store, provider, fuyao, _factory, _rebuilds = _runtime_container(
        tmp_path
    )
    provider.primary = RuntimeError("primary unavailable")

    result = container.reads.collection.coordinator.collect(AS_OF, ("sectors",))

    assert result.tasks[0].status == "partial"
    assert result.tasks[0].source == "eastmoney-clist-delay"
    assert result.tasks[0].observations == 1
    assert "东方财富行业主域不可用：primary unavailable" in result.tasks[0].warning
    assert "已降级到东方财富延迟行业排名" in result.tasks[0].warning
    assert provider.eastmoney_calls == ["primary", "delayed"]
    assert provider.enrichment_calls == 0
    assert fuyao.calls == []
    assert provider.legacy_sectors_calls == 0
    container.close()


def test_default_runtime_does_not_construct_legacy_sectors_collector(
    monkeypatch,
    tmp_path,
) -> None:
    from src.market_environment.bootstrap import container as container_module

    def reject_legacy_sectors(*_args, **_kwargs):
        raise AssertionError("legacy SectorsCollector was constructed")

    monkeypatch.setattr(container_module, "SectorsCollector", reject_legacy_sectors)

    container, *_rest = _runtime_container(tmp_path)

    assert isinstance(
        container.registries.collectors.get("sectors"),
        AcquisitionPlanCollector,
    )
    container.close()


def test_sectors_failure_retains_same_date_and_polling_is_provider_free(
    tmp_path,
) -> None:
    container, store, provider, fuyao, unit_of_work_factory, rebuilds = (
        _runtime_container(tmp_path)
    )
    coordinator = container.reads.collection.coordinator
    first = coordinator.collect(AS_OF, ("sectors",))
    provider.primary = RuntimeError("primary unavailable")
    provider.delayed = RuntimeError("delayed unavailable")

    second = coordinator.collect(AS_OF, ("sectors",))
    calls_after_collection = list(provider.eastmoney_calls)

    assert first.tasks[0].status == "partial"
    assert second.tasks[0].status == "failed-retained"
    assert "delayed unavailable" in second.tasks[0].warning
    assert "扶摇 sectors 未启用" in second.tasks[0].warning
    assert fuyao.calls == []
    assert provider.enrichment_calls == 0
    retained = store.get("sectors", AS_OF)
    assert retained is not None
    assert retained.source == "eastmoney-clist"
    assert len(unit_of_work_factory.units) == 1
    assert rebuilds == [AS_OF, AS_OF]

    def provider_call_is_forbidden(*_args, **_kwargs):
        raise AssertionError("provider called while polling local collection state")

    provider._fetch_eastmoney_industries_from = provider_call_is_forbidden
    fuyao.fetch_sectors = provider_call_is_forbidden
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
    sectors = next(
        item
        for item in status_response.json()["datasets"]
        if item["dataset"] == "sectors"
    )
    assert sectors["available"] is True
    assert sectors["source"] == "eastmoney-clist"
    assert "delayed unavailable" in sectors["refreshWarning"]
    assert provider.eastmoney_calls == calls_after_collection
    container.close()
