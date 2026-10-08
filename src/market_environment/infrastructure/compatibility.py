"""Seam-first adapters over legacy market-environment components."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from ..application.commands import (
    ExecuteCollectionRunCommand,
    RebuildAggregateCommand,
    RefreshDatasetsCommand,
    PrepareLimitHistoryCommand,
    StartCollectionRunCommand,
    SubmitCollectionRunCommand,
    UpdateTimezonePreferenceCommand,
)
from ..application.ports import CollectionRefreshRequest, LimitHistoryPreparationRequest
from ..application.mappers import (
    candidate_to_snapshot_fields,
    snapshot_to_candidate,
)
from ..application.queries import (
    GetChapter01Query,
    GetCollectionRunStatusQuery,
    GetCollectionStatusQuery,
    GetCoreQuery,
    GetMarketEnvironmentQuery,
    GetNextSessionComparisonQuery,
    GetTimezonePreferenceQuery,
)
from ..domain.analysis.calculations import build_market_review_evidence
from .collection import CollectionCoordinator
from ..domain.models import CollectionCandidate, DatasetDate, MaterializationRevision
from ..snapshot_store import SnapshotRecord, SnapshotStore


@dataclass(frozen=True, slots=True)
class SnapshotRepositoryAdapter:
    store: SnapshotStore
    now: Callable[[], datetime]

    def get(self, identity: DatasetDate) -> CollectionCandidate | None:
        record = self.store.get(identity.dataset, identity.as_of)
        return snapshot_to_candidate(record) if record is not None else None

    def put(self, candidate: CollectionCandidate) -> CollectionCandidate:
        refresh_warning = (
            candidate.quality.cache.refresh_warning
            if candidate.quality is not None and candidate.quality.cache is not None
            else None
        )
        stored = self.store.put(
            SnapshotRecord(
                **candidate_to_snapshot_fields(
                    candidate,
                    fetched_at=self.now(),
                    refresh_warning=refresh_warning,
                )
            )
        )
        return snapshot_to_candidate(stored)

    def list_dates(self, dataset: str):
        return self.store.list_snapshot_dates(dataset)


@dataclass(frozen=True, slots=True)
class MaterializedAggregateReaderAdapter:
    store: SnapshotStore

    def get_aggregate(self, as_of: date):
        record = self.store.get_materialized_aggregate(as_of)
        return copy.deepcopy(record.payload) if record is not None else None

    def revision(self, as_of: date) -> MaterializationRevision:
        return MaterializationRevision(self.store.materialization_revision(as_of))


@dataclass(frozen=True, slots=True)
class TradingSessionReaderAdapter:
    store: SnapshotStore

    def get_session(self, as_of: date):
        return self.store.get_trading_session(as_of)

    def list_sessions(self, *, after: date | None = None):
        sessions = self.store.list_trading_sessions()
        if after is None:
            return sessions
        return tuple(item for item in sessions if item.as_of > after)


@dataclass(frozen=True, slots=True)
class RepositoryMarketEnvironmentQueryAdapter:
    store: SnapshotStore

    def get(self, as_of: date) -> dict:
        return GetMarketEnvironmentQuery(
            MaterializedAggregateReaderAdapter(self.store)
        ).execute(as_of)

    def get_core(self, as_of: date) -> dict:
        return GetCoreQuery(
            SnapshotRepositoryAdapter(
                self.store,
                now=lambda: datetime.now(timezone.utc),
            )
        ).execute(as_of)

    def get_chapter01(self, as_of: date, section: str) -> dict:
        return GetChapter01Query(
            MaterializedAggregateReaderAdapter(self.store)
        ).execute(as_of, section)

    def get_next_session_comparison(self, as_of: date) -> dict:
        return GetNextSessionComparisonQuery(
            SnapshotRepositoryAdapter(
                self.store,
                now=lambda: datetime.now(timezone.utc),
            ),
            MaterializedAggregateReaderAdapter(self.store),
            TradingSessionReaderAdapter(self.store),
            build_market_review_evidence,
        ).execute(as_of)

@dataclass(frozen=True, slots=True)
class _LegacyCoordinatorStatusReader:
    coordinator: Any

    def collection_status(self, as_of: date):
        return self.coordinator.collection_status(as_of)

    def get_run(self, run_id: str):
        return self.coordinator.get_run(run_id)


@dataclass(frozen=True, slots=True)
class CoordinatorCollectionQueryAdapter:
    coordinator: CollectionCoordinator

    def collection_status(self, as_of: date) -> dict[str, Any]:
        return GetCollectionStatusQuery(
            _LegacyCoordinatorStatusReader(self.coordinator)
        ).execute(as_of)

    def get_run(self, run_id: str):
        return GetCollectionRunStatusQuery(
            _LegacyCoordinatorStatusReader(self.coordinator)
        ).execute(run_id)


@dataclass(frozen=True, slots=True)
class _LegacyCoordinatorCommands:
    coordinator: Any

    def start_run(self, as_of: date, datasets: Iterable[str] | None = None):
        return self.coordinator.start_run(as_of, datasets)

    def submit_run(self, run_id: str):
        return self.coordinator.execute_run(run_id)

    def execute_run(self, run_id: str):
        return self.coordinator.execute_run(run_id)

    def refresh(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
    ):
        return self.coordinator.collect(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
        )

    def refresh_request(self, request: CollectionRefreshRequest):
        return self.coordinator.collect_request(request)

    def prepare_limit_history(self, request: LimitHistoryPreparationRequest):
        return self.coordinator.prepare_limit_history(request)


@dataclass(frozen=True, slots=True)
class CoordinatorCollectionCommandAdapter:
    coordinator: CollectionCoordinator
    executor: Any

    @property
    def _commands(self) -> _LegacyCoordinatorCommands:
        return _LegacyCoordinatorCommands(self.coordinator)

    def start_run(self, as_of: date, datasets: Iterable[str] | None = None):
        return StartCollectionRunCommand(self._commands).execute(as_of, datasets)

    def submit_run(self, run_id: str):
        return SubmitCollectionRunCommand(
            self.executor,
            ExecuteCollectionRunCommand(self._commands),
        ).execute(run_id)

    def execute_run(self, run_id: str):
        return ExecuteCollectionRunCommand(self._commands).execute(run_id)

    def refresh(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
    ):
        return RefreshDatasetsCommand(self._commands).execute(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
        )

    def refresh_request(self, request: CollectionRefreshRequest):
        return RefreshDatasetsCommand(self._commands).execute_request(request)

    def collect(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
    ):
        return self.refresh(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
        )

    def prepare_limit_history_sessions(self, as_of: date, count: int):
        return PrepareLimitHistoryCommand(self._commands).execute(
            LimitHistoryPreparationRequest(as_of, count)
        )

    def prepare_limit_history(self, request: LimitHistoryPreparationRequest):
        return PrepareLimitHistoryCommand(self._commands).execute(request)


@dataclass(frozen=True, slots=True)
class _RebuilderAggregateCommand:
    rebuilder: Any

    def rebuild(self, as_of: date):
        return self.rebuilder.rebuild(as_of)


@dataclass(frozen=True, slots=True)
class RebuilderAggregateCommandAdapter:
    rebuilder: Any

    def rebuild(self, as_of: date):
        return RebuildAggregateCommand(
            _RebuilderAggregateCommand(self.rebuilder)
        ).execute(as_of)


@dataclass(frozen=True, slots=True)
class TimezoneQueryAdapter:
    repository: Any

    def get(self, *args, **kwargs):
        return GetTimezonePreferenceQuery(self.repository).execute(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class TimezoneCommandAdapter:
    repository: Any

    def set(self, *args, **kwargs):
        return UpdateTimezonePreferenceCommand(self.repository).execute(*args, **kwargs)


__all__ = [
    "CoordinatorCollectionCommandAdapter",
    "CoordinatorCollectionQueryAdapter",
    "MaterializedAggregateReaderAdapter",
    "RebuilderAggregateCommandAdapter",
    "RepositoryMarketEnvironmentQueryAdapter",
    "SnapshotRepositoryAdapter",
    "TimezoneCommandAdapter",
    "TimezoneQueryAdapter",
    "TradingSessionReaderAdapter",
]
