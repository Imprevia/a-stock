from __future__ import annotations

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
from src.market_environment.infrastructure.providers.capability import (
    ProviderCapabilityReport,
)
from src.market_environment.infrastructure.providers.fuyao.market import (
    FuyaoMarketResult,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 16, 0, tzinfo=MARKET_TIME_ZONE)


def breadth_payload(as_of: date, primary_warning: str) -> dict:
    warnings = (
        primary_warning,
        "已按涨跌幅排序分页定位全 A 有效样本",
    )
    return {
        "advanceCount": 3,
        "declineCount": 1,
        "flatCount": 0,
        "validCount": 4,
        "advanceRatio": 0.75,
        "medianReturn": 0.8,
        "state": "多数上涨",
        "quality": {
            "dataset": "market-breadth",
            "source": "eastmoney-clist-delay",
            "provider": "eastmoney-clist-delay",
            "status": "fallback",
            "observations": 4,
            "asOf": as_of.isoformat(),
            "warning": "；".join(warnings),
            "warnings": list(warnings),
        },
    }


class RuntimeProvider:
    def __init__(self) -> None:
        self.eastmoney_calls: list[tuple[date, str]] = []
        self.legacy_breadth_calls = 0
        self.fail = False

    def fetch_chapter01_breadth(self, *_args, **_kwargs):
        self.legacy_breadth_calls += 1
        raise AssertionError("legacy breadth collector facade was invoked")

    def _fetch_tdx_breadth(self, *_args, **_kwargs):
        raise AssertionError("TDX must remain disabled by its default gate")

    def _fetch_eastmoney_breadth_fallback(
        self,
        as_of: date,
        primary_warning: str,
    ) -> dict:
        self.eastmoney_calls.append((as_of, primary_warning))
        if self.fail:
            raise RuntimeError("offline fixture unavailable")
        return breadth_payload(as_of, primary_warning)


class FuyaoClient:
    def __init__(self, result: FuyaoMarketResult | None = None) -> None:
        self.result = result
        self.calls: list[date] = []

    def fetch_breadth(self, as_of: date):
        self.calls.append(as_of)
        if self.result is None:
            raise AssertionError("Fuyao must remain disabled by its default gate")
        return self.result

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


def runtime_container(
    tmp_path,
    *,
    settings_env: dict[str, str] | None = None,
    fuyao_client: FuyaoClient | None = None,
    prepare_store=None,
):
    store = SnapshotStore(tmp_path / "breadth-runtime.sqlite3")
    if prepare_store is not None:
        prepare_store(store)
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
            fuyao_adapter=fuyao_client or FuyaoClient(),
            unit_of_work_factory=unit_of_work_factory,
        ),
    )
    coordinator = container.reads.collection.coordinator
    coordinator.rebuild_aggregate = lambda _as_of, **_kwargs: None
    return container, store, provider, unit_of_work_factory


def test_default_runtime_collects_breadth_through_plan_and_standard_committer(
    tmp_path,
) -> None:
    container, store, provider, unit_of_work_factory = runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator

    result = coordinator.collect(AS_OF, ("breadth",))

    assert coordinator.typed_cutover_datasets == frozenset(
        {"core", "breadth", "limits", "sectors", "activeDirection"}
    )
    assert isinstance(
        container.registries.collectors.get("breadth"),
        AcquisitionPlanCollector,
    )
    assert isinstance(
        container.registries.committers.get("breadth"),
        StandardSnapshotCommitter,
    )
    assert result.run.status == "success"
    assert result.tasks[0].status == "success"
    assert result.tasks[0].source == "eastmoney-clist-delay"
    assert result.tasks[0].observations == 4
    assert "市场广度直接使用涨跌幅排序分页统计" in result.tasks[0].warning
    assert "providerCollectionMs" in result.tasks[0].timings
    assert provider.legacy_breadth_calls == 0
    assert provider.eastmoney_calls == [
        (
            AS_OF,
            "市场广度直接使用涨跌幅排序分页统计，未请求名义全 A 主快照",
        )
    ]
    snapshot = store.get("breadth", AS_OF)
    assert snapshot is not None
    assert snapshot.as_of == AS_OF
    assert snapshot.source == "eastmoney-clist-delay"
    assert snapshot.observations == 4
    assert snapshot.payload["quality"]["asOf"] == AS_OF.isoformat()
    assert unit_of_work_factory.units[0].committed is True
    container.close()


