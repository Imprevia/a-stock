"""Collection and aggregate command use cases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import uuid
from typing import Any, Callable

from ..ports import (
    AggregateCommandPort,
    CollectionCommandPort,
    CollectionQueryPort,
    CollectionRefreshRequest,
    LimitHistoryPreparationRequest,
    TaskExecutor,
)
from ...domain.models import (
    CollectionFailureCategory,
    IdempotencyBinding,
    IdempotencyKey,
    StructuredTaskFailure,
    SubmissionState,
)


@dataclass(frozen=True, slots=True)
class StartCollectionRunCommand:
    commands: CollectionCommandPort

    def execute(self, as_of: date, datasets: Iterable[str] | None = None):
        return self.commands.start_run(as_of, datasets)


@dataclass(frozen=True, slots=True)
class ExecuteCollectionRunCommand:
    commands: CollectionCommandPort

    def execute(self, run_id: str):
        return self.commands.execute_run(run_id)


@dataclass(frozen=True, slots=True)
class SubmitCollectionRunCommand:
    executor: TaskExecutor
    execute_run: ExecuteCollectionRunCommand

    def execute(self, run_id: str):
        return self.executor.submit(self.execute_run.execute, run_id)


class RecoverableSubmissionDisposition(str, Enum):
    SUBMITTED = "submitted"
    ACTIVE = "active"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RecoverableSubmissionResult:
    disposition: RecoverableSubmissionDisposition
    binding: IdempotencyBinding
    submitted_task: Any | None = None

    @property
    def submitted_now(self) -> bool:
        return self.disposition is RecoverableSubmissionDisposition.SUBMITTED


class CollectionSubmissionRejected(RuntimeError):
    def __init__(self, binding: IdempotencyBinding) -> None:
        super().__init__("collection executor rejected the original run submission")
        self.binding = binding


@dataclass(frozen=True, slots=True)
class RecoverableCollectionSubmissionService:
    """Submit one claimed run while preserving restart-safe ownership state."""

    unit_of_work_factory: Callable[[], Any]
    commands: CollectionCommandPort
    queries: CollectionQueryPort
    executor: TaskExecutor
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    submission_lease_seconds: float = 1800.0
    task_lease_seconds: float = 1800.0

    def submit(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        run_id: str,
    ) -> RecoverableSubmissionResult:
        if self.submission_lease_seconds <= 0 or self.task_lease_seconds <= 0:
            raise ValueError("submission and task lease durations must be positive")
        current_binding = self._get_binding(operation_scope, key)
        self._require_original_run(current_binding, run_id)
        current_run = self.queries.get_run(run_id)
        if current_run is None:
            raise KeyError(f"unknown collection run: {run_id}")
        if (
            current_binding.submission_state is SubmissionState.SUBMITTED
            and self._is_terminal(current_run)
        ):
            return RecoverableSubmissionResult(
                RecoverableSubmissionDisposition.TERMINAL,
                current_binding,
            )

        owner = uuid.uuid4().hex
        now = self._utc_now()
        with self.unit_of_work_factory() as unit_of_work:
            acquired = unit_of_work.collection_idempotency.acquire_submission(
                operation_scope,
                key,
                owner=owner,
                now=now,
                lease_seconds=self.submission_lease_seconds,
            )
            unit_of_work.commit()
        if acquired is None:
            binding = self._get_binding(operation_scope, key)
            self._require_original_run(binding, run_id)
            observed = self.queries.get_run(run_id)
            return RecoverableSubmissionResult(
                (
                    RecoverableSubmissionDisposition.TERMINAL
                    if observed is not None and self._is_terminal(observed)
                    else RecoverableSubmissionDisposition.ACTIVE
                ),
                binding,
            )

        tasks = tuple(
            self.commands.prepare_run_submission(
                run_id,
                lease_seconds=self.task_lease_seconds,
            )
        )
        observed = self.queries.get_run(run_id)
        if observed is None:
            raise KeyError(f"unknown collection run: {run_id}")
        if self._is_terminal(observed) or (tasks and self._all_terminal(tasks)):
            if not self._is_terminal(observed):
                self.commands.execute_run(run_id)
            binding = self._mark_submitted(operation_scope, key, owner)
            return RecoverableSubmissionResult(
                RecoverableSubmissionDisposition.TERMINAL,
                binding,
            )
        if any(getattr(task, "status", None) == "collecting" for task in tasks):
            binding = self._mark_submitted(operation_scope, key, owner)
            return RecoverableSubmissionResult(
                RecoverableSubmissionDisposition.ACTIVE,
                binding,
            )

        try:
            submitted_task = self.executor.submit(self.commands.execute_run, run_id)
        except Exception as error:
            release_error: Exception | None = None
            try:
                self.commands.release_run_submission(run_id)
            except Exception as exc:  # pragma: no cover - defensive cleanup path
                release_error = exc
            message = str(error) or "collection executor rejected submission"
            if release_error is not None:
                message = f"{message}; queued lease cleanup failed: {release_error}"
            failure = StructuredTaskFailure(
                category=CollectionFailureCategory.CONCURRENCY,
                message=message,
                retryable=True,
                retained=False,
                stage="executor-submission",
                code="EXECUTOR_SUBMISSION_REJECTED",
            )
            with self.unit_of_work_factory() as unit_of_work:
                binding = unit_of_work.collection_idempotency.mark_submission_failed(
                    operation_scope,
                    key,
                    owner=owner,
                    failure=failure,
                    now=self._utc_now(),
                )
                unit_of_work.commit()
            raise CollectionSubmissionRejected(binding) from error

        binding = self._mark_submitted(operation_scope, key, owner)
        return RecoverableSubmissionResult(
            RecoverableSubmissionDisposition.SUBMITTED,
            binding,
            submitted_task,
        )

    def _get_binding(
        self,
        operation_scope: str,
        key: IdempotencyKey,
    ) -> IdempotencyBinding:
        with self.unit_of_work_factory() as unit_of_work:
            binding = unit_of_work.collection_idempotency.get_binding(
                operation_scope,
                key,
            )
            unit_of_work.commit()
        if binding is None:
            raise KeyError("unknown idempotency binding")
        return binding

    def _mark_submitted(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        owner: str,
    ) -> IdempotencyBinding:
        with self.unit_of_work_factory() as unit_of_work:
            binding = unit_of_work.collection_idempotency.mark_submitted(
                operation_scope,
                key,
                owner=owner,
                now=self._utc_now(),
                recovery_seconds=self.submission_lease_seconds,
            )
            unit_of_work.commit()
        return binding

    def _utc_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _require_original_run(binding: IdempotencyBinding, run_id: str) -> None:
        if binding.run_id != run_id:
            raise ValueError("idempotency binding does not reference the requested run")

    @staticmethod
    def _is_terminal(result: Any) -> bool:
        run = getattr(result, "run", result)
        return getattr(run, "status", None) in {"success", "partial", "failed"}

    @staticmethod
    def _all_terminal(tasks: tuple[Any, ...]) -> bool:
        return all(
            getattr(task, "status", None)
            in {
                "success",
                "partial",
                "failed-retained",
                "failed-missing",
                "busy",
                "blocked",
            }
            for task in tasks
        )


@dataclass(frozen=True, slots=True)
class RefreshDatasetsCommand:
    commands: CollectionCommandPort

    def execute(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
    ):
        return self.commands.refresh(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
        )

    def execute_request(self, request: CollectionRefreshRequest):
        return self.commands.refresh_request(request)


@dataclass(frozen=True, slots=True)
class PrepareLimitHistoryCommand:
    commands: CollectionCommandPort

    def execute(self, request: LimitHistoryPreparationRequest) -> tuple[date, ...]:
        return self.commands.prepare_limit_history(request)


@dataclass(frozen=True, slots=True)
class RebuildAggregateCommand:
    commands: AggregateCommandPort

    def execute(self, as_of: date):
        return self.commands.rebuild(as_of)


__all__ = [
    "ExecuteCollectionRunCommand",
    "CollectionSubmissionRejected",
    "RecoverableCollectionSubmissionService",
    "RecoverableSubmissionDisposition",
    "RecoverableSubmissionResult",
    "RebuildAggregateCommand",
    "PrepareLimitHistoryCommand",
    "RefreshDatasetsCommand",
    "StartCollectionRunCommand",
    "SubmitCollectionRunCommand",
]
