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


class AcquisitionFailureCategory(str, Enum):
    """Stable failure vocabulary shared by plans, adapters and transport."""

    CONFIGURATION = "configuration"
    ENGINE_UNAVAILABLE = "engine-unavailable"
    NETWORK = "network"
    RATE_LIMIT = "rate-limit"
    PERMISSION = "permission"
    CHALLENGE = "challenge"
    CONTRACT = "contract"
    DATE_MISMATCH = "date-mismatch"
    INSUFFICIENT = "insufficient"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class FieldAvailability:
    """Evidence for fields that were available, missing or unsupported."""

    available: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (*self.available, *self.missing, *self.unsupported):
            if not str(name).strip():
                raise ValueError("field availability names must not be empty")


@dataclass(frozen=True, slots=True)
class AcquisitionTimings:
    """Redaction-safe timing evidence; values are milliseconds unless noted."""

    total_ms: float | None = None
    phases_ms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_ms is not None and self.total_ms < 0:
            raise ValueError("total acquisition timing must be non-negative")
        if any(float(value) < 0 for value in self.phases_ms.values()):
            raise ValueError("acquisition phase timings must be non-negative")


@dataclass(frozen=True, slots=True)
class RedactedProvenance:
    """Safe provenance identity without credentials or raw response bodies."""

    endpoint: str | None = None
    engine: str | None = None
    request_id: str | None = None
    authentication_scope_digest: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttemptEvidence:
    """One formal, fallback, shadow or enrichment acquisition attempt."""

    role: str
    provider: str
    source: str
    source_revision: str | None = None
    engine: str | None = None
    requested_as_of: date | None = None
    actual_as_of: date | None = None
    category: AcquisitionFailureCategory | None = None
    status_code: int | None = None
    warning: str | None = None
    timings: AcquisitionTimings = field(default_factory=AcquisitionTimings)
    provenance: RedactedProvenance = field(default_factory=RedactedProvenance)
    evidence_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"formal", "fallback", "shadow", "enrichment"}:
            raise ValueError(f"unsupported acquisition attempt role: {self.role}")
        if not self.provider.strip() or not self.source.strip():
            raise ValueError("acquisition attempt provider and source are required")


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """Classified failure returned when an adapter cannot produce a candidate."""

    category: AcquisitionFailureCategory
    message: str
    retryable: bool = False
    source: str | None = None
    source_revision: str | None = None
    requested_as_of: date | None = None
    fetched_at: datetime | None = None
    timings: AcquisitionTimings = field(default_factory=AcquisitionTimings)
    provenance: RedactedProvenance = field(default_factory=RedactedProvenance)
    evidence_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("acquisition failure message must not be empty")


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
    source_revision: str | None = None
    fetched_at: datetime | None = None
    field_availability: FieldAvailability = field(default_factory=FieldAvailability)
    timings: AcquisitionTimings = field(default_factory=AcquisitionTimings)
    evidence_fingerprint: str | None = None
    provenance: RedactedProvenance = field(default_factory=RedactedProvenance)

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
    source_revision: str | None = None
    fetched_at: datetime | None = None
    field_availability: FieldAvailability = field(default_factory=FieldAvailability)
    timings: AcquisitionTimings = field(default_factory=AcquisitionTimings)
    evidence_fingerprint: str | None = None
    provenance: RedactedProvenance = field(default_factory=RedactedProvenance)

    def __post_init__(self) -> None:
        if self.observations < 0:
            raise ValueError("candidate observations must be non-negative")
        if not self.source.strip():
            raise ValueError("candidate source must not be empty")
        if self.actual_as_of is not None and self.actual_as_of != self.identity.as_of:
            raise ValueError("candidate actual date must match requested date")


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    identity: DatasetDate
    state: CollectionTaskState
    candidate: CollectionCandidate | None = None
    warning: str | None = None
    retained: bool = False
    failure: AcquisitionFailure | None = None
    attempts: tuple[AttemptEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.retained and self.state is not CollectionTaskState.FAILED_RETAINED:
            raise ValueError("retained outcomes must use failed-retained state")
        if self.state in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL} and self.candidate is None:
            raise ValueError("successful or partial outcomes require a candidate")
        if self.state in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL} and self.failure is not None:
            raise ValueError("successful or partial outcomes cannot carry a terminal failure")
        if self.state in {CollectionTaskState.FAILED_MISSING, CollectionTaskState.FAILED_RETAINED}:
            if self.candidate is not None and self.state is CollectionTaskState.FAILED_MISSING:
                raise ValueError("failed-missing outcomes cannot carry a candidate")
            if self.failure is None and not self.warning:
                raise ValueError("classified failure outcomes require failure evidence or warning")


@dataclass(frozen=True, slots=True)
class MaterializationRevision:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("materialization revision must not be empty")


__all__ = [
    "CacheMetadata",
    "CacheState",
    "AcquisitionFailure",
    "AcquisitionFailureCategory",
    "AcquisitionTimings",
    "AttemptEvidence",
    "CollectionCandidate",
    "CollectionOutcome",
    "CollectionRunState",
    "CollectionTaskState",
    "DATASET_IDS",
    "DatasetDate",
    "FieldAvailability",
    "MaterializationRevision",
    "QualityMetadata",
    "RedactedProvenance",
]