def test_runtime_preserves_approved_fuyao_revision_and_primary_gate(tmp_path) -> None:
    value = breadth_payload(AS_OF, "")
    value["quality"].update(
        {
            "source": "fuyao",
            "provider": "fuyao",
            "providerRevision": "r1",
            "status": "ok",
            "warning": None,
            "warnings": [],
        }
    )
    result = FuyaoMarketResult(
        payload={key: item for key, item in value.items() if key != "quality"},
        quality=value["quality"],
        status="ok",
        as_of=AS_OF,
        observations=4,
        warnings=(),
    )
    fuyao = FuyaoClient(result)

    def approve(store: SnapshotStore) -> None:
        store.put_capability_report(
            ProviderCapabilityReport(
                provider="fuyao",
                dataset="breadth",
                revision="r1",
                status="eligible",
            )
        )

    container, _store, provider, _unit_of_work_factory = runtime_container(
        tmp_path,
        settings_env={
            "MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED": "1",
            "MARKET_ENVIRONMENT_FUYAO_BREADTH_APPROVED_REVISION": "r1",
        },
        fuyao_client=fuyao,
        prepare_store=approve,
    )

    collected = container.reads.collection.coordinator.collect(AS_OF, ("breadth",))

    assert collected.tasks[0].status == "success"
    assert collected.tasks[0].source == "fuyao"
    assert fuyao.calls == [AS_OF]
    assert provider.eastmoney_calls == []
    container.close()


def test_default_runtime_does_not_construct_legacy_breadth_collector(
    monkeypatch,
    tmp_path,
) -> None:
    from src.market_environment.bootstrap import container as container_module

    def reject_legacy_breadth(*_args, **_kwargs):
        raise AssertionError("legacy BreadthCollector was constructed")

    monkeypatch.setattr(container_module, "BreadthCollector", reject_legacy_breadth)

    container, _store, _provider, _unit_of_work_factory = runtime_container(tmp_path)

    assert isinstance(
        container.registries.collectors.get("breadth"),
        AcquisitionPlanCollector,
    )
    container.close()


def test_breadth_failure_retains_same_date_and_http_polling_is_provider_free(
    tmp_path,
) -> None:
    container, store, provider, _unit_of_work_factory = runtime_container(tmp_path)
    coordinator = container.reads.collection.coordinator
    first = coordinator.collect(AS_OF, ("breadth",))
    provider.fail = True

    second = coordinator.collect(AS_OF, ("breadth",))
    calls_after_collection = list(provider.eastmoney_calls)

    assert first.tasks[0].status == "success"
    assert second.tasks[0].status == "failed-retained"
    assert "offline fixture unavailable" in second.tasks[0].warning
    retained = store.get("breadth", AS_OF)
    assert retained is not None
    assert retained.source == "eastmoney-clist-delay"

    def provider_call_is_forbidden(*_args, **_kwargs):
        raise AssertionError("provider called while polling local collection state")

    provider._fetch_eastmoney_breadth_fallback = provider_call_is_forbidden
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
    breadth = next(
        item
        for item in status_response.json()["datasets"]
        if item["dataset"] == "breadth"
    )
    assert breadth["available"] is True
    assert breadth["source"] == "eastmoney-clist-delay"
    assert "offline fixture unavailable" in breadth["refreshWarning"]
    assert provider.eastmoney_calls == calls_after_collection
