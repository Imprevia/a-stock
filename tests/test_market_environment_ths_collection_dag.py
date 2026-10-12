from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from src.market_environment.application.collection import DatasetCollectorRegistry
from src.market_environment.domain.models import DATASET_IDS
from src.market_environment.infrastructure.collection.coordinator import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 10, 12)
AFTER_MARKET = datetime(2026, 10, 12, 15, 20, tzinfo=MARKET_TIME_ZONE)


def _payload(dataset: str) -> dict:
    return {
        "asOf": AS_OF.isoformat(),
        "rows": [],
        "state": "ok",
        "quality": {
            "dataset": dataset,
            "source": "fixture",
            "provider": "fixture",
            "status": "ok",
            "observations": 1,
            "asOf": AS_OF.isoformat(),
            "warnings": [],
        },
    }


@dataclass
class RecordingCollector:
    dataset_id: str
    store: SnapshotStore
    calls: list[str]
    failing: frozenset[str] = frozenset()

    def collect_task(self, task, started, lease, **_kwargs):
        self.calls.append(self.dataset_id)
        if self.dataset_id in self.failing:
            raise RuntimeError(f"{self.dataset_id} failed")
        self.store.put(
            SnapshotRecord(
                dataset=self.dataset_id,
                as_of=task.as_of,
                payload=_payload(self.dataset_id),
                source="fixture",
                status="ok",
                observations=1,
                warnings=(),
                fetched_at=AFTER_MARKET,
                settled=True,
            ),
            lease=lease,
            now=AFTER_MARKET,
        )
        return self.store.transition_collection_task(
            task.task_id,
            "success",
            expected_statuses=("collecting",),
            source="fixture",
            observations=1,
            completed_at=AFTER_MARKET,
            settled=True,
        )


def _coordinator(tmp_path, *, failing=()):
    store = SnapshotStore(tmp_path / "ths-dag.sqlite3")
    calls: list[str] = []
    registry = DatasetCollectorRegistry.complete(
        RecordingCollector(dataset, store, calls, frozenset(failing))
        for dataset in DATASET_IDS
    )
    return CollectionCoordinator(
        store=store,
        collector_registry=registry,
        now=lambda: AFTER_MARKET,
    ), store, calls


def test_sector_breadth_retry_expands_missing_dependencies_in_order(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path)
    result = coordinator.collect(AS_OF, ["sector-breadth"])

    assert result.run.requested_datasets == (
        "industry-ranking",
        "sector-turnover",
        "sector-breadth",
    )
    assert calls == ["industry-ranking", "sector-turnover", "sector-breadth"]
    assert all(task.status == "success" for task in result.tasks)
    assert store.get("sector-breadth", AS_OF) is not None


def test_failed_ranking_blocks_dependents_but_not_independent_siblings(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path, failing={"industry-ranking"})
    result = coordinator.collect(AS_OF, ["breadth", "sector-breadth"])
    tasks = {task.dataset: task for task in result.tasks}

    assert tasks["industry-ranking"].status == "failed-missing"
    assert tasks["sector-turnover"].status == "blocked"
    assert tasks["sector-breadth"].status == "blocked"
    assert tasks["breadth"].status == "success"
    assert calls == ["breadth", "industry-ranking"]
    assert store.get("breadth", AS_OF) is not None
    assert result.run.status == "partial"


def test_breadth_retry_reuses_compatible_local_prerequisites(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path)
    for dataset in ("industry-ranking", "sector-turnover"):
        store.put(
            SnapshotRecord(
                dataset=dataset,
                as_of=AS_OF,
                payload=_payload(dataset),
                source="fixture",
                status="ok",
                observations=1,
                warnings=(),
                fetched_at=AFTER_MARKET,
                settled=True,
            )
        )

    result = coordinator.collect(AS_OF, ["sector-breadth"])
    assert result.run.requested_datasets == ("sector-breadth",)
    assert calls == ["sector-breadth"]


def test_legacy_sectors_is_rejected_with_migration_targets_before_io(tmp_path) -> None:
    coordinator, _store, calls = _coordinator(tmp_path)
    with pytest.raises(
        ValueError,
        match="industry-ranking, sector-turnover, or sector-breadth",
    ):
        coordinator.collect(AS_OF, ["sectors"])
    assert calls == []
