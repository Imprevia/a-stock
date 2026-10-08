from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from src.market_environment.application.collection import (
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
)
from src.market_environment.application.ports import DatasetCommitEvidence
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DATASET_IDS,
    DatasetDate,
)
from src.market_environment.infrastructure.collection import CollectionCoordinator
from src.market_environment.refresh import MARKET_TIME_ZONE
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


AS_OF = date(2026, 9, 14)
NOW = datetime(2026, 9, 14, 15, 20, tzinfo=MARKET_TIME_ZONE)


def successful(identity: DatasetDate) -> CollectionOutcome:
    candidate = CollectionCandidate(
        identity=identity,
        payload={
            "asOf": identity.as_of.isoformat(),
            "quality": {
                "dataset": identity.dataset,
                "source": "typed-fixture",
                "provider": "fixture",
                "status": "ok",
                "observations": 1,
                "asOf": identity.as_of.isoformat(),
                "warnings": [],
            },
        },
        source="typed-fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=identity.as_of,
        fetched_at=NOW,
    )
    return CollectionOutcome(identity, CollectionTaskState.SUCCESS, candidate=candidate)


def failed(identity: DatasetDate) -> CollectionOutcome:
    failure = AcquisitionFailure(
        AcquisitionFailureCategory.NETWORK,
        "typed fixture unavailable",
        requested_as_of=identity.as_of,
    )
    return CollectionOutcome(
        identity,
        CollectionTaskState.FAILED_MISSING,
        warning=failure.message,
        failure=failure,
    )


@dataclass
class Collector:
    dataset_id: str
    failures: frozenset[str]
    calls: list[DatasetDate] = field(default_factory=list)

    def collect(self, identity):
        self.calls.append(identity)
        return failed(identity) if self.dataset_id in self.failures else successful(identity)


@dataclass
class Committer:
    dataset_id: str
    store: SnapshotStore
    calls: list[object] = field(default_factory=list)

    def commit(self, request):
        self.calls.append(request)
        candidate = request.candidate
        self.store.put(
            SnapshotRecord(
                dataset=candidate.identity.dataset,
                as_of=candidate.identity.as_of,
                payload=dict(candidate.payload),
                source=candidate.source,
                status=candidate.status,
                observations=candidate.observations,
                warnings=candidate.warnings,
                fetched_at=NOW,
                settled=candidate.settled,
            ),
            lease=request.lease,
            now=NOW,
        )
        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=candidate,
            writes=("snapshot",),
        )


def coordinator(tmp_path, *, failures=frozenset(), rebuild=None):
    store = SnapshotStore(tmp_path / "typed-coordinator.sqlite3")
    collectors = tuple(Collector(dataset, failures) for dataset in DATASET_IDS)
    committers = tuple(Committer(dataset, store) for dataset in DATASET_IDS)
    value = CollectionCoordinator(
        None,
        store,
        now=lambda: NOW,
        rebuild_aggregate=rebuild,
        collector_registry=DatasetCollectorRegistry.complete(collectors),
        committer_registry=DatasetCommitterRegistry.complete(committers),
        typed_cutover_datasets=DATASET_IDS,
    )
    return value, store, collectors, committers


def test_typed_coordinator_collects_commits_and_rebuilds_once(tmp_path) -> None:
    rebuilds: list[date] = []
    value, store, collectors, committers = coordinator(
        tmp_path,
        rebuild=rebuilds.append,
    )

    result = value.collect(AS_OF, ("breadth",))

    assert result.tasks[0].status == "success"
    assert result.tasks[0].source == "typed-fixture"
    assert store.get("breadth", AS_OF) is not None
    assert collectors[1].calls == [DatasetDate("breadth", AS_OF)]
    assert len(committers[1].calls) == 1
    assert rebuilds == [AS_OF]


def test_typed_coordinator_derives_same_date_retention_and_isolates_siblings(tmp_path) -> None:
    rebuilds: list[date] = []
    value, store, collectors, committers = coordinator(
        tmp_path,
        failures=frozenset({"sectors"}),
        rebuild=rebuilds.append,
    )
    store.put(
        SnapshotRecord(
            dataset="sectors",
            as_of=AS_OF,
            payload={"asOf": AS_OF.isoformat(), "quality": {}},
            source="retained-source",
            status="ok",
            observations=1,
            warnings=(),
            fetched_at=NOW,
            settled=True,
        )
    )

    result = value.collect(AS_OF, ("breadth", "sectors"))
    tasks = {task.dataset: task for task in result.tasks}

    assert tasks["breadth"].status == "success"
    assert tasks["sectors"].status == "failed-retained"
    assert "typed fixture unavailable" in tasks["sectors"].warning
    assert store.get("sectors", AS_OF).source == "retained-source"
    assert len(committers[1].calls) == 1
    assert committers[3].calls == []
    assert rebuilds == [AS_OF, AS_OF]
    assert collectors[1].calls == [DatasetDate("breadth", AS_OF)]
    assert collectors[3].calls == [DatasetDate("sectors", AS_OF)]


def test_coordinator_source_contains_no_signature_reflection() -> None:
    source = Path(
        "src/market_environment/infrastructure/collection/coordinator.py"
    ).read_text(encoding="utf-8")

    assert "inspect.signature" not in source
