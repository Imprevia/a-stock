from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.market_environment.application.collection import DatasetCollectorRegistry
from src.market_environment.application.ports import DatasetCollector
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.domain.models import (
    DATASET_IDS,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.compatibility import (
    build_provider_collector_registry,
)
from src.market_environment.infrastructure.persistence.sqlite_import import (
    LegacySqliteSnapshotStore,
)
from src.market_environment.fuyao_config import FuyaoCollectionConfig
from tests.test_market_environment_collection import (
    AFTER_MARKET,
    AS_OF,
    CollectionProvider,
)


@dataclass
class RecordingCollector:
    dataset_id: str
    calls: list[DatasetDate] = field(default_factory=list)

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        self.calls.append(identity)
        return CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.FAILED_MISSING,
            warning="fixture",
        )


@dataclass
class RecordingTaskCollector:
    dataset_id: str
    store: LegacySqliteSnapshotStore
    calls: list[str] = field(default_factory=list)

    def collect_task(self, task, _started, _lease, **options):
        self.calls.append(task.dataset)
        return self.store.transition_collection_task(
            task.task_id,
            "success",
            expected_statuses=("collecting",),
            source="registry-fixture",
            observations=1,
            timings={"options": options},
            completed_at=AFTER_MARKET,
            settled=True,
        )


def test_complete_registry_routes_all_five_stable_dataset_identifiers() -> None:
    collectors = tuple(RecordingCollector(dataset_id) for dataset_id in DATASET_IDS)
    registry = DatasetCollectorRegistry.complete(collectors)
    identity = DatasetDate("breadth", AS_OF)

    outcome = registry.collect(identity)

    assert registry.dataset_ids == DATASET_IDS
    assert len(registry) == 5
    assert tuple(collector.dataset_id for collector in registry) == DATASET_IDS
    assert outcome.identity == identity
    assert collectors[1].calls == [identity]
    assert all(isinstance(collector, DatasetCollector) for collector in registry)


def test_registry_rejects_unknown_duplicate_and_incomplete_registration() -> None:
    with pytest.raises(ValueError, match="unsupported dataset collector: unknown"):
        DatasetCollectorRegistry((RecordingCollector("unknown"),))

    duplicate = RecordingCollector("core")
    with pytest.raises(ValueError, match="duplicate dataset collector: core"):
        DatasetCollectorRegistry((duplicate, duplicate))

    with pytest.raises(
        ValueError,
        match="missing dataset collectors: breadth, limits, sectors, activeDirection",
    ):
        DatasetCollectorRegistry.complete((RecordingCollector("core"),))

    registry = DatasetCollectorRegistry()
    with pytest.raises(ValueError, match="unknown dataset collector: core"):
        registry.get("core")


def test_legacy_provider_adapter_builds_complete_registry_without_algorithm_move(
    tmp_path,
) -> None:
    provider = CollectionProvider()
    store = LegacySqliteSnapshotStore(tmp_path / "collector-registry.sqlite3")
    registry = build_provider_collector_registry(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    outcome = registry.collect(DatasetDate("breadth", AS_OF))

    assert registry.dataset_ids == DATASET_IDS
    assert outcome.state is CollectionTaskState.SUCCESS
    assert outcome.candidate is not None
    assert outcome.candidate.source == "fixture"
    assert provider.calls == ["breadth"]


def test_collection_coordinator_invokes_task_collector_through_registry(tmp_path) -> None:
    provider = CollectionProvider()
    store = LegacySqliteSnapshotStore(tmp_path / "task-collector-registry.sqlite3")
    collectors = tuple(
        RecordingTaskCollector(dataset_id, store) for dataset_id in DATASET_IDS
    )
    registry = DatasetCollectorRegistry.complete(collectors)
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda *_args, **_kwargs: None,
        fuyao_config=FuyaoCollectionConfig(datasets={}),
        collector_registry=registry,
    )

    result = coordinator.collect(AS_OF, ("breadth",))

    assert result.run.status == "success"
    assert collectors[1].calls == ["breadth"]
    assert all(not collector.calls for collector in collectors if collector is not collectors[1])
    assert provider.calls == []
    assert not {
        "_collect_chapter_dataset",
        "_collect_core",
        "_collect_limits",
        "_fetch_chapter_dataset",
        "_fetch_fuyao_chapter_dataset",
        "_fuyao_cutover_error",
        "_fuyao_gate_warning",
        "_fuyao_is_enabled",
        "_fuyao_revision",
        "_fuyao_shadow_enabled",
        "_limits_collection_detail",
    } & set(CollectionCoordinator.__dict__)
