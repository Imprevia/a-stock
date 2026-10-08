from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.market_environment.application.collection import (
    AcquisitionPlanRegistry,
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
    SourceAdapterRegistry,
)
from src.market_environment.application.ports import (
    AcquisitionPlanStep,
    DatasetCommitEvidence,
    SourceCapability,
)
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    AcquisitionTimings,
    CollectionCandidate,
    DATASET_IDS,
    DatasetDate,
)
from src.market_environment.infrastructure.collection import (
    CollectionCoordinator,
    build_plan_collector_registry,
)
from src.market_environment.infrastructure.providers import (
    CompatibilitySourceAdapter,
    DeterministicAcquisitionPlan,
)
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 14)
NOW = datetime(2026, 9, 14, 15, 20, tzinfo=MARKET_TIME_ZONE)


def candidate(identity: DatasetDate) -> CollectionCandidate:
    return CollectionCandidate(
        identity=identity,
        payload={
            "asOf": identity.as_of.isoformat(),
            "quality": {
                "dataset": identity.dataset,
                "source": "parity-source",
                "provider": "fixture",
                "status": "partial",
                "observations": 3,
                "asOf": identity.as_of.isoformat(),
                "warnings": ["shared warning"],
            },
        },
        source="parity-source",
        status="partial",
        observations=3,
        warnings=("shared warning",),
        settled=True,
        actual_as_of=identity.as_of,
        fetched_at=NOW,
        timings=AcquisitionTimings(
            total_ms=12.5,
            phases_ms={"normalizeMs": 2.0},
        ),
    )


@dataclass
class TypedAdapter:
    source_id: str
    capability: SourceCapability
    calls: int = 0

    def acquire(self, request):
        self.calls += 1
        return candidate(request.identity)


@dataclass
class FailingAdapter:
    source_id: str
    capability: SourceCapability
    calls: int = 0

    def acquire(self, request):
        self.calls += 1
        return AcquisitionFailure(
            AcquisitionFailureCategory.NETWORK,
            "isolated sibling failure",
            source=self.source_id,
            requested_as_of=request.identity.as_of,
        )


@dataclass
class SnapshotCommitter:
    dataset_id: str
    store: SnapshotStore
    calls: int = 0

    def commit(self, request):
        self.calls += 1
        value = request.candidate
        self.store.put(
            SnapshotRecord(
                dataset=value.identity.dataset,
                as_of=value.identity.as_of,
                payload=dict(value.payload),
                source=value.source,
                status=value.status,
                observations=value.observations,
                warnings=value.warnings,
                fetched_at=value.fetched_at or NOW,
                settled=value.settled,
            ),
            lease=request.lease,
            now=NOW,
        )
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=value,
            writes=("snapshot",),
        )


@dataclass
class LegacyTaskCollector:
    dataset_id: str
    store: SnapshotStore
    failure: str | None = None
    calls: int = 0

    def collect_task(
        self,
        task,
        started,
        lease,
        *,
        fetch_previous_limit_details=True,
    ):
        del started, fetch_previous_limit_details
        self.calls += 1
        if self.failure is not None:
            raise RuntimeError(self.failure)
        payload = {
            "asOf": task.as_of.isoformat(),
            "quality": {
                "dataset": task.dataset,
                "source": f"legacy-{task.dataset}",
                "provider": "legacy-fixture",
                "status": "ok",
                "observations": 5,
                "asOf": task.as_of.isoformat(),
                "warnings": ["legacy warning"],
            },
        }
        self.store.put(
            SnapshotRecord(
                dataset=task.dataset,
                as_of=task.as_of,
                payload=payload,
                source=f"legacy-{task.dataset}",
                status="ok",
                observations=5,
                warnings=("legacy warning",),
                fetched_at=NOW,
                settled=True,
            ),
            lease=lease,
            now=NOW,
        )
        return self.store.transition_collection_task(
            task.task_id,
            "success",
            expected_statuses=("collecting",),
            source=f"legacy-{task.dataset}",
            observations=5,
            warning="legacy warning",
            timings={"providerCollectionMs": 7.0},
            completed_at=NOW,
            duration_ms=8.0,
            settled=True,
        )


