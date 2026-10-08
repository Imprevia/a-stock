"""Typed limits commit request construction from local dependency evidence."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from ...application.ports import LimitsCommitRequest
from ...domain.models import (
    AcquisitionTimings,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
)
from ...trading_sessions import TradingDayResolver
from ..providers.limits_acquisition import (
    LIMITS_RULE_VERSION,
    LimitsCollectionCandidate,
)


@dataclass(frozen=True, slots=True)
class LimitsPreviousSessionEvidenceReader:
    """Read exact previous-session and detail evidence without provider I/O."""

    store: Any
    rule_version: str = LIMITS_RULE_VERSION

    def resolve(self, as_of: date):
        return TradingDayResolver(self.store).resolve(as_of)

    def previous_as_of(self, as_of: date) -> date | None:
        resolution = self.resolve(as_of)
        return resolution.previous_as_of if resolution.sufficient else None

    def detail_available(self, as_of: date | None) -> bool | None:
        if as_of is None:
            return None
        manifest = self.store.get_limit_security_dataset(as_of)
        return bool(
            manifest
            and manifest.get("membership_complete") is True
            and manifest.get("actual_as_of") == as_of
            and manifest.get("rule_version") == self.rule_version
        )


@dataclass(slots=True)
class LimitsCommitPreparation:
    """Request-scoped previous-session evidence with deterministic lease release."""

    store: Any
    previous_as_of: date | None
    previous_detail_available: bool | None
    previous_outcome: CollectionOutcome | None = None
    previous_lease: Any | None = None
    warning: str | None = None
    timings: Mapping[str, float] = field(default_factory=dict)

    def __enter__(self) -> "LimitsCommitPreparation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.previous_lease is not None:
            self.store.release_lease(
                "limits",
                self.previous_lease.as_of,
                lease=self.previous_lease,
            )
            self.previous_lease = None


@dataclass(frozen=True, slots=True)
class LimitsPreviousSessionCommitPreparer:
    """Acquire missing previous-session detail before the current collection."""

    store: Any
    acquisition_plan: Any
    previous_sessions: LimitsPreviousSessionEvidenceReader
    enabled: Callable[[], bool]
    now: Callable[[], datetime]
    lease_seconds: float = 600.0

    def prepare(
        self,
        task: Any,
        _current_lease: Any,
        *,
        fetch_previous_limit_details: bool,
    ) -> LimitsCommitPreparation:
        identity = DatasetDate(task.dataset, task.as_of)
        if identity.dataset != "limits":
            raise ValueError("limits commit preparation requires the limits dataset")
        resolution = self.previous_sessions.resolve(identity.as_of)
        previous_as_of = (
            resolution.previous_as_of if resolution.sufficient else None
        )
        available = self.previous_sessions.detail_available(previous_as_of)
        preparation = LimitsCommitPreparation(
            store=self.store,
            previous_as_of=previous_as_of,
            previous_detail_available=available,
        )
        if not self.enabled() or not fetch_previous_limit_details:
            return preparation
        if previous_as_of is None:
            preparation.warning = resolution.reason or "missing session evidence"
            return preparation
        if available:
            return preparation

        lease_started = time.perf_counter()
        previous_lease = self.store.acquire_lease(
            "limits",
            previous_as_of,
            task.task_id,
            lease_seconds=self.lease_seconds,
            now=self.now(),
        )
        preparation.timings = {
            "previousLeaseWaitMs": _milliseconds(lease_started)
        }
        if previous_lease is None:
            preparation.warning = "previous session limit detail lease is busy"
            return preparation
        preparation.previous_lease = previous_lease

        provider_started = time.perf_counter()
        try:
            previous_outcome = self.acquisition_plan.collect(
                DatasetDate("limits", previous_as_of)
            )
        except Exception as exc:
            preparation.warning = f"previous session detail unavailable: {exc}"
            return preparation
        preparation.timings = {
            **dict(preparation.timings),
            "previousProviderCollectionMs": _milliseconds(provider_started),
        }
        candidate = previous_outcome.candidate
        if (
            previous_outcome.state
            not in {CollectionTaskState.SUCCESS, CollectionTaskState.PARTIAL}
            or not isinstance(candidate, LimitsCollectionCandidate)
            or candidate.normalization is None
        ):
            warning = previous_outcome.warning or (
                previous_outcome.failure.message
                if previous_outcome.failure is not None
                else "previous session detail unavailable"
            )
            preparation.warning = f"previous session detail unavailable: {warning}"
            return preparation
        preparation.previous_outcome = previous_outcome
        preparation.previous_detail_available = bool(
            candidate.normalization.membership_complete is True
            and candidate.normalization.actual_as_of == previous_as_of
            and candidate.normalization.rule_version == self.previous_sessions.rule_version
        )
        if not preparation.previous_detail_available:
            preparation.warning = "previous session normalized detail is unavailable"
        return preparation


@dataclass(frozen=True, slots=True)
class LimitsCommitRequestFactory:
    """Create the specialized fenced limits request from a typed outcome."""

    previous_sessions: LimitsPreviousSessionEvidenceReader

    def __call__(
        self,
        task: Any,
        outcome: CollectionOutcome,
        lease: Any,
        preparation: LimitsCommitPreparation | None = None,
    ) -> LimitsCommitRequest:
        identity = DatasetDate(task.dataset, task.as_of)
        if identity.dataset != "limits" or outcome.identity != identity:
            raise ValueError("limits commit request factory identity mismatch")
        candidate = outcome.candidate
        if not isinstance(candidate, LimitsCollectionCandidate):
            raise TypeError("limits acquisition must return a typed limits candidate")
        if candidate.normalization is None:
            raise ValueError("limits acquisition candidate is missing normalization")
        previous_as_of = candidate.previous_as_of
        if previous_as_of is None:
            previous_as_of = self.previous_sessions.previous_as_of(identity.as_of)
        previous_detail_available = self.previous_sessions.detail_available(
            previous_as_of
        )
        previous_candidate = None
        previous_normalization = None
        previous_lease = None
        if preparation is not None:
            previous_as_of = preparation.previous_as_of
            previous_detail_available = preparation.previous_detail_available
            if preparation.previous_outcome is not None:
                previous_candidate = preparation.previous_outcome.candidate
                if not isinstance(previous_candidate, LimitsCollectionCandidate):
                    raise TypeError(
                        "limits previous acquisition must return a typed limits candidate"
                    )
                previous_normalization = previous_candidate.normalization
                previous_lease = preparation.previous_lease
            if preparation.warning:
                outcome = replace(
                    outcome,
                    state=CollectionTaskState.PARTIAL,
                    warning="; ".join(
                        dict.fromkeys(
                            value
                            for value in (outcome.warning, preparation.warning)
                            if value
                        )
                    ),
                )
            if preparation.timings:
                candidate = replace(
                    candidate,
                    timings=AcquisitionTimings(
                        total_ms=candidate.timings.total_ms,
                        phases_ms={
                            **dict(candidate.timings.phases_ms),
                            **dict(preparation.timings),
                        },
                    ),
                )
                outcome = replace(outcome, candidate=candidate)
        return LimitsCommitRequest(
            identity=identity,
            outcome=outcome,
            lease=lease,
            normalization=candidate.normalization,
            previous_as_of=previous_as_of,
            previous_detail_available=previous_detail_available,
            previous_candidate=previous_candidate,
            previous_normalization=previous_normalization,
            previous_lease=previous_lease,
        )


def _milliseconds(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = [
    "LimitsCommitRequestFactory",
    "LimitsCommitPreparation",
    "LimitsPreviousSessionEvidenceReader",
    "LimitsPreviousSessionCommitPreparer",
]
