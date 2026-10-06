"""Typed cross-layer values for market-environment workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping


DATASET_IDS = (
    "core",
    "breadth",
    "limits",
    "sectors",
    "activeDirection",
)


class CacheState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


class CollectionRunState(str, Enum):
    QUEUED = "queued"
    COLLECTING = "collecting"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class CollectionTaskState(str, Enum):
    QUEUED = "queued"
    COLLECTING = "collecting"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED_RETAINED = "failed-retained"
    FAILED_MISSING = "failed-missing"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class DatasetDate:
    dataset: str
    as_of: date

    def __post_init__(self) -> None:
        if self.dataset not in DATASET_IDS:
            raise ValueError(f"unsupported market-environment dataset: {self.dataset}")


@dataclass(frozen=True, slots=True)
class CacheMetadata:
    state: CacheState | None = None
    snapshot_fetched_at: datetime | None = None
    refreshing: bool | None = None
    refresh_warning: str | None = None


@dataclass(frozen=True, slots=True)
class QualityMetadata:
    dataset: str
    source: str
    provider: str
    status: str
    observations: int
    as_of: date | None = None
    warning: str | None = None
    warnings: tuple[str, ...] = ()
    cache: CacheMetadata | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observations < 0:
            raise ValueError("quality observations must be non-negative")


@dataclass(frozen=True, slots=True)
class CollectionCandidate:
    identity: DatasetDate
    payload: Mapping[str, Any]
    source: str
    status: str
    observations: int
    warnings: tuple[str, ...]
    settled: bool
    actual_as_of: date | None = None
    quality: QualityMetadata | None = None

    def __post_init__(self) -> None:
        if self.observations < 0:
            raise ValueError("candidate observations must be non-negative")


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    identity: DatasetDate
    state: CollectionTaskState
    candidate: CollectionCandidate | None = None
    warning: str | None = None
    retained: bool = False

    def __post_init__(self) -> None:
        if self.retained and self.state is not CollectionTaskState.FAILED_RETAINED:
            raise ValueError("retained outcomes must use failed-retained state")
        if self.state in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL} and self.candidate is None:
            raise ValueError("successful or partial outcomes require a candidate")


@dataclass(frozen=True, slots=True)
class MaterializationRevision:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("materialization revision must not be empty")


__all__ = [
    "CacheMetadata",
    "CacheState",
    "CollectionCandidate",
    "CollectionOutcome",
    "CollectionRunState",
    "CollectionTaskState",
    "DATASET_IDS",
    "DatasetDate",
    "MaterializationRevision",
    "QualityMetadata",
]
