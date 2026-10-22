"""Bounded, explicit maintenance for exact-date breadth history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..ports import (
    AggregateCommandPort,
    CollectionCommandPort,
    CollectionRefreshRequest,
    MaterializedAggregateReader,
    SnapshotReader,
    TradingSessionReader,
)
from ...domain.models import CollectionFailureCategory


MAX_BREADTH_HISTORY_DATES = 20
BREADTH_HISTORY_WINDOW = 250
AGGREGATE_REBUILD_BATCH_SIZE = 25

_UNAVAILABLE_CATEGORIES = frozenset(
    {
        CollectionFailureCategory.ENGINE_UNAVAILABLE,
        CollectionFailureCategory.NETWORK,
        CollectionFailureCategory.RATE_LIMIT,
        CollectionFailureCategory.PERMISSION,
        CollectionFailureCategory.CHALLENGE,
    }
)


@dataclass(frozen=True, slots=True)
class BreadthHistoryMaintenanceRequest:
    """Closed input contract validated before provider execution."""

    dates: tuple[date, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    apply: bool = False
    allow_real_provider: bool = False
    allow_snapshot_writes: bool = False

    def __post_init__(self) -> None:
        normalized_dates = tuple(sorted(set(self.dates)))
        object.__setattr__(self, "dates", normalized_dates)
        has_explicit_dates = bool(normalized_dates)
        has_any_range = self.start_date is not None or self.end_date is not None
        if has_explicit_dates == has_any_range:
            raise ValueError(
                "provide either repeatable --date values or --start-date/--end-date"
            )
        if has_any_range and (self.start_date is None or self.end_date is None):
            raise ValueError("--start-date and --end-date must be provided together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("--start-date cannot be later than --end-date")
        if len(normalized_dates) > MAX_BREADTH_HISTORY_DATES:
            raise ValueError(
                f"breadth history maintenance is limited to {MAX_BREADTH_HISTORY_DATES} dates"
            )
        if self.apply and not (
            self.allow_real_provider and self.allow_snapshot_writes
        ):
            raise ValueError(
                "--apply requires both --allow-real-provider and --allow-snapshot-writes"
            )


@dataclass(frozen=True, slots=True)
class BreadthHistoryMaintenanceFailure:
    as_of: date
    stage: str
    category: str
    message: str
    run_id: str | None = None
    task_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asOf": self.as_of.isoformat(),
            "stage": self.stage,
            "category": self.category,
            "message": self.message,
            "runId": self.run_id,
            "taskId": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class BreadthHistoryMaintenanceResult:
    mode: str
    eligible: tuple[date, ...]
    succeeded: tuple[date, ...] = ()
    retained: tuple[date, ...] = ()
    unavailable: tuple[date, ...] = ()
    failed: tuple[date, ...] = ()
    rebuilt_aggregates: tuple[date, ...] = ()
    failures: tuple[BreadthHistoryMaintenanceFailure, ...] = ()
    aggregate_failures: tuple[BreadthHistoryMaintenanceFailure, ...] = ()
    provider_calls: int | None = None
    formal_writes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "planned" if self.mode == "dry-run" else self._apply_status(),
            "mode": self.mode,
            "maximumDates": MAX_BREADTH_HISTORY_DATES,
            "eligible": [item.isoformat() for item in self.eligible],
            "succeeded": [item.isoformat() for item in self.succeeded],
            "retained": [item.isoformat() for item in self.retained],
            "unavailable": [item.isoformat() for item in self.unavailable],
            "failed": [item.isoformat() for item in self.failed],
            "rebuiltAggregates": [
                item.isoformat() for item in self.rebuilt_aggregates
            ],
            "failures": [item.as_dict() for item in self.failures],
            "aggregateFailures": [
                item.as_dict() for item in self.aggregate_failures
            ],
            "providerCalls": self.provider_calls,
            "formalWrites": self.formal_writes,
        }

    def _apply_status(self) -> str:
        if self.failed or self.unavailable or self.aggregate_failures:
            return "partial" if self.succeeded or self.retained else "failed"
        return "success"


@dataclass(slots=True)
class BreadthHistoryMaintenanceService:
    """Plan locally or apply sequentially through the collection coordinator."""

    trading_sessions: TradingSessionReader
    snapshots: SnapshotReader
    aggregates: MaterializedAggregateReader
    collection: CollectionCommandPort
    aggregate: AggregateCommandPort
    _last_eligible: tuple[date, ...] = field(default=(), init=False, repr=False)

    def execute(
        self,
        request: BreadthHistoryMaintenanceRequest,
    ) -> BreadthHistoryMaintenanceResult:
        eligible = self._resolve_eligible(request)
        self._last_eligible = eligible
        if not request.apply:
            return BreadthHistoryMaintenanceResult(
                mode="dry-run",
                eligible=eligible,
                provider_calls=0,
                formal_writes=0,
            )

        succeeded: list[date] = []
        retained: list[date] = []
        unavailable: list[date] = []
        failed: list[date] = []
        failures: list[BreadthHistoryMaintenanceFailure] = []

        for as_of in eligible:
            try:
                result = self.collection.refresh_request(
                    CollectionRefreshRequest(
                        as_of=as_of,
                        datasets=("breadth",),
                        allow_historical_latest_only=True,
                    )
                )
                task = self._breadth_task(result)
                status = str(getattr(task, "status", "failed-missing"))
                if status in {"success", "partial"}:
                    succeeded.append(as_of)
                    continue
                if status == "failed-retained":
                    retained.append(as_of)
                elif self._is_unavailable(task):
                    unavailable.append(as_of)
                else:
                    failed.append(as_of)
                failures.append(self._task_failure(as_of, result, task))
            except Exception as exc:
                failed.append(as_of)
                failures.append(
                    BreadthHistoryMaintenanceFailure(
                        as_of=as_of,
                        stage="collection",
                        category="internal",
                        message=str(exc),
                    )
                )

        rebuilt, aggregate_failures = self._rebuild_dependents(tuple(succeeded))
        return BreadthHistoryMaintenanceResult(
            mode="apply",
            eligible=eligible,
            succeeded=tuple(succeeded),
            retained=tuple(retained),
            unavailable=tuple(unavailable),
            failed=tuple(failed),
            rebuilt_aggregates=rebuilt,
            failures=tuple(failures),
            aggregate_failures=aggregate_failures,
        )

    def _resolve_eligible(
        self,
        request: BreadthHistoryMaintenanceRequest,
    ) -> tuple[date, ...]:
        sessions = {
            item.as_of: item
            for item in self.trading_sessions.list_sessions()
            if getattr(item, "as_of", None) is not None
        }
        if request.dates:
            eligible = request.dates
        else:
            assert request.start_date is not None and request.end_date is not None
            self._require_session(request.start_date, sessions)
            self._require_session(request.end_date, sessions)
            eligible = tuple(
                sorted(
                    as_of
                    for as_of, item in sessions.items()
                    if request.start_date <= as_of <= request.end_date
                    and bool(getattr(item, "is_session", False))
                )
            )
        for as_of in eligible:
            self._require_session(as_of, sessions)
        if not eligible:
            raise ValueError("breadth history maintenance resolved no trading sessions")
        if len(eligible) > MAX_BREADTH_HISTORY_DATES:
            raise ValueError(
                f"breadth history maintenance is limited to {MAX_BREADTH_HISTORY_DATES} dates"
            )
        return eligible

    @staticmethod
    def _require_session(as_of: date, sessions: dict[date, Any]) -> None:
        value = sessions.get(as_of)
        if value is None or not bool(getattr(value, "is_session", False)):
            raise ValueError(f"not a confirmed trading session: {as_of.isoformat()}")

    @staticmethod
    def _breadth_task(result: Any) -> Any:
        for task in tuple(getattr(result, "tasks", ())):
            if getattr(task, "dataset", None) == "breadth":
                return task
        raise ValueError("breadth collection result did not contain a breadth task")

    @staticmethod
    def _is_unavailable(task: Any) -> bool:
        failure = getattr(task, "failure", None)
        return getattr(failure, "category", None) in _UNAVAILABLE_CATEGORIES

    @staticmethod
    def _task_failure(as_of: date, result: Any, task: Any) -> BreadthHistoryMaintenanceFailure:
        failure = getattr(task, "failure", None)
        category = getattr(failure, "category", "internal")
        if hasattr(category, "value"):
            category = category.value
        message = (
            getattr(failure, "message", None)
            or getattr(task, "warning", None)
            or "breadth history collection failed"
        )
        run = getattr(result, "run", None)
        return BreadthHistoryMaintenanceFailure(
            as_of=as_of,
            stage=str(getattr(failure, "stage", None) or "collection"),
            category=str(category),
            message=str(message),
            run_id=getattr(run, "run_id", None),
            task_id=getattr(task, "task_id", None),
        )

    def _rebuild_dependents(
        self,
        succeeded: tuple[date, ...],
    ) -> tuple[
        tuple[date, ...],
        tuple[BreadthHistoryMaintenanceFailure, ...],
    ]:
        if not succeeded:
            return (), ()
        successful_dates = set(succeeded)
        breadth_dates = tuple(self.snapshots.list_dates("breadth"))
        affected: list[date] = []
        for aggregate_date in sorted(self.aggregates.list_dates()):
            if aggregate_date in successful_dates:
                continue
            recent = tuple(
                sorted(
                    (
                        snapshot_date
                        for snapshot_date in breadth_dates
                        if snapshot_date <= aggregate_date
                    ),
                    reverse=True,
                )[:BREADTH_HISTORY_WINDOW]
            )
            if successful_dates.intersection(recent):
                affected.append(aggregate_date)

        rebuilt: list[date] = []
        failures: list[BreadthHistoryMaintenanceFailure] = []
        for offset in range(0, len(affected), AGGREGATE_REBUILD_BATCH_SIZE):
            batch = affected[offset : offset + AGGREGATE_REBUILD_BATCH_SIZE]
            for as_of in batch:
                try:
                    self.aggregate.rebuild(as_of)
                    rebuilt.append(as_of)
                except Exception as exc:
                    failures.append(
                        BreadthHistoryMaintenanceFailure(
                            as_of=as_of,
                            stage="aggregate-rebuild",
                            category="internal",
                            message=str(exc),
                        )
                    )
        return tuple(rebuilt), tuple(failures)


__all__ = [
    "AGGREGATE_REBUILD_BATCH_SIZE",
    "BREADTH_HISTORY_WINDOW",
    "MAX_BREADTH_HISTORY_DATES",
    "BreadthHistoryMaintenanceFailure",
    "BreadthHistoryMaintenanceRequest",
    "BreadthHistoryMaintenanceResult",
    "BreadthHistoryMaintenanceService",
]
