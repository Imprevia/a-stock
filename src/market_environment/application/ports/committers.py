"""Typed persistence boundary for normalized dataset collection outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from ...domain.models import (
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)


@runtime_checkable
class DatasetCommitFence(Protocol):
    """Minimum lease identity required to authorize a dataset commit."""

    dataset: str
    as_of: date
    owner: str
    generation: int
    token: str


@dataclass(frozen=True, slots=True)
class DatasetCommitRequest:
    """One normalized candidate-bearing outcome authorized by an active lease."""

    identity: DatasetDate
    outcome: CollectionOutcome
    lease: DatasetCommitFence = field(repr=False)

    def __post_init__(self) -> None:
        if self.outcome.identity != self.identity:
            raise ValueError("dataset commit outcome identity mismatch")
        if self.outcome.state not in {
            CollectionTaskState.SUCCESS,
            CollectionTaskState.PARTIAL,
            CollectionTaskState.FAILED_RETAINED,
        }:
            raise ValueError(
                "dataset commit requires a successful, partial, or retained outcome"
            )
        if (
            self.outcome.state is CollectionTaskState.FAILED_RETAINED
            and not self.outcome.retained
        ):
            raise ValueError("failed-retained dataset commits require retained evidence")
        candidate = self.outcome.candidate
        if candidate is None or candidate.identity != self.identity:
            raise ValueError("dataset commit requires a matching candidate")
        if not isinstance(self.lease, DatasetCommitFence):
            raise TypeError("dataset commit requires a typed lease fence")
        if (
            self.lease.dataset != self.identity.dataset
            or self.lease.as_of != self.identity.as_of
        ):
            raise ValueError("dataset commit lease identity mismatch")
        if not self.lease.owner.strip() or not self.lease.token.strip():
            raise ValueError("dataset commit lease owner and token are required")
        if self.lease.generation < 1:
            raise ValueError("dataset commit lease generation must be positive")

    @property
    def candidate(self) -> CollectionCandidate:
        candidate = self.outcome.candidate
        assert candidate is not None
        return candidate


@dataclass(frozen=True, slots=True)
class DatasetCommitEvidence:
    """Typed evidence describing the local write set produced by a committer."""

    identity: DatasetDate
    outcome_state: CollectionTaskState
    candidate: CollectionCandidate
    writes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.candidate.identity != self.identity:
            raise ValueError("dataset commit evidence candidate identity mismatch")
        if self.outcome_state not in {
            CollectionTaskState.SUCCESS,
            CollectionTaskState.PARTIAL,
            CollectionTaskState.FAILED_RETAINED,
        }:
            raise ValueError("dataset commit evidence requires a committed outcome state")
        if not self.writes or any(not value.strip() for value in self.writes):
            raise ValueError("dataset commit evidence requires a non-empty write set")
        if len(set(self.writes)) != len(self.writes):
            raise ValueError("dataset commit evidence write set must not contain duplicates")


@runtime_checkable
class DatasetCommitter(Protocol):
    dataset_id: str

    def commit(self, request: DatasetCommitRequest) -> DatasetCommitEvidence: ...


__all__ = [
    "DatasetCommitEvidence",
    "DatasetCommitFence",
    "DatasetCommitRequest",
    "DatasetCommitter",
]
