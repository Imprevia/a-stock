from __future__ import annotations

from datetime import datetime

from src.market_environment.application.ports import (
    CollectionCommandPort,
    CollectionQueryPort,
    DatasetCollector,
    MarketEnvironmentQueryPort,
    SnapshotRepository,
)
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.compatibility import (
    RebuilderAggregateCommandAdapter,
    CoordinatorCollectionCommandAdapter,
    CoordinatorCollectionQueryAdapter,
    CoordinatorDatasetCollectorAdapter,
    RepositoryMarketEnvironmentQueryAdapter,
    SnapshotRepositoryAdapter,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotStore
from tests.test_market_environment_collection import AS_OF, CollectionProvider


NOW = datetime(2026, 9, 3, 16, 0, tzinfo=MARKET_TIME_ZONE)


def test_snapshot_store_adapter_round_trips_typed_candidate(tmp_path) -> None:
    adapter = SnapshotRepositoryAdapter(
        SnapshotStore(tmp_path / "adapter.sqlite3"),
        now=lambda: NOW,
    )
    candidate = CollectionCandidate(
        identity=DatasetDate("breadth", AS_OF),
        payload={"advanceCount": 2},
        source="fixture",
        status="ok",
        observations=3,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
    )

    stored = adapter.put(candidate)

    assert isinstance(adapter, SnapshotRepository)
    assert stored == adapter.get(candidate.identity)
    assert adapter.list_dates("breadth") == (AS_OF,)


def test_provider_and_coordinator_are_exposed_as_dataset_collector(tmp_path) -> None:
    provider = CollectionProvider()
    store = SnapshotStore(tmp_path / "collector.sqlite3")
    collector = CoordinatorDatasetCollectorAdapter.from_provider(
        "breadth",
        provider,
        store,
        now=lambda: NOW,
        rebuild_aggregate=lambda _as_of: None,
    )

    outcome = collector.collect(DatasetDate("breadth", AS_OF))

    assert isinstance(collector, DatasetCollector)
    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.source == "fixture"
    assert provider.calls == ["breadth"]


class _FakeSnapshotRecord:
    def __init__(self, dataset, as_of, payload):
        self.dataset = dataset
        self.as_of = as_of
        self.payload = payload
        self.source = payload.get("source", "fake-store")
        self.status = payload.get("status", "ok")
        self.observations = payload.get("observations", len(payload.get("indices", [])))
        self.settled = payload.get("settled", True)
        self.checksum = payload.get("checksum", "fake-checksum")
        self.fetched_at = payload.get("fetched_at", datetime.now())
        self.fetched_at_iso = self.fetched_at.isoformat()
        self.refresh_warning = payload.get("refresh_warning")
        self.warnings = tuple(payload.get("warnings", []))


class FakeStore:
    def __init__(self) -> None:
        self._records: dict = {}

    def get_materialized_aggregate(self, as_of):
        key = ("agg", as_of.isoformat())
        record = self._records.get(key)
        if record is None:
            return None
        return record

    def put_materialized_aggregate(self, *args, **kwargs):
        raise AssertionError("rebuilder must not be invoked via the query adapter")

    def materialization_revision(self, as_of):
        return "agg-rev"

    def get_trading_session(self, as_of):
        return None

    def list_trading_sessions(self):
        return ()

    def get(self, dataset, as_of):
        key = (dataset, as_of.isoformat())
        return self._records.get(key)

    def list_snapshot_dates(self, dataset):
        return tuple(sorted(as_of for ds, as_of in self._records if ds == dataset))

    def seed(self, dataset, as_of, payload):
        self._records[(dataset, as_of.isoformat())] = _FakeSnapshotRecord(dataset, as_of, payload)

    def seed_aggregate(self, as_of, payload):
        self._records[("agg", as_of.isoformat())] = _FakeSnapshotRecord("aggregate", as_of, payload)


class FakeCoordinator:
    def __init__(self) -> None:
        self.executed = []

    def collection_status(self, as_of):
        return {"asOf": as_of, "datasets": []}

    def get_run(self, run_id):
        return {"runId": run_id}

    def start_run(self, as_of, datasets=None):
        return {"asOf": as_of, "datasets": datasets}

    def execute_run(self, run_id):
        self.executed.append(run_id)
        return run_id


class ImmediateExecutor:
    def submit(self, function, *args):
        return function(*args)


def test_service_and_coordinator_adapters_delegate_without_algorithm_moves() -> None:
    store = FakeStore()
    store.seed_aggregate(AS_OF, {"kind": "aggregate", "asOf": AS_OF.isoformat(), "summary": {}, "chapter01": {}})
    store.seed("core", AS_OF, {"kind": "core", "asOf": AS_OF.isoformat(), "indices": [], "summary": {}, "chapter01": {}})
    service_adapter = RepositoryMarketEnvironmentQueryAdapter(store)
    coordinator = FakeCoordinator()
    query_adapter = CoordinatorCollectionQueryAdapter(coordinator)
    command_adapter = CoordinatorCollectionCommandAdapter(coordinator, ImmediateExecutor())

    assert isinstance(service_adapter, MarketEnvironmentQueryPort)
    assert isinstance(query_adapter, CollectionQueryPort)
    assert isinstance(command_adapter, CollectionCommandPort)
    assert service_adapter.get_core(AS_OF)["kind"] == "core"
    assert query_adapter.get_run("run-1") == {"runId": "run-1"}
    assert command_adapter.start_run(AS_OF, ("breadth",))["datasets"] == ("breadth",)
    assert command_adapter.submit_run("run-1") == "run-1"
    assert coordinator.executed == ["run-1"]


def test_aggregate_command_adapter_uses_rebuilder_directly() -> None:
    calls = []

    class FakeRebuilder:
        def rebuild(self, as_of, *, lease=None, now=None):
            calls.append(as_of)
            return {"asOf": as_of.isoformat(), "chapter01": {}}

    adapter = RebuilderAggregateCommandAdapter(FakeRebuilder())
    result = adapter.rebuild(AS_OF)
    assert result["asOf"] == AS_OF.isoformat()
    assert calls == [AS_OF]
