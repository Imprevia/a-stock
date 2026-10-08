"""Typed commit contract for the core index dataset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ...domain.models import CollectionTaskState
from .committers import DatasetCommitEvidence, DatasetCommitRequest


@dataclass(frozen=True, slots=True)
class CoreIndexCommitEvidence:
    """One independently collected or same-date-retained core index result."""

    code: str
    name: str
    state: CollectionTaskState
    source: str
    observations: int
    payload: Mapping[str, Any] | None
    warning: str | None = None
    duration_ms: float | None = None
    retained: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip() or not self.source.strip():
            raise ValueError("core index commit evidence requires code, name and source")
        if self.observations < 0:
            raise ValueError("core index observations must be non-negative")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("core index duration must be non-negative")
        if self.state not in {
            CollectionTaskState.SUCCESS,
            CollectionTaskState.FAILED_RETAINED,
            CollectionTaskState.FAILED_MISSING,
        }:
            raise ValueError(f"unsupported core index commit state: {self.state.value}")
        if self.state is CollectionTaskState.FAILED_MISSING:
            if self.payload is not None or self.retained:
                raise ValueError("failed-missing core index evidence cannot carry payload")
        elif self.payload is None:
            raise ValueError("successful or retained core index evidence requires payload")
        if self.retained != (self.state is CollectionTaskState.FAILED_RETAINED):
            raise ValueError("core index retained flag must match failed-retained state")


@dataclass(frozen=True, slots=True)
class CoreTradingSessionEvidence:
    """Exact-date trading-session evidence derived from core histories."""

    as_of: date
    previous_as_of: date | None
    is_session: bool
    source: str
    actual_as_of: date
    fetched_at: datetime
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("core trading-session source must not be empty")
        if self.actual_as_of != self.as_of:
            raise ValueError("core trading-session actual date must match its date")
        if self.previous_as_of is not None and self.previous_as_of >= self.as_of:
            raise ValueError("previous core trading session must precede its date")
        if self.fetched_at.tzinfo is None:
            raise ValueError("core trading-session fetch time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CoreCommitRequest(DatasetCommitRequest):
    """Atomic core write set selected by collection orchestration."""

    task_id: str
    index_results: tuple[CoreIndexCommitEvidence, ...]
    completed_at: datetime
    session: CoreTradingSessionEvidence | None = None
    previous_session: CoreTradingSessionEvidence | None = None
    session_warning: str | None = None
    task_timings: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        DatasetCommitRequest.__post_init__(self)
        if self.identity.dataset != "core":
            raise ValueError("core commit request requires the core dataset")
        if not self.task_id.strip() or self.task_id != self.lease.owner:
            raise ValueError("core commit task must own the active lease")
        if self.completed_at.tzinfo is None:
            raise ValueError("core commit completion time must be timezone-aware")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("core commit duration must be non-negative")
        if not self.index_results:
            raise ValueError("core commit requires index sub-results")
        codes = tuple(result.code for result in self.index_results)
        if len(set(codes)) != len(codes):
            raise ValueError("core commit index codes must be unique")
        if self.session is None:
            if not self.session_warning or not self.session_warning.strip():
                raise ValueError("missing core session evidence requires a warning")
            if self.previous_session is not None:
                raise ValueError("previous core session requires current session evidence")
        elif self.session.as_of != self.identity.as_of:
            raise ValueError("core session evidence must match the requested date")
        elif self.session.previous_as_of is None:
            if self.previous_session is not None:
                raise ValueError("unexpected previous core session evidence")
        elif (
            self.previous_session is None
            or self.previous_session.as_of != self.session.previous_as_of
        ):
            raise ValueError("core commit requires matching previous session evidence")

        payload_indices = self.candidate.payload.get("indices")
        if not isinstance(payload_indices, (list, tuple)):
            raise ValueError("core candidate requires an indices payload")
        indexed_payload: dict[str, Mapping[str, Any]] = {}
        for value in payload_indices:
            if not isinstance(value, Mapping) or not str(value.get("code") or "").strip():
                raise ValueError("core candidate indices require stable codes")
            code = str(value["code"])
            if code in indexed_payload:
                raise ValueError("core candidate index codes must be unique")
            indexed_payload[code] = value
        for result in self.index_results:
            candidate_payload = indexed_payload.get(result.code)
            if result.payload is None:
                if candidate_payload is not None:
                    raise ValueError("failed-missing core index cannot enter the snapshot")
            elif candidate_payload is None or dict(candidate_payload) != dict(result.payload):
                raise ValueError("core index evidence must match the candidate payload")
        expected_codes = {
            result.code for result in self.index_results if result.payload is not None
        }
        if set(indexed_payload) != expected_codes:
            raise ValueError("core candidate contains unaccounted index payloads")
        failed = tuple(
            result
            for result in self.index_results
            if result.state is not CollectionTaskState.SUCCESS
        )
        if self.outcome.state is CollectionTaskState.SUCCESS and failed:
            raise ValueError("successful core outcome cannot contain failed sub-results")


@dataclass(frozen=True, slots=True)
class CoreCommitEvidence(DatasetCommitEvidence):
    """Committed core transaction evidence returned to the coordinator."""

    task_id: str
    index_results: tuple[CoreIndexCommitEvidence, ...]
    session: CoreTradingSessionEvidence | None
    previous_session: CoreTradingSessionEvidence | None
    snapshot_checksum: str

    def __post_init__(self) -> None:
        DatasetCommitEvidence.__post_init__(self)
        if self.identity.dataset != "core":
            raise ValueError("core commit evidence requires the core dataset")
        if not self.task_id.strip():
            raise ValueError("core commit evidence requires a task id")
        if not self.index_results:
            raise ValueError("core commit evidence requires index sub-results")
        if len(self.snapshot_checksum) != 64 or any(
            value not in "0123456789abcdef" for value in self.snapshot_checksum.lower()
        ):
            raise ValueError("core snapshot checksum must be a SHA-256 digest")


__all__ = [
    "CoreCommitEvidence",
    "CoreCommitRequest",
    "CoreIndexCommitEvidence",
    "CoreTradingSessionEvidence",
]
