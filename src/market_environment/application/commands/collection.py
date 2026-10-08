"""Collection and aggregate command use cases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ..ports import (
    AggregateCommandPort,
    CollectionCommandPort,
    CollectionRefreshRequest,
    LimitHistoryPreparationRequest,
    TaskExecutor,
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
    "RebuildAggregateCommand",
    "PrepareLimitHistoryCommand",
    "RefreshDatasetsCommand",
    "StartCollectionRunCommand",
    "SubmitCollectionRunCommand",
]
