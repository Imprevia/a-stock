from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from src.market_environment.application.collection import DatasetCollectorRegistry
from src.market_environment.domain.models import DATASET_IDS
from src.market_environment.application.ths_diagnostics import parse_ths_diagnostic
from src.market_environment.infrastructure.collection.coordinator import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 10, 12)
AFTER_MARKET = datetime(2026, 10, 12, 15, 20, tzinfo=MARKET_TIME_ZONE)


def _payload(
    dataset: str,
    *,
    status: str = "ok",
    catalog_revision: str = "catalog-r1",
) -> dict:
    payload = {
        "asOf": AS_OF.isoformat(),
        "rows": [],
        "state": status,
        "quality": {
            "dataset": dataset,
            "source": "fixture",
            "provider": "fixture",
            "status": status,
            "observations": 1,
            "asOf": AS_OF.isoformat(),
            "warnings": [],
        },
    }
    if dataset in {"industry-ranking", "sector-turnover", "sector-breadth"}:
        payload["catalogRevisionId"] = catalog_revision
        payload["catalogRevision"] = catalog_revision
    return payload


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
        catalog_revision = "catalog-r1"
        if self.dataset_id in {"sector-turnover", "sector-breadth"}:
            ranking = self.store.get("industry-ranking", task.as_of)
            if ranking is not None:
                catalog_revision = str(
                    ranking.payload.get("catalogRevisionId")
                    or ranking.payload.get("catalogRevision")
                    or catalog_revision
                )
        self.store.put(
            SnapshotRecord(
                dataset=self.dataset_id,
                as_of=task.as_of,
                payload=_payload(
                    self.dataset_id,
                    catalog_revision=catalog_revision,
                ),
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


def test_sector_breadth_blocks_when_turnover_dependency_fails(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path, failing={"sector-turnover"})
    result = coordinator.collect(AS_OF, ["sector-breadth"])

    assert result.run.requested_datasets == (
        "industry-ranking",
        "sector-turnover",
        "sector-breadth",
    )
    assert calls == ["industry-ranking", "sector-turnover"]
    statuses = {task.dataset: task.status for task in result.tasks}
    assert statuses == {
        "industry-ranking": "success",
        "sector-turnover": "failed-missing",
        "sector-breadth": "blocked",
    }
    assert store.get("sector-breadth", AS_OF) is None


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


def test_partial_ranking_is_a_usable_turnover_prerequisite(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path)
    store.put(
        SnapshotRecord(
            dataset="industry-ranking",
            as_of=AS_OF,
            payload=_payload("industry-ranking", status="partial"),
            source="fixture",
            status="partial",
            observations=1,
            warnings=("one declared live-value gap",),
            fetched_at=AFTER_MARKET,
            settled=True,
        )
    )

    result = coordinator.collect(AS_OF, ["sector-turnover"])

    assert result.run.requested_datasets == ("sector-turnover",)
    assert calls == ["sector-turnover"]


def test_breadth_retry_refreshes_revision_mismatched_turnover(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path)
    for dataset, revision in (
        ("industry-ranking", "catalog-r2"),
        ("sector-turnover", "catalog-r1"),
    ):
        store.put(
            SnapshotRecord(
                dataset=dataset,
                as_of=AS_OF,
                payload=_payload(dataset, catalog_revision=revision),
                source="fixture",
                status="ok",
                observations=1,
                warnings=(),
                fetched_at=AFTER_MARKET,
                settled=True,
            )
        )

    result = coordinator.collect(AS_OF, ["sector-breadth"])

    assert result.run.requested_datasets == ("sector-turnover", "sector-breadth")
    assert calls == ["sector-turnover", "sector-breadth"]
    assert store.get("sector-turnover", AS_OF).payload["catalogRevisionId"] == "catalog-r2"


def test_revision_mismatch_block_is_typed_and_lists_both_upstreams(tmp_path) -> None:
    coordinator, store, calls = _coordinator(tmp_path, failing={"sector-turnover"})
    for dataset, revision in (
        ("industry-ranking", "catalog-r2"),
        ("sector-turnover", "catalog-r1"),
    ):
        store.put(
            SnapshotRecord(
                dataset=dataset,
                as_of=AS_OF,
                payload=_payload(dataset, catalog_revision=revision),
                source="fixture",
                status="ok",
                observations=1,
                warnings=(),
                fetched_at=AFTER_MARKET,
                settled=True,
            )
        )
    # Force the targeted turnover refresh to fail so the coordinator must emit
    # a typed block for the incompatible pair rather than silently reusing it.
    result = coordinator.collect(AS_OF, ["sector-breadth"], allow_historical_latest_only=False)
    task = next(item for item in result.tasks if item.dataset == "sector-breadth")
    diagnostic = parse_ths_diagnostic(task.warning)
    assert diagnostic is not None
    assert diagnostic.reason_code == "THS_DEPENDENCY_REVISION_MISMATCH"
    assert {item.dataset for item in diagnostic.blocked_by} == {
        "industry-ranking",
        "sector-turnover",
    }


def test_legacy_sectors_is_rejected_with_migration_targets_before_io(tmp_path) -> None:
    coordinator, _store, calls = _coordinator(tmp_path)
    with pytest.raises(
        ValueError,
        match="industry-ranking, sector-turnover, or sector-breadth",
    ):
        coordinator.collect(AS_OF, ["sectors"])
    assert calls == []
