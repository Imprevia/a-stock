"""Seam-first adapters over legacy market-environment components."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any

from ..application.commands import (
    CatalogSyncRequest,
    ExecuteCollectionRunCommand,
    MemberImportRequest,
    RebuildAggregateCommand,
    RefreshDatasetsCommand,
    PrepareLimitHistoryCommand,
    StartCollectionRunCommand,
    SubmitCollectionRunCommand,
    ThsCatalogSyncService,
    ThsMemberImportService,
    ThsOperationGateError,
    ThsTurnoverBackfillService,
    TurnoverBackfillRequest,
    UpdateTimezonePreferenceCommand,
    catalog_sync_request_plan,
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
    GetThsOperationProgressQuery,
    GetThsSectorBarsQuery,
    GetTimezonePreferenceQuery,
    ListThsCatalogQuery,
)
from ..domain.analysis.calculations import build_market_review_evidence
from .collection import CollectionCoordinator
from .providers.fuyao.ths_dump import ThsDumpManifest
from .providers.fuyao.ths_sector import FuyaoThsCapabilityError
from ..domain.models import CollectionCandidate, DatasetDate, MaterializationRevision
from ..domain.models.ths_sector import ThsOperation
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

    def list_dates(self) -> tuple[date, ...]:
        return self.store.list_materialized_aggregate_dates()


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
        repair_integrity: bool = False,
    ):
        return self.coordinator.collect(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
            repair_integrity=repair_integrity,
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

    def prepare_run_submission(self, run_id: str, *, lease_seconds: float):
        return self.coordinator.prepare_run_submission(
            run_id,
            lease_seconds=lease_seconds,
        )

    def release_run_submission(self, run_id: str) -> int:
        return self.coordinator.release_run_submission(run_id)

    def refresh(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
        repair_integrity: bool = False,
    ):
        return RefreshDatasetsCommand(self._commands).execute(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
            repair_integrity=repair_integrity,
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
        repair_integrity: bool = False,
    ):
        return self.refresh(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
            fetch_previous_limit_details=fetch_previous_limit_details,
            repair_integrity=repair_integrity,
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
class FencedRebuilderAggregateCommandAdapter:
    """Persist one maintenance rebuild under the affected breadth/date lease."""

    store: Any
    rebuilder: Any
    now: Callable[[], datetime]
    lease_seconds: float = 600.0

    def rebuild(self, as_of: date):
        current = self.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        owner = f"breadth-history-{uuid.uuid4().hex}"
        lease = self.store.acquire_lease(
            "breadth",
            as_of,
            owner,
            lease_seconds=self.lease_seconds,
            now=current,
        )
        if lease is None:
            raise RuntimeError(
                f"breadth aggregate rebuild lease is busy: {as_of.isoformat()}"
            )
        try:
            return self.rebuilder.rebuild(as_of, lease=lease, now=current)
        finally:
            self.store.release_lease("breadth", as_of, lease=lease)


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


@dataclass(frozen=True, slots=True)
class ThsSectorQueryAdapter:
    """Provider-free THS reads over a short-lived PostgreSQL UoW."""

    unit_of_work_factory: Callable[[], Any]

    def list_catalog(self, **kwargs):
        with self.unit_of_work_factory() as unit_of_work:
            return ListThsCatalogQuery(unit_of_work.ths_sectors).execute(**kwargs)

    def get_bars(self, thscode: str, **kwargs):
        with self.unit_of_work_factory() as unit_of_work:
            return GetThsSectorBarsQuery(unit_of_work.ths_sectors).execute(
                thscode,
                **kwargs,
            )

    def get_operation(self, run_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return GetThsOperationProgressQuery(unit_of_work.ths_sectors).execute(run_id)


@dataclass(frozen=True, slots=True)
class ThsSectorCommandAdapter:
    """Preflight and asynchronously submit explicit THS write operations."""

    unit_of_work_factory: Callable[[], Any]
    executor: Any
    adapter_factory: Callable[[str, str, str | None], Any]
    dump_reader: Any
    fact_merger: Callable[..., Any]
    capability_policy: Any
    gates: Any
    default_revisions: dict[str, str | None]
    clock: Callable[[], datetime]
    effective_date: Callable[[], date] | None = None

    def start_catalog_sync(
        self,
        *,
        as_of: date,
        capability_revision: str | None = None,
        membership_capability_revision: str | None = None,
        membership_thscodes: Iterable[str] = (),
        request_budget: int | None = None,
    ) -> dict[str, str]:
        if self.effective_date is not None and as_of != self.effective_date():
            raise ThsOperationGateError(
                "catalog sync requires the current effective Shanghai market date"
            )
        revision = self._revision("industry-ranking", capability_revision)
        membership_revision = self._revision(
            "sector-membership",
            membership_capability_revision,
        )
        selected_memberships = tuple(membership_thscodes)
        self.gates.require(as_of)
        report = self._require_capability("industry-ranking", revision)
        membership_report = self._require_capability(
            "sector-membership",
            membership_revision,
        )
        _, membership_request_limit, minimum_budget = catalog_sync_request_plan(
            report,
            membership_report,
            explicit_membership_codes=len(set(selected_memberships)),
        )
        authorized_budget = min(
            int(report.rate_limit_evidence["requestBudget"]),
            int(membership_report.rate_limit_evidence["requestBudget"]),
        )
        budget = request_budget if request_budget is not None else minimum_budget
        request = CatalogSyncRequest(
            as_of=as_of,
            capability_revision=revision,
            request_budget=budget,
            membership_capability_revision=membership_revision,
            membership_thscodes=selected_memberships,
            run_id=uuid.uuid4().hex,
        )
        if request.request_budget < minimum_budget:
            raise ThsOperationGateError(
                f"catalog sync request budget must be at least {minimum_budget}"
            )
        if request.request_budget > authorized_budget:
            raise ThsOperationGateError(
                "industry-ranking request budget exceeds capability evidence"
            )
        service = ThsCatalogSyncService(
            self.unit_of_work_factory,
            adapter_factory=lambda: self.adapter_factory(
                revision,
                revision,
                membership_revision,
            ),
            capability_policy=self.capability_policy,
            gates=self.gates,
            clock=self.clock,
        )
        queued = ThsOperation(
            run_id=request.run_id or "",
            kind="catalog-sync",
            status="queued",
            capability_revision=revision,
            request_checksum=self._checksum(
                {
                    "asOf": as_of.isoformat(),
                    "capabilityRevision": revision,
                    "membershipCapabilityRevision": membership_revision,
                    "membershipThscodes": list(request.membership_thscodes),
                    "requestBudget": request.request_budget,
                }
            ),
            requested_at=self.clock(),
            request_metadata={
                "asOf": as_of.isoformat(),
                "membershipCapabilityRevision": membership_revision,
                "membershipThscodes": list(request.membership_thscodes),
            },
            total_items=4 + membership_request_limit,
            request_budget=request.request_budget,
        )
        self._put_operation(queued)
        try:
            self.executor.submit(service.run, request)
        except Exception as error:
            self._put_operation(
                replace(
                    queued,
                    status="failed",
                    failed_items=4,
                    completed_at=self.clock(),
                    warning="THS task executor rejected the operation",
                )
            )
            raise error
        return {"runId": request.run_id or "", "status": "queued"}

    def start_turnover_backfill(
        self,
        *,
        thscodes: Iterable[str],
        start_date: date,
        end_date: date,
        capability_revision: str | None = None,
        request_budget: int | None = None,
    ) -> dict[str, str]:
        revision = self._revision("sector-turnover-history", capability_revision)
        codes = tuple(thscodes)
        window_count = max(1, ((end_date - start_date).days // 366) + 1)
        budget = request_budget or max(1, len(set(codes)) * window_count)
        request = TurnoverBackfillRequest(
            thscodes=codes,
            start_date=start_date,
            end_date=end_date,
            capability_revision=revision,
            request_budget=budget,
            run_id=uuid.uuid4().hex,
        )
        # Constructing the domain run performs the 60-code and five-year checks
        # before any provider adapter can be created.
        queued_run = request.as_run(request.run_id or "")
        self._preflight(end_date, "sector-turnover-history", revision, budget)
        service = ThsTurnoverBackfillService(
            self.unit_of_work_factory,
            adapter_factory=lambda: self.adapter_factory(revision, revision, None),
            capability_policy=self.capability_policy,
            gates=self.gates,
            clock=self.clock,
        )
        self._put_backfill_run(queued_run)
        try:
            self.executor.submit(service.run, request)
        except Exception as error:
            self._put_backfill_run(
                replace(
                    queued_run,
                    status="failed",
                    warning="THS task executor rejected the operation",
                )
            )
            raise error
        return {"runId": request.run_id or "", "status": "queued"}

    def start_member_import(
        self,
        *,
        as_of: date,
        source_revision: str,
        daily: Mapping[str, Any],
        adjustment: Mapping[str, Any],
        incremental: Mapping[str, Any] | None = None,
        request_budget: int | None = None,
    ) -> dict[str, str]:
        request = MemberImportRequest(
            as_of=as_of,
            daily_path=str(daily["path"]),
            daily_manifest=self._manifest(daily, "daily"),
            adjustment_path=str(adjustment["path"]),
            adjustment_manifest=self._manifest(adjustment, "adjustment"),
            source_revision=source_revision,
            request_budget=request_budget,
            incremental_path=(str(incremental["path"]) if incremental else None),
            incremental_manifest=(
                self._manifest(incremental, "incremental") if incremental else None
            ),
        )
        self.gates.require(request.as_of)
        capabilities = (
            ("sector-member-daily-dump", request.daily_manifest.capability_revision),
            (
                "sector-member-adjustment-dump",
                request.adjustment_manifest.capability_revision,
            ),
            *(
                (
                    (
                        "sector-member-incremental-dump",
                        request.incremental_manifest.capability_revision,
                    ),
                )
                if request.incremental_manifest is not None
                else ()
            ),
        )
        reports = [self._require_capability(dataset, revision) for dataset, revision in capabilities]
        if request.request_budget is not None:
            authorized_budget = min(
                int(report.rate_limit_evidence["requestBudget"])
                for report in reports
            )
            if request.request_budget > authorized_budget:
                raise ThsOperationGateError(
                    "member import request budget exceeds capability evidence"
                )
        run_id = request.run_id or uuid.uuid4().hex
        queued = replace(request, run_id=run_id)
        service = ThsMemberImportService(
            self.unit_of_work_factory,
            reader=self.dump_reader,
            fact_merger=self.fact_merger,
            capability_policy=self.capability_policy,
            gates=self.gates,
            clock=self.clock,
        )
        manifests = [queued.daily_manifest, queued.adjustment_manifest]
        if queued.incremental_manifest is not None:
            manifests.append(queued.incremental_manifest)
        metadata = {
            "asOf": queued.as_of.isoformat(),
            "dumpIds": [item.dump_id for item in manifests],
            "checksums": [item.checksum for item in manifests],
            "schemaRevisions": [item.schema_revision for item in manifests],
        }
        operation = ThsOperation(
            run_id=run_id,
            kind="member-import",
            status="queued",
            capability_revision=queued.source_revision,
            request_checksum=self._checksum(metadata),
            requested_at=self.clock(),
            request_metadata=metadata,
            total_items=len(manifests),
            request_budget=queued.request_budget,
        )
        self._put_operation(operation)
        try:
            self.executor.submit(service.run, queued)
        except Exception as error:
            self._put_operation(
                replace(
                    operation,
                    status="failed",
                    failed_items=len(manifests),
                    completed_at=self.clock(),
                    warning="THS task executor rejected the operation",
                )
            )
            raise error
        return {"runId": run_id, "status": "queued"}

    def _preflight(
        self,
        as_of: date,
        dataset: str,
        revision: str,
        request_budget: int,
    ) -> Any:
        self.gates.require(as_of)
        report = self._require_capability(dataset, revision)
        authorized_budget = int(report.rate_limit_evidence["requestBudget"])
        if request_budget > authorized_budget:
            raise ThsOperationGateError(
                f"{dataset} request budget exceeds capability evidence"
            )
        return report

    def _require_capability(self, dataset: str, revision: str) -> Any:
        try:
            return self.capability_policy.require(dataset, revision)
        except FuyaoThsCapabilityError as error:
            raise ThsOperationGateError(str(error)) from error

    @staticmethod
    def _manifest(value: Mapping[str, Any], kind: str) -> ThsDumpManifest:
        return ThsDumpManifest(
            dump_id=str(value["dump_id"]),
            kind=kind,  # type: ignore[arg-type]
            schema_revision=str(value["schema_revision"]),
            capability_revision=str(value["capability_revision"]),
            checksum=str(value["checksum"]),
            start_date=value["start_date"],
            end_date=value["end_date"],
        )

    def _revision(self, dataset: str, supplied: str | None) -> str:
        revision = (supplied or self.default_revisions.get(dataset) or "").strip()
        if not revision:
            raise ThsOperationGateError(
                f"{dataset} capability revision is not configured"
            )
        return revision

    def _put_operation(self, operation: ThsOperation) -> None:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_operation(operation)
            unit_of_work.commit()

    def _put_backfill_run(self, run: Any) -> None:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_backfill_run(run)
            unit_of_work.commit()

    @staticmethod
    def _checksum(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CoordinatorCollectionCommandAdapter",
    "CoordinatorCollectionQueryAdapter",
    "MaterializedAggregateReaderAdapter",
    "FencedRebuilderAggregateCommandAdapter",
    "RebuilderAggregateCommandAdapter",
    "RepositoryMarketEnvironmentQueryAdapter",
    "SnapshotRepositoryAdapter",
    "TimezoneCommandAdapter",
    "TimezoneQueryAdapter",
    "ThsSectorCommandAdapter",
    "ThsSectorQueryAdapter",
    "TradingSessionReaderAdapter",
]
