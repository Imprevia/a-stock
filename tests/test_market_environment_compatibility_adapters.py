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
    LegacyCollectionCommandAdapter,
    LegacyCollectionQueryAdapter,
    LegacyDatasetCollectorAdapter,
    LegacyMarketEnvironmentQueryAdapter,
    LegacySnapshotRepositoryAdapter,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotStore
from tests.test_market_environment_collection import AS_OF, CollectionProvider


NOW = datetime(2026, 9, 3, 16, 0, tzinfo=MARKET_TIME_ZONE)


def test_snapshot_store_adapter_round_trips_typed_candidate(tmp_path) -> None:
    adapter = LegacySnapshotRepositoryAdapter(
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
    collector = LegacyDatasetCollectorAdapter.from_provider(
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


class FakeService:
    def get(self, as_of):
        return {"kind": "aggregate", "asOf": as_of.isoformat()}

    def get_core(self, as_of):
        return {"kind": "core", "asOf": as_of.isoformat()}

    def get_chapter01(self, as_of, section):
        return {"kind": section, "asOf": as_of.isoformat()}

    def get_next_session_comparison(self, as_of):
        return {"kind": "next", "asOf": as_of.isoformat()}


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
    service_adapter = LegacyMarketEnvironmentQueryAdapter(FakeService())
    coordinator = FakeCoordinator()
    query_adapter = LegacyCollectionQueryAdapter(coordinator)
    command_adapter = LegacyCollectionCommandAdapter(coordinator, ImmediateExecutor())

    assert isinstance(service_adapter, MarketEnvironmentQueryPort)
    assert isinstance(query_adapter, CollectionQueryPort)
    assert isinstance(command_adapter, CollectionCommandPort)
    assert service_adapter.get_core(AS_OF)["kind"] == "core"
    assert query_adapter.get_run("run-1") == {"runId": "run-1"}
    assert command_adapter.start_run(AS_OF, ("breadth",))["datasets"] == ("breadth",)
    assert command_adapter.submit_run("run-1") == "run-1"
    assert coordinator.executed == ["run-1"]
