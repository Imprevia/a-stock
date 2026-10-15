"""Application command for the idempotent seven-dataset automation trigger."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from time import monotonic, sleep
from typing import Any
from zoneinfo import ZoneInfo

from ...domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    FullCollectionSemantics,
    IdempotencyBinding,
    IdempotencyClaimDisposition,
    IdempotencyKey,
    SubmissionState,
)
from ..ports import CollectionQueryPort
from .collection import (
    RecoverableCollectionSubmissionService,
    RecoverableSubmissionResult,
)


_TERMINAL_RUN_STATUSES = frozenset({"success", "partial", "failed"})
_SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class FullCollectionSkippedResult:
    """Provider-free result for a Shanghai weekend invocation."""

    resolved_as_of: date
    reason: str = "weekend"
    message: str = "full collection is skipped on Shanghai weekends"
    datasets: tuple[str, ...] = CANONICAL_FULL_COLLECTION_DATASETS
    status: str = "skipped"
    run_id: None = None


@dataclass(frozen=True, slots=True)
class FullCollectionRunResult:
    """One created or replayed durable full-collection run."""

    semantics: FullCollectionSemantics
    claim_disposition: IdempotencyClaimDisposition
    binding: IdempotencyBinding
    run: Any
    submission: RecoverableSubmissionResult | None

    @property
    def resolved_as_of(self) -> date:
        return self.semantics.resolved_as_of

    @property
    def datasets(self) -> tuple[str, ...]:
        return self.semantics.datasets

    @property
    def run_id(self) -> str:
        return self.binding.run_id


class FullCollectionBeforeSettlementError(ValueError):
    """The current Shanghai weekday has not reached its settlement boundary."""

    code = "before-settlement"

    def __init__(
        self,
        *,
        current: datetime,
        settlement_boundary: time,
    ) -> None:
        self.current = current
        self.resolved_as_of = current.date()
        self.settlement_boundary = settlement_boundary
        super().__init__(
            "full collection is unavailable before the Shanghai settlement time "
            f"{settlement_boundary.isoformat(timespec='minutes')}"
        )


class FullCollectionIdempotencyConflictError(RuntimeError):
    """The key already belongs to another semantic full-collection request."""

    code = "idempotency-key-conflict"

    def __init__(
        self,
        *,
        binding: IdempotencyBinding,
        requested: FullCollectionSemantics,
    ) -> None:
        self.binding = binding
        self.requested = requested
        super().__init__(
            "idempotency key is already bound to a different full-collection request"
        )


@dataclass(frozen=True, slots=True)
class FullCollectionCommand:
    """Resolve Shanghai time, atomically claim one run, and recover its submission."""

    unit_of_work_factory: Callable[[], Any]
    submission_service: RecoverableCollectionSubmissionService
    queries: CollectionQueryPort
    clock: Callable[[], datetime]
    settlement_boundary: time
    identifier_factory: Callable[[], str] = lambda: uuid.uuid4().hex
    monotonic_clock: Callable[[], float] = monotonic
    sleeper: Callable[[float], None] = sleep
    poll_interval_seconds: float = 1.0

    def execute(
        self,
        key: IdempotencyKey,
    ) -> FullCollectionSkippedResult | FullCollectionRunResult:
        if not isinstance(key, IdempotencyKey):
            raise TypeError("full collection requires a validated IdempotencyKey")

        current = self._shanghai_now()
        resolved_as_of = current.date()
        if current.weekday() >= 5:
            return FullCollectionSkippedResult(resolved_as_of=resolved_as_of)
        if current.time().replace(tzinfo=None) < self.settlement_boundary:
            raise FullCollectionBeforeSettlementError(
                current=current,
                settlement_boundary=self.settlement_boundary,
            )

        semantics = FullCollectionSemantics.create(resolved_as_of)
        run_id = self._new_identifier()
        task_ids = {
            dataset: self._new_identifier()
            for dataset in semantics.datasets
        }
        with self.unit_of_work_factory() as unit_of_work:
            claim = unit_of_work.collection_idempotency.claim(
                key,
                semantics,
                run_id=run_id,
                task_ids=task_ids,
                now=current.astimezone(timezone.utc),
            )
            unit_of_work.commit()

        if claim.disposition is IdempotencyClaimDisposition.CONFLICT:
            raise FullCollectionIdempotencyConflictError(
                binding=claim.binding,
                requested=semantics,
            )

        original_run = self.queries.get_run(claim.binding.run_id)
        if original_run is None:
            raise RuntimeError("claimed full-collection run cannot be read")

        submission: RecoverableSubmissionResult | None = None
        if not (
            claim.disposition is IdempotencyClaimDisposition.REPLAY
            and claim.binding.submission_state is SubmissionState.SUBMITTED
            and self._is_terminal(original_run)
        ):
            submission = self.submission_service.submit(
                semantics.operation_scope,
                key,
                claim.binding.run_id,
            )
            observed = self.queries.get_run(claim.binding.run_id)
            if observed is None:
                raise RuntimeError("submitted full-collection run cannot be read")
            original_run = observed

        return FullCollectionRunResult(
            semantics=semantics,
            claim_disposition=claim.disposition,
            binding=submission.binding if submission is not None else claim.binding,
            run=original_run,
            submission=submission,
        )

    def wait(self, run_id: str, timeout_seconds: float) -> Any | None:
        """Poll only persisted state; timing out never cancels submitted work."""

        if not str(run_id).strip():
            raise ValueError("collection run id is required")
        if not 0 <= timeout_seconds <= 900:
            raise ValueError("wait timeout must be between 0 and 900 seconds")
        if self.poll_interval_seconds <= 0:
            raise ValueError("full-collection poll interval must be positive")

        latest = self.queries.get_run(run_id)
        if latest is None or self._is_terminal(latest) or timeout_seconds == 0:
            return latest

        deadline = self.monotonic_clock() + timeout_seconds
        while True:
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                return latest
            self.sleeper(min(self.poll_interval_seconds, remaining))
            observed = self.queries.get_run(run_id)
            if observed is None:
                return None
            latest = observed
            if self._is_terminal(latest):
                return latest

    def _shanghai_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=_SHANGHAI_TIME_ZONE)
        return value.astimezone(_SHANGHAI_TIME_ZONE)

    def _new_identifier(self) -> str:
        value = str(self.identifier_factory()).strip()
        if not value:
            raise ValueError("full-collection identifiers must not be empty")
        return value

    @staticmethod
    def _is_terminal(result: Any) -> bool:
        run = getattr(result, "run", result)
        return getattr(run, "status", None) in _TERMINAL_RUN_STATUSES


__all__ = [
    "FullCollectionBeforeSettlementError",
    "FullCollectionCommand",
    "FullCollectionIdempotencyConflictError",
    "FullCollectionRunResult",
    "FullCollectionSkippedResult",
]
