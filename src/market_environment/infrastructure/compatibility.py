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
    StartCollectionRunCommand,
    SubmitCollectionRunCommand,
    UpdateTimezonePreferenceCommand,
)
from ..application.collection import DatasetCollectorRegistry
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
from ..calculations import build_market_review_evidence
from ..collection import CollectionCoordinator
from ..domain.models import (
    DATASET_IDS,
    CollectionCandidate,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    MaterializationRevision,
)
from ..service import MarketEnvironmentService
from ..snapshot_store import SnapshotRecord, SnapshotStore


@dataclass(frozen=True, slots=True)
class LegacySnapshotRepositoryAdapter:
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
class LegacyMaterializedAggregateReaderAdapter:
    store: SnapshotStore

    def get_aggregate(self, as_of: date):
        record = self.store.get_materialized_aggregate(as_of)
        return copy.deepcopy(record.payload) if record is not None else None

    def revision(self, as_of: date) -> MaterializationRevision:
        return MaterializationRevision(self.store.materialization_revision(as_of))


@dataclass(frozen=True, slots=True)
class LegacyTradingSessionReaderAdapter:
    store: SnapshotStore

    def get_session(self, as_of: date):
        return self.store.get_trading_session(as_of)

    def list_sessions(self, *, after: date | None = None):
        sessions = self.store.list_trading_sessions()
        if after is None:
            return sessions
        return tuple(item for item in sessions if item.as_of > after)


@dataclass(frozen=True, slots=True)
class _LegacyServiceAggregateReader:
    service: Any
    section: str | None = None

    def get_aggregate(self, as_of: date):
        if self.section is None:
            return self.service.get(as_of)
        return self.service.get_chapter01(as_of, self.section)


@dataclass(frozen=True, slots=True)
class _LegacyServiceCoreReader:
    service: Any

    def get(self, identity: DatasetDate) -> CollectionCandidate | None:
        payload = self.service.get_core(identity.as_of)
        actual_value = payload.get("asOf") if isinstance(payload, dict) else None
        actual_as_of = (
            date.fromisoformat(actual_value)
            if isinstance(actual_value, str)
            else identity.as_of
        )
        summary = payload.get("summary") if isinstance(payload, dict) else None
        warnings = (
            tuple(str(value) for value in summary.get("warnings") or ())
            if isinstance(summary, dict)
            else ()
        )
        indices = payload.get("indices") if isinstance(payload, dict) else None
        return CollectionCandidate(
            identity=identity,
            payload=copy.deepcopy(payload),
            source="legacy-service",
            status="ok",
            observations=len(indices) if isinstance(indices, list) else 0,
            warnings=warnings,
            settled=True,
            actual_as_of=actual_as_of,
        )

    def list_dates(self, dataset: str):
        store = getattr(self.service, "snapshot_store", None)
        if store is None:
            return ()
        return store.list_snapshot_dates(dataset)