def test_parent_run_keeps_public_parity_across_mixed_adapter_paths(tmp_path) -> None:
    calls = {"compatibility": 0}
    typed = TypedAdapter(
        "typed-breadth",
        SourceCapability("typed-breadth", "fixture", "r1"),
    )

    def fetch_compatibility(request):
        calls["compatibility"] += 1
        return request.identity

    compatibility = CompatibilitySourceAdapter(
        "legacy-sectors",
        SourceCapability("legacy-sectors", "fixture", "r1"),
        fetch=fetch_compatibility,
        normalize=lambda raw, _request: candidate(raw),
    )
    failing = FailingAdapter(
        "legacy-active-direction",
        SourceCapability("legacy-active-direction", "fixture", "r1"),
    )

    adapter_by_dataset = {
        "breadth": typed,
        "sectors": compatibility,
        "activeDirection": failing,
    }
    for dataset in ("core", "limits"):
        adapter_by_dataset[dataset] = TypedAdapter(
            f"typed-{dataset}",
            SourceCapability(f"typed-{dataset}", "fixture", "r1"),
        )
    adapters = SourceAdapterRegistry(adapter_by_dataset.values())
    plans = AcquisitionPlanRegistry.complete(
        (
            DeterministicAcquisitionPlan(
                dataset,
                f"{dataset}-plan-v1",
                (AcquisitionPlanStep(adapter_by_dataset[dataset].source_id),),
                adapters,
            )
            for dataset in DATASET_IDS
        ),
        source_adapters=adapters,
    )
    store = SnapshotStore(tmp_path / "mixed-paths.sqlite3")
    coordinator = CollectionCoordinator(
        None,
        store,
        now=lambda: NOW,
        rebuild_aggregate=lambda _as_of: None,
        collector_registry=build_plan_collector_registry(plans),
        committer_registry=DatasetCommitterRegistry.complete(
            SnapshotCommitter(dataset, store) for dataset in DATASET_IDS
        ),
        typed_cutover_datasets=DATASET_IDS,
    )

    result = coordinator.collect(
        AS_OF,
        ("breadth", "sectors", "activeDirection"),
    )
    public = coordinator.get_run(result.run.run_id)
    assert public is not None
    tasks = {task.dataset: task for task in public.tasks}

    assert public.run.status == "partial"
    for dataset in ("breadth", "sectors"):
        task = tasks[dataset]
        assert task.status == "partial"
        assert task.source == "parity-source"
        assert task.observations == 3
        assert task.warning == "shared warning"
        assert {
            key: value
            for key, value in task.timings.items()
            if key != "aggregateRebuildMs"
        } == {
            "normalizeMs": 2.0,
            "providerCollectionMs": 12.5,
        }
        assert task.timings["aggregateRebuildMs"] >= 0
    assert (
        tasks["breadth"].status,
        tasks["breadth"].source,
        tasks["breadth"].observations,
        tasks["breadth"].warning,
    ) == (
        tasks["sectors"].status,
        tasks["sectors"].source,
        tasks["sectors"].observations,
        tasks["sectors"].warning,
    )
    assert tasks["activeDirection"].status == "failed-missing"
    assert tasks["activeDirection"].warning == "isolated sibling failure"
    assert store.get("breadth", AS_OF) is not None
    assert store.get("sectors", AS_OF) is not None

    call_counts = (typed.calls, calls["compatibility"], failing.calls)
    status = coordinator.collection_status(AS_OF)

    assert (typed.calls, calls["compatibility"], failing.calls) == call_counts
    status_by_dataset = {item["dataset"]: item for item in status["datasets"]}
    assert status_by_dataset["breadth"]["source"] == "parity-source"
    assert status_by_dataset["sectors"]["source"] == "parity-source"
    assert status_by_dataset["activeDirection"]["available"] is False


