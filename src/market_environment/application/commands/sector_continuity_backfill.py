"""Explicit, provider-free backfill orchestration for sector continuity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...domain.models.sector_continuity import (
    BackfillDateAttempt,
    BackfillRun,
    SectorContinuityResult,
)


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    as_of: date
    start_as_of: date | None = None
    sessions: int = 272
    calculation_version: str = "sector-continuity-v1"
    source_revisions: Mapping[str, str] = None  # type: ignore[assignment]
    run_id: str | None = None
    repair: bool = False

    def __post_init__(self) -> None:
        if self.sessions < 1:
            raise ValueError("sessions must be at least 1")
        if self.start_as_of is not None and self.start_as_of > self.as_of:
            raise ValueError("start_as_of must not be after as_of")
        if not self.calculation_version.strip():
            raise ValueError("calculation_version is required")


@dataclass(frozen=True, slots=True)
class BackfillReadiness:
    as_of: date
    required_history: int
    available_history: int
    missing_sessions: tuple[date, ...]
    coverage: float
    calculation_version: str | None
    warnings: tuple[str, ...] = ()
    latest_attempt: BackfillDateAttempt | None = None


class SectorContinuityBackfillService:
    """Run only over an explicit finite list of authoritative sessions.

    ``session_reader`` and ``processor`` are injected so ordinary GETs never
    acquire data.  A processor may return a result or raise; failures are
    isolated to that date and retained in the attempt log.
    """

    def __init__(
        self,
        repository: Any,
        *,
        session_reader: Callable[[date, int], Sequence[date]],
        processor: Callable[[date, Mapping[str, str]], SectorContinuityResult],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.session_reader = session_reader
        self.processor = processor
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve_sessions(self, request: BackfillRequest) -> tuple[date, ...]:
        sessions = tuple(sorted(set(self.session_reader(request.as_of, request.sessions))))
        if request.start_as_of is not None:
            sessions = tuple(item for item in sessions if item >= request.start_as_of)
        sessions = tuple(item for item in sessions if item <= request.as_of)
        if not sessions:
            raise ValueError("no authoritative trading sessions in requested range")
        return sessions

    def run(self, request: BackfillRequest) -> BackfillRun:
        sessions = self.resolve_sessions(request)
        now = self.clock()
        run_id = request.run_id or f"sector-backfill-{request.as_of.isoformat()}-{request.calculation_version}"
        run = BackfillRun(
            run_id=run_id,
            as_of=sessions[-1],
            session_dates=sessions,
            source_revisions=dict(request.source_revisions or {}),
            calculation_version=request.calculation_version,
            status="running",
        )
        if hasattr(self.repository, "put_backfill_run"):
            self.repository.put_backfill_run(run)
        attempts: list[BackfillDateAttempt] = []
        completed_dates = 0
        previous_attempts = {
            attempt.as_of: attempt
            for attempt in (
                self.repository.list_backfill_attempts(run_id)
                if hasattr(self.repository, "list_backfill_attempts")
                else ()
            )
        }
        for session in sessions:
            previous = previous_attempts.get(session)
            if previous is not None and previous.status == "success" and not request.repair:
                attempts.append(previous)
                completed_dates += 1
                continue
            try:
                result = self.processor(session, request.source_revisions or {})
                if result.as_of != session:
                    raise ValueError("processor returned a different as_of")
                if hasattr(self.repository, "put_result"):
                    self.repository.put_result(result)
                checksum = result.lineage.checksum
                attempt_status = "success" if result.status == "ok" else "partial" if result.status == "partial" else "insufficient"
                completed_dates += attempt_status in {"success", "partial", "insufficient"}
                attempt = BackfillDateAttempt(run_id, session, attempt_status, now, self.clock(), True, None, checksum)
            except Exception as exc:
                retained = self.repository.get_result(session, request.calculation_version) if hasattr(self.repository, "get_result") else None
                status = "failed-retained" if retained is not None else "failed-missing"
                attempt = BackfillDateAttempt(run_id, session, status, now, self.clock(), True, str(exc), getattr(getattr(retained, "lineage", None), "checksum", None))
            attempts.append(attempt)
            if hasattr(self.repository, "put_backfill_attempt"):
                self.repository.put_backfill_attempt(attempt)
        all_success = all(attempt.status == "success" for attempt in attempts)
        status = "success" if all_success else "partial" if completed_dates else "failed"
        completed = BackfillRun(
            run_id=run_id,
            as_of=sessions[-1],
            session_dates=sessions,
            source_revisions=dict(request.source_revisions or {}),
            calculation_version=request.calculation_version,
            status=status,
            attempts=tuple(attempts),
        )
        if hasattr(self.repository, "put_backfill_run"):
            self.repository.put_backfill_run(completed)
        return completed

    def readiness(self, as_of: date, *, required_history: int = 272, calculation_version: str | None = None) -> BackfillReadiness:
        available: set[date] = set()
        if hasattr(self.repository, "list_result_dates"):
            available = set(self.repository.list_result_dates(as_of=as_of, calculation_version=calculation_version))
        elif hasattr(self.repository, "list_results"):
            available = {item.as_of for item in self.repository.list_results(as_of, calculation_version=calculation_version)}
        required = tuple(sorted(set(self.session_reader(as_of, required_history))))
        required = tuple(item for item in required if item <= as_of)[-required_history:]
        missing = tuple(item for item in required if item not in available)
        coverage = len(required) and len(required) - len(missing)
        return BackfillReadiness(
            as_of=as_of,
            required_history=len(required),
            available_history=len(required) - len(missing),
            missing_sessions=missing,
            coverage=(coverage / len(required)) if required else 0.0,
            calculation_version=calculation_version,
            warnings=("backfill is explicit; readiness never triggers provider I/O",),
        )


__all__ = ["BackfillReadiness", "BackfillRequest", "SectorContinuityBackfillService"]