@dataclass(frozen=True, slots=True)
class LegacyMarketEnvironmentQueryAdapter:
    service: MarketEnvironmentService

    def get(self, as_of: date) -> dict:
        return GetMarketEnvironmentQuery(
            _LegacyServiceAggregateReader(self.service)
        ).execute(as_of)

    def get_core(self, as_of: date) -> dict:
        return GetCoreQuery(_LegacyServiceCoreReader(self.service)).execute(as_of)

    def get_chapter01(self, as_of: date, section: str) -> dict:
        return GetChapter01Query(
            _LegacyServiceAggregateReader(self.service, section)
        ).execute(as_of, section)

    def get_next_session_comparison(self, as_of: date) -> dict:
        store = getattr(self.service, "snapshot_store", None)
        if store is None:
            return self.service.get_next_session_comparison(as_of)
        return GetNextSessionComparisonQuery(
            LegacySnapshotRepositoryAdapter(
                store,
                now=lambda: datetime.now(timezone.utc),
            ),
            LegacyMaterializedAggregateReaderAdapter(store),
            LegacyTradingSessionReaderAdapter(store),
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
class LegacyCollectionQueryAdapter:
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


@dataclass(frozen=True, slots=True)
class LegacyCollectionCommandAdapter:
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
        return self.coordinator.prepare_limit_history_sessions(as_of, count)


@dataclass(frozen=True, slots=True)
class _LegacyAggregateCommands:
    service: Any

    def rebuild(self, as_of: date):
        return self.service.rebuild_materialized_aggregate(as_of)


@dataclass(frozen=True, slots=True)
class LegacyAggregateCommandAdapter:
    service: MarketEnvironmentService

    def rebuild(self, as_of: date):
        return RebuildAggregateCommand(
            _LegacyAggregateCommands(self.service)
        ).execute(as_of)


@dataclass(frozen=True, slots=True)
class LegacyTimezoneQueryAdapter:
    repository: Any

    def get(self, *args, **kwargs):
        return GetTimezonePreferenceQuery(self.repository).execute(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class LegacyTimezoneCommandAdapter:
    repository: Any

    def set(self, *args, **kwargs):
        return UpdateTimezonePreferenceCommand(self.repository).execute(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class LegacyDatasetCollectorAdapter:
    """Expose one existing provider/coordinator dataset chain as a collector."""

    dataset_id: str
    coordinator: CollectionCoordinator

    @classmethod
    def from_provider(
        cls,
        dataset_id: str,
        provider: Any,
        store: SnapshotStore,
        *,
        now: Callable[[], datetime],
        rebuild_aggregate: Callable[..., Any] | None = None,
        **coordinator_options: Any,
    ) -> "LegacyDatasetCollectorAdapter":
        return cls(
            dataset_id,
            CollectionCoordinator(
                provider,
                store,
                now=now,
                rebuild_aggregate=rebuild_aggregate,
                **coordinator_options,
            ),
        )

    def collect(self, identity: DatasetDate) -> CollectionOutcome:
        if identity.dataset != self.dataset_id:
            raise ValueError(
                f"collector {self.dataset_id} cannot collect {identity.dataset}"
            )
        result = self.coordinator.collect(identity.as_of, (self.dataset_id,))
        task = result.tasks[0]
        record = self.coordinator.store.get(self.dataset_id, identity.as_of)
        candidate = snapshot_to_candidate(record) if record is not None else None
        return CollectionOutcome(
            identity=identity,
            state=CollectionTaskState(task.status),
            candidate=candidate,
            warning=task.warning,
            retained=task.status == CollectionTaskState.FAILED_RETAINED.value,
        )


def build_legacy_provider_collector_registry(
    provider: Any,
    store: SnapshotStore,
    *,
    now: Callable[[], datetime],
    rebuild_aggregate: Callable[..., Any] | None = None,
    **coordinator_options: Any,
) -> DatasetCollectorRegistry:
    """Expose existing provider/coordinator paths through all stable collectors."""

    return DatasetCollectorRegistry.complete(
        LegacyDatasetCollectorAdapter.from_provider(
            dataset_id,
            provider,
            store,
            now=now,
            rebuild_aggregate=rebuild_aggregate,
            **coordinator_options,
        )
        for dataset_id in DATASET_IDS
    )


__all__ = [
    "LegacyAggregateCommandAdapter",
    "LegacyCollectionCommandAdapter",
    "LegacyCollectionQueryAdapter",
    "LegacyDatasetCollectorAdapter",
    "LegacyMaterializedAggregateReaderAdapter",
    "LegacyMarketEnvironmentQueryAdapter",
    "LegacySnapshotRepositoryAdapter",
    "LegacyTimezoneCommandAdapter",
    "LegacyTimezoneQueryAdapter",
    "LegacyTradingSessionReaderAdapter",
    "build_legacy_provider_collector_registry",
]