def test_parent_run_mixes_typed_cutover_with_legacy_siblings_provider_free(
    tmp_path,
) -> None:
    typed = TypedAdapter(
        "typed-breadth",
        SourceCapability("typed-breadth", "fixture", "r1"),
    )
    adapter_by_dataset = {"breadth": typed}
    for dataset in ("core", "limits", "sectors", "activeDirection"):
        adapter_by_dataset[dataset] = TypedAdapter(
            f"unused-{dataset}",
            SourceCapability(f"unused-{dataset}", "fixture", "r1"),
        )
    adapters = SourceAdapterRegistry(adapter_by_dataset.values())
    plans = AcquisitionPlanRegistry.complete(
        (
            DeterministicAcquisitionPlan(
                dataset,
                f"{dataset}-plan-v1",
                (AcquisitionPlanStep(adapter_by_dataset[dataset].source_id),),
                adapters,
            )
            for dataset in DATASET_IDS
        ),
        source_adapters=adapters,
    )
    plan_collectors = build_plan_collector_registry(plans)
    store = SnapshotStore(tmp_path / "mixed-collector-paths.sqlite3")
    legacy_collectors = {
        dataset: LegacyTaskCollector(dataset, store)
        for dataset in DATASET_IDS
        if dataset != "breadth"
    }
    legacy_collectors["activeDirection"].failure = "legacy sibling unavailable"
    collectors = DatasetCollectorRegistry.complete(
        plan_collectors.get(dataset)
        if dataset == "breadth"
        else legacy_collectors[dataset]
        for dataset in DATASET_IDS
    )
    committers = tuple(SnapshotCommitter(dataset, store) for dataset in DATASET_IDS)
    coordinator = CollectionCoordinator(
        None,
        store,
        now=lambda: NOW,
        rebuild_aggregate=lambda _as_of: None,
        collector_registry=collectors,
        committer_registry=DatasetCommitterRegistry.complete(committers),
        typed_cutover_datasets=("breadth",),
    )

    result = coordinator.collect(
        AS_OF,
        ("breadth", "sectors", "activeDirection"),
    )
    public = coordinator.get_run(result.run.run_id)
    assert public is not None
    tasks = {task.dataset: task for task in public.tasks}

    assert public.run.status == "partial"
    assert tasks["breadth"].status == "partial"
    assert tasks["breadth"].source == "parity-source"
    assert tasks["breadth"].observations == 3
    assert tasks["breadth"].warning == "shared warning"
    assert tasks["breadth"].timings["normalizeMs"] == 2.0
    assert tasks["breadth"].timings["providerCollectionMs"] == 12.5
    assert tasks["sectors"].status == "success"
    assert tasks["sectors"].source == "legacy-sectors"
    assert tasks["sectors"].observations == 5
    assert tasks["sectors"].warning == "legacy warning"
    assert tasks["sectors"].timings["providerCollectionMs"] == 7.0
    assert tasks["activeDirection"].status == "failed-missing"
    assert tasks["activeDirection"].source == "none"
    assert tasks["activeDirection"].observations == 0
    assert tasks["activeDirection"].warning == "legacy sibling unavailable"
    assert tasks["activeDirection"].timings["leaseWaitMs"] >= 0
    assert "providerCollectionMs" not in tasks["activeDirection"].timings
    assert typed.calls == 1
    assert committers[1].calls == 1
    assert legacy_collectors["sectors"].calls == 1
    assert legacy_collectors["activeDirection"].calls == 1

    calls_before_poll = (
        typed.calls,
        legacy_collectors["sectors"].calls,
        legacy_collectors["activeDirection"].calls,
    )
    status = coordinator.collection_status(AS_OF)

    assert calls_before_poll == (
        typed.calls,
        legacy_collectors["sectors"].calls,
        legacy_collectors["activeDirection"].calls,
    )
    status_by_dataset = {item["dataset"]: item for item in status["datasets"]}
    assert status_by_dataset["breadth"]["source"] == "parity-source"
    assert status_by_dataset["sectors"]["source"] == "legacy-sectors"
    assert status_by_dataset["activeDirection"]["available"] is False
