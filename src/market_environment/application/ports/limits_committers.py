"""Typed limits dataset commit request and evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from ...domain.policies import LimitNormalizationResult
from .committers import (
    DatasetCommitEvidence,
    DatasetCommitFence,
    DatasetCommitRequest,
)
from ...domain.models import CollectionCandidate, DatasetDate


@dataclass(frozen=True, slots=True)
class LimitsManifestEvidence:
    as_of: date
    actual_as_of: date
    source: str
    source_revision: str | None
    rule_version: str | None
    complete: bool
    membership_complete: bool | None
    streak_complete: bool | None
    pool_quality: Mapping[str, Any] | None
    excluded: int
    warnings: tuple[str, ...]
    dataset_checksum: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        if self.actual_as_of != self.as_of:
            raise ValueError("limits manifest requires an exact actual date")
        if not self.source.strip() or not self.dataset_checksum.strip():
            raise ValueError("limits manifest source and checksum are required")
        if self.excluded < 0:
            raise ValueError("limits manifest excluded count must be non-negative")

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "as_of": self.as_of,
            "actual_as_of": self.actual_as_of,
            "source": self.source,
            "source_revision": self.source_revision,
            "rule_version": self.rule_version,
            "complete": self.complete,
            "membership_complete": self.membership_complete,
            "streak_complete": self.streak_complete,
            "pool_quality": dict(self.pool_quality) if self.pool_quality is not None else None,
            "excluded": self.excluded,
            "warnings": self.warnings,
            "dataset_checksum": self.dataset_checksum,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True, slots=True)
class LimitsCommitRequest(DatasetCommitRequest):
    normalization: LimitNormalizationResult
    previous_as_of: date | None = None
    previous_detail_available: bool | None = None
    previous_candidate: CollectionCandidate | None = None
    previous_normalization: LimitNormalizationResult | None = None
    previous_lease: DatasetCommitFence | None = None

    def __post_init__(self) -> None:
        super(LimitsCommitRequest, self).__post_init__()
        if self.identity.dataset != "limits":
            raise ValueError("limits commit request requires the limits dataset")
        if (
            self.normalization.as_of != self.identity.as_of
            or self.normalization.actual_as_of != self.identity.as_of
        ):
            raise ValueError("limits commit normalization date mismatch")
        if any(
            fact.as_of != self.identity.as_of
            or fact.actual_as_of != self.identity.as_of
            for fact in self.normalization.rows
        ):
            raise ValueError("limits commit facts must use the exact requested date")
        if self.previous_as_of is not None and self.previous_as_of >= self.identity.as_of:
            raise ValueError("limits previous-session dependency must precede the requested date")
        previous_values = (
            self.previous_candidate,
            self.previous_normalization,
            self.previous_lease,
        )
        if any(value is not None for value in previous_values) and not all(
            value is not None for value in previous_values
        ):
            raise ValueError(
                "limits previous-session bundle requires candidate, normalization, and lease"
            )
        if self.previous_candidate is not None:
            assert self.previous_normalization is not None
            assert self.previous_lease is not None
            if self.previous_as_of is None:
                raise ValueError("limits previous-session bundle requires previous_as_of")
            previous_identity = DatasetDate("limits", self.previous_as_of)
            if self.previous_candidate.identity != previous_identity:
                raise ValueError("limits previous candidate identity mismatch")
            if (
                self.previous_normalization.as_of != self.previous_as_of
                or self.previous_normalization.actual_as_of != self.previous_as_of
            ):
                raise ValueError("limits previous normalization date mismatch")
            if (
                self.previous_lease.dataset != "limits"
                or self.previous_lease.as_of != self.previous_as_of
            ):
                raise ValueError("limits previous lease identity mismatch")


@dataclass(frozen=True, slots=True)
class LimitsCommitEvidence(DatasetCommitEvidence):
    manifest: LimitsManifestEvidence
    fact_count: int
    previous_as_of: date | None
    previous_detail_available: bool | None
    snapshot_checksum: str
    previous_manifest: LimitsManifestEvidence | None = None
    previous_fact_count: int | None = None

    def __post_init__(self) -> None:
        super(LimitsCommitEvidence, self).__post_init__()
        if self.identity.dataset != "limits" or self.manifest.as_of != self.identity.as_of:
            raise ValueError("limits commit evidence identity mismatch")
        if self.fact_count < 0:
            raise ValueError("limits commit fact count must be non-negative")
        if not self.snapshot_checksum.strip():
            raise ValueError("limits commit snapshot checksum is required")
        if self.previous_manifest is not None:
            if self.previous_as_of != self.previous_manifest.as_of:
                raise ValueError("limits previous manifest identity mismatch")
            if self.previous_fact_count is None or self.previous_fact_count < 0:
                raise ValueError("limits previous fact count must be non-negative")


__all__ = [
    "LimitsCommitEvidence",
    "LimitsCommitRequest",
    "LimitsManifestEvidence",
]
