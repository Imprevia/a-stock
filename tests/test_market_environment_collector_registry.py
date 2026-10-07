from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.market_environment.application.collection import DatasetCollectorRegistry
from src.market_environment.application.ports import DatasetCollector
from src.market_environment.domain.models import (
    DATASET_IDS,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.compatibility import (
    build_legacy_provider_collector_registry,
)
from src.market_environment.infrastructure.persistence.sqlite_import import (
    LegacySqliteSnapshotStore,
)
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
    registry = build_legacy_provider_collector_registry(
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
