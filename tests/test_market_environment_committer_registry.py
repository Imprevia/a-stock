from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from src.market_environment.application.collection import DatasetCommitterRegistry
from src.market_environment.application.ports import (
    DatasetCommitRequest,
    DatasetCommitter,
)
from src.market_environment.domain.models import (
    DATASET_IDS,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.collection import (
    STANDARD_SNAPSHOT_DATASETS,
    StandardSnapshotCommitter,
)


AS_OF = date(2026, 9, 3)


@dataclass(frozen=True)
class Lease:
    dataset: str
    as_of: date
    owner: str = "task-fixture"
    generation: int = 1
    token: str = "secret-lease-token"


class SnapshotRepository:
    def __init__(self) -> None:
        self.puts: list[CollectionCandidate] = []

    def put(self, candidate: CollectionCandidate) -> CollectionCandidate:
        self.puts.append(candidate)
        return candidate


class LeaseRepository:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.calls: list[tuple[object, str, DatasetDate]] = []

    def execute_fenced(
        self,
        lease,
        operation,
        writer,
        *,
        expected_identity=None,
    ):
        self.calls.append((lease, operation, expected_identity))
        if self.reject:
            raise RuntimeError("lease fenced")
        return writer(object())


class UnitOfWork:
    def __init__(self, *, reject_lease: bool = False) -> None:
        self.snapshots = SnapshotRepository()
        self.leases = LeaseRepository(reject=reject_lease)
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None or self.commits == 0:
            self.rollbacks += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class UnitOfWorkFactory:
    def __init__(self, *, reject_lease: bool = False) -> None:
        self.reject_lease = reject_lease
        self.calls = 0
        self.units: list[UnitOfWork] = []

    def __call__(self) -> UnitOfWork:
        self.calls += 1
        unit = UnitOfWork(reject_lease=self.reject_lease)
        self.units.append(unit)
        return unit


@dataclass
class StubCommitter:
    dataset_id: str

    def commit(self, request):
        raise AssertionError(f"unexpected commit for {request.identity.dataset}")


def commit_request(dataset: str = "breadth") -> DatasetCommitRequest:
    identity = DatasetDate(dataset, AS_OF)
    candidate = CollectionCandidate(
        identity=identity,
        payload={"asOf": AS_OF.isoformat(), "value": 1},
        source="fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
    )
    return DatasetCommitRequest(
        identity=identity,
        outcome=CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.SUCCESS,
            candidate=candidate,
        ),
        lease=Lease(dataset, AS_OF),
    )


def complete_committers(factory: UnitOfWorkFactory):
    return tuple(
        StandardSnapshotCommitter(dataset, factory)
        if dataset in STANDARD_SNAPSHOT_DATASETS
        else StubCommitter(dataset)
        for dataset in DATASET_IDS
    )


def test_complete_registry_routes_all_stable_datasets_to_typed_committers() -> None:
    factory = UnitOfWorkFactory()
    registry = DatasetCommitterRegistry.complete(complete_committers(factory))

    evidence = registry.commit(commit_request())

    assert registry.dataset_ids == DATASET_IDS
    assert tuple(committer.dataset_id for committer in registry) == DATASET_IDS
    assert all(isinstance(committer, DatasetCommitter) for committer in registry)
    assert evidence.identity == DatasetDate("breadth", AS_OF)
    assert evidence.outcome_state is CollectionTaskState.SUCCESS
    assert evidence.writes == ("snapshot",)
    assert factory.calls == 1
    assert factory.units[0].snapshots.puts == [evidence.candidate]
    assert factory.units[0].commits == 1
    assert factory.units[0].rollbacks == 0
    assert factory.units[0].leases.calls == [
        (commit_request().lease, "snapshot_commit", evidence.identity)
    ]


def test_registry_rejects_unknown_duplicate_and_missing_committers_before_writes() -> None:
    factory = UnitOfWorkFactory()

    with pytest.raises(ValueError, match="unsupported dataset committer: unknown"):
        DatasetCommitterRegistry((StubCommitter("unknown"),))

    core = StubCommitter("core")
    with pytest.raises(ValueError, match="duplicate dataset committer: core"):
        DatasetCommitterRegistry((core, core))

    with pytest.raises(
        ValueError,
        match="missing dataset committers: breadth, limits, sectors, activeDirection",
    ):
        DatasetCommitterRegistry.complete((core,))

    incomplete = DatasetCommitterRegistry((core,))
    with pytest.raises(ValueError, match="unknown dataset committer: breadth"):
        incomplete.commit(commit_request("breadth"))

    assert factory.calls == 0


def test_standard_committer_rejects_datasets_with_specialized_write_sets() -> None:
    factory = UnitOfWorkFactory()

    for dataset in ("core", "limits"):
        with pytest.raises(
            ValueError,
            match=f"dataset requires a specialized committer: {dataset}",
        ):
            StandardSnapshotCommitter(dataset, factory)

    assert factory.calls == 0


def test_commit_request_and_committer_reject_identity_mismatch_before_uow() -> None:
    factory = UnitOfWorkFactory()
    request = commit_request("breadth")

    with pytest.raises(ValueError, match="lease identity mismatch"):
        DatasetCommitRequest(
            identity=request.identity,
            outcome=request.outcome,
            lease=Lease("sectors", AS_OF),
        )

    with pytest.raises(ValueError, match="dataset committer identity mismatch"):
        StandardSnapshotCommitter("sectors", factory).commit(request)

    assert factory.calls == 0


def test_standard_snapshot_committer_rolls_back_when_fence_rejects_write() -> None:
    factory = UnitOfWorkFactory(reject_lease=True)
    committer = StandardSnapshotCommitter("breadth", factory)

    with pytest.raises(RuntimeError, match="lease fenced"):
        committer.commit(commit_request())

    assert factory.calls == 1
    assert factory.units[0].snapshots.puts == []
    assert factory.units[0].commits == 0
    assert factory.units[0].rollbacks == 1
