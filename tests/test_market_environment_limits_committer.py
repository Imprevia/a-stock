from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

import pytest

from src.market_environment.application.ports.limits_committers import LimitsCommitRequest
from src.market_environment.domain.models import (
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from src.market_environment.infrastructure.collection.committers import LimitsDatasetCommitter
from src.market_environment.limit_facts import LimitNormalizationResult, LimitSecurityFactRecord


AS_OF = date(2026, 9, 14)
PREVIOUS = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Lease:
    dataset: str = "limits"
    as_of: date = AS_OF
    owner: str = "task-limits"
    generation: int = 1
    token: str = "lease-secret"


class TransactionState:
    def __init__(self) -> None:
        self.details: dict[date, tuple[dict, tuple[object, ...]]] = {}
        self.snapshots: dict[DatasetDate, CollectionCandidate] = {}


class DetailRepository:
    def __init__(self, values) -> None:
        self.values = values

    def put_limit_detail(self, as_of, manifest, facts) -> None:
        self.values[as_of] = (dict(manifest), tuple(facts))


class SnapshotRepository:
    def __init__(self, values, *, fail_as_of: date | None) -> None:
        self.values = values
        self.fail_as_of = fail_as_of

    def put(self, candidate):
        if candidate.identity.as_of == self.fail_as_of:
            raise RuntimeError("snapshot write failed")
        self.values[candidate.identity] = candidate
        return candidate


class LeaseRepository:
    def __init__(self, *, stale_as_of: date | None) -> None:
        self.stale_as_of = stale_as_of
        self.writer_calls = 0

    def execute_fenced(self, lease, operation, writer, *, expected_identity=None):
        if lease.as_of == self.stale_as_of:
            raise RuntimeError("lease fenced")
        self.writer_calls += 1
        return writer(object())


class UnitOfWork:
    def __init__(
        self,
        state,
        *,
        stale_as_of: date | None,
        fail_snapshot_as_of: date | None,
    ) -> None:
        self.state = state
        self.working_details = copy.deepcopy(state.details)
        self.working_snapshots = copy.deepcopy(state.snapshots)
        self.limit_details = DetailRepository(self.working_details)
        self.snapshots = SnapshotRepository(
            self.working_snapshots,
            fail_as_of=fail_snapshot_as_of,
        )
        self.leases = LeaseRepository(stale_as_of=stale_as_of)
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if not self.committed:
            self.rolled_back = True

    def commit(self) -> None:
        self.state.details = self.working_details
        self.state.snapshots = self.working_snapshots
        self.committed = True


class UnitOfWorkFactory:
    def __init__(
        self,
        *,
        stale: bool = False,
        stale_as_of: date | None = None,
        fail_snapshot: bool = False,
        fail_snapshot_as_of: date | None = None,
    ) -> None:
        self.state = TransactionState()
        self.stale_as_of = AS_OF if stale else stale_as_of
        self.fail_snapshot_as_of = (
            AS_OF if fail_snapshot else fail_snapshot_as_of
        )
        self.units: list[UnitOfWork] = []

    def __call__(self):
        unit = UnitOfWork(
            self.state,
            stale_as_of=self.stale_as_of,
            fail_snapshot_as_of=self.fail_snapshot_as_of,
        )
        self.units.append(unit)
        return unit


def request() -> LimitsCommitRequest:
    identity = DatasetDate("limits", AS_OF)
    candidate = CollectionCandidate(
        identity=identity,
        payload={
            "asOf": AS_OF.isoformat(),
            "limitUpCount": 1,
            "quality": {
                "dataset": "limit-pools",
                "source": "fixture",
                "provider": "fixture",
                "status": "ok",
                "observations": 1,
                "asOf": AS_OF.isoformat(),
                "warnings": [],
            },
        },
        source="fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
        fetched_at=FETCHED_AT,
    )
    fact = LimitSecurityFactRecord(
        as_of=AS_OF,
        actual_as_of=AS_OF,
        security_id="SSE:600000",
        pool_type="limit_up",
        code="600000",
        exchange="SSE",
        name="示例股份",
        closed_limit_up=True,
        streak_days=2,
        eligible=True,
        source="fixture",
        fetched_at=FETCHED_AT,
    ).normalized()
    normalization = LimitNormalizationResult(
        rows=(fact,),
        as_of=AS_OF,
        actual_as_of=AS_OF,
        source="fixture",
        complete=True,
        source_revision="fixture-v1",
        rule_version="rules-v1",
        membership_complete=True,
        streak_complete=True,
        pool_quality={"status": "ok"},
    )
    return LimitsCommitRequest(
        identity=identity,
        outcome=CollectionOutcome(
            identity=identity,
            state=CollectionTaskState.SUCCESS,
            candidate=candidate,
        ),
        lease=Lease(),
        normalization=normalization,
        previous_as_of=PREVIOUS,
        previous_detail_available=True,
    )


def request_with_previous_bundle() -> LimitsCommitRequest:
    value = request()
    identity = DatasetDate("limits", PREVIOUS)
    candidate = CollectionCandidate(
        identity=identity,
        payload={
            "asOf": PREVIOUS.isoformat(),
            "limitUpCount": 1,
            "quality": {
                "dataset": "limit-pools",
                "source": "previous-fixture",
                "provider": "previous-fixture",
                "status": "ok",
                "observations": 1,
                "asOf": PREVIOUS.isoformat(),
                "warnings": [],
            },
        },
        source="previous-fixture",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=PREVIOUS,
        fetched_at=FETCHED_AT,
    )
    fact = replace(
        value.normalization.rows[0],
        as_of=PREVIOUS,
        actual_as_of=PREVIOUS,
        source="previous-fixture",
        row_checksum="",
    ).normalized()
    normalization = LimitNormalizationResult(
        rows=(fact,),
        as_of=PREVIOUS,
        actual_as_of=PREVIOUS,
        source="previous-fixture",
        complete=True,
        source_revision="previous-v1",
        rule_version="rules-v1",
        membership_complete=True,
        streak_complete=True,
        pool_quality={"status": "ok"},
    ).normalized()
    return replace(
        value,
        previous_detail_available=True,
        previous_candidate=candidate,
        previous_normalization=normalization,
        previous_lease=Lease(as_of=PREVIOUS, token="previous-token"),
    )


def test_limits_committer_writes_facts_manifest_and_snapshot_atomically() -> None:
    factory = UnitOfWorkFactory()

    evidence = LimitsDatasetCommitter(factory).commit(request())

    assert evidence.writes == ("limit-facts", "limit-manifest", "snapshot")
    assert evidence.fact_count == 1
    assert evidence.previous_as_of == PREVIOUS
    assert evidence.previous_detail_available is True
    assert evidence.manifest.dataset_checksum
    manifest, facts = factory.state.details[AS_OF]
    assert manifest["dataset_checksum"] == evidence.manifest.dataset_checksum
    assert len(facts) == 1
    stored = factory.state.snapshots[DatasetDate("limits", AS_OF)]
    assert stored.payload["quality"]["_detailDatasetChecksum"] == evidence.manifest.dataset_checksum
    assert factory.units[0].committed is True
    assert factory.units[0].leases.writer_calls == 1


def test_limits_committer_rolls_back_detail_when_snapshot_write_fails() -> None:
    factory = UnitOfWorkFactory(fail_snapshot=True)

    with pytest.raises(RuntimeError, match="snapshot write failed"):
        LimitsDatasetCommitter(factory).commit(request())

    assert factory.state.details == {}
    assert factory.state.snapshots == {}
    assert factory.units[0].rolled_back is True


def test_limits_committer_stale_lease_executes_no_partial_write() -> None:
    factory = UnitOfWorkFactory(stale=True)

    with pytest.raises(RuntimeError, match="lease fenced"):
        LimitsDatasetCommitter(factory).commit(request())

    assert factory.state.details == {}
    assert factory.state.snapshots == {}
    assert factory.units[0].leases.writer_calls == 0
    assert factory.units[0].rolled_back is True


def test_limits_committer_commits_current_and_previous_bundles_in_one_uow() -> None:
    factory = UnitOfWorkFactory()

    evidence = LimitsDatasetCommitter(factory).commit(request_with_previous_bundle())

    assert set(factory.state.details) == {PREVIOUS, AS_OF}
    assert set(factory.state.snapshots) == {
        DatasetDate("limits", PREVIOUS),
        DatasetDate("limits", AS_OF),
    }
    assert evidence.previous_manifest is not None
    assert evidence.previous_manifest.as_of == PREVIOUS
    assert evidence.previous_fact_count == 1
    assert factory.units[0].leases.writer_calls == 2
    assert factory.units[0].committed is True


def test_limits_committer_rolls_back_previous_bundle_when_current_snapshot_fails() -> None:
    factory = UnitOfWorkFactory(fail_snapshot_as_of=AS_OF)

    with pytest.raises(RuntimeError, match="snapshot write failed"):
        LimitsDatasetCommitter(factory).commit(request_with_previous_bundle())

    assert factory.state.details == {}
    assert factory.state.snapshots == {}
    assert factory.units[0].leases.writer_calls == 2
    assert factory.units[0].rolled_back is True


def test_limits_committer_stale_previous_lease_rejects_both_bundles() -> None:
    factory = UnitOfWorkFactory(stale_as_of=PREVIOUS)

    with pytest.raises(RuntimeError, match="lease fenced"):
        LimitsDatasetCommitter(factory).commit(request_with_previous_bundle())

    assert factory.state.details == {}
    assert factory.state.snapshots == {}
    assert factory.units[0].leases.writer_calls == 1
    assert factory.units[0].rolled_back is True


def test_limits_commit_request_rejects_mismatched_normalization_date() -> None:
    value = request()
    wrong = LimitNormalizationResult(
        rows=(),
        as_of=PREVIOUS,
        actual_as_of=PREVIOUS,
        source="fixture",
        complete=False,
    )

    with pytest.raises(ValueError, match="normalization date mismatch"):
        LimitsCommitRequest(
            identity=value.identity,
            outcome=value.outcome,
            lease=value.lease,
            normalization=wrong,
        )
