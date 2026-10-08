from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from src.market_environment.application.collection import DatasetDetailProjectorRegistry
from src.market_environment.domain.models import DATASET_IDS, DatasetDate
from src.market_environment.infrastructure.collection import build_local_detail_projector_registry
from src.market_environment.infrastructure.persistence.sqlite_import import LegacySqliteSnapshotStore


AS_OF = date(2026, 9, 14)


@dataclass
class RecordingProjector:
    dataset_id: str
    calls: list[DatasetDate] = field(default_factory=list)

    def project(self, identity, candidate):
        self.calls.append(identity)
        return {"dataset": identity.dataset, "available": candidate is not None}


def test_detail_projector_registry_is_complete_and_fail_closed() -> None:
    projectors = tuple(RecordingProjector(dataset_id) for dataset_id in DATASET_IDS)
    registry = DatasetDetailProjectorRegistry.complete(projectors)

    assert registry.dataset_ids == DATASET_IDS
    assert registry.project(DatasetDate("core", AS_OF), None) == {
        "dataset": "core",
        "available": False,
    }
    assert projectors[0].calls == [DatasetDate("core", AS_OF)]

    with pytest.raises(ValueError, match="missing dataset detail projectors"):
        DatasetDetailProjectorRegistry.complete(projectors[:-1])
    with pytest.raises(ValueError, match="duplicate dataset detail projector"):
        DatasetDetailProjectorRegistry((*projectors, projectors[0]))
    with pytest.raises(ValueError, match="unknown dataset detail projector"):
        DatasetDetailProjectorRegistry().get("limits")


def test_local_projector_registry_reads_limits_without_provider(tmp_path) -> None:
    store = LegacySqliteSnapshotStore(tmp_path / "projectors.sqlite3")
    registry = build_local_detail_projector_registry(store, limits_enabled=True)

    assert registry.dataset_ids == DATASET_IDS
    assert registry.project(DatasetDate("core", AS_OF), None) is None
    detail = registry.project(DatasetDate("limits", AS_OF), None)
    assert detail is not None
    assert detail["sampleAsOf"] == AS_OF.isoformat()
    assert detail["promotionRequired"] is True
    assert detail["excludedCount"] is None
