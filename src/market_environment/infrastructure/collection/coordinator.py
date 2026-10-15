"""Independent market dataset collection and failure isolation."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import nullcontext
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...application.collection import (
    DatasetCollectorRegistry,
    DatasetCommitterRegistry,
    DatasetDetailProjectorRegistry,
)
from ...application.ports import (
    CollectionRefreshRequest,
    DatasetCommitRequest,
    LimitHistoryPreparationRequest,
    LimitHistoryPreparer,
)
from ...application.mappers import snapshot_to_candidate
from ...domain.models import (
    CollectionFailureCategory,
    CollectionOutcome,
    CollectionTaskState,
    DatasetDate,
    StructuredTaskFailure,
)
from ...application.ths_diagnostics import (
    ThsBlockedBy,
    ThsDiagnostic,
    encode_ths_diagnostic,
)
from ..providers.fuyao.config import FuyaoCollectionConfig
from ..providers.fuyao.market import FuyaoMarketAdapter
from ..providers import (
    ActiveDirectionCollector,
    BreadthCollector,
    CoreCollector,
    FuyaoCollectionPolicy,
    LimitsCollector,
    SectorsCollector,
)
from .refresh import MARKET_TIME_ZONE, effective_market_date, settlement_time
from .projectors import build_local_detail_projector_registry
from .callbacks import normalize_rebuild_callback
from .limits_history import CollectorLimitHistoryPreparer
from ...snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    LeaseFenceError,
    LeaseToken,
)

SUPPORTED_COLLECTION_DATASETS = (
    "core",
    "breadth",
    "limits",
    "industry-ranking",
    "sector-turnover",
    "sector-breadth",
    "activeDirection",
)
LATEST_ONLY_DATASETS = frozenset(
    {
        "breadth",
        "industry-ranking",
        "sector-turnover",
        "sector-breadth",
        "activeDirection",
    }
)
DATASET_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "sector-turnover": ("industry-ranking",),
    "sector-breadth": ("industry-ranking", "sector-turnover"),
}


def _ths_catalog_revision(snapshot: Any | None) -> str | None:
    if snapshot is None or not isinstance(snapshot.payload, dict):
        return None
    payload = snapshot.payload
    value = payload.get("catalogRevisionId") or payload.get("catalogRevision")
    if value is None and isinstance(payload.get("catalog"), dict):
        value = payload["catalog"].get("revision")
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _accepted_ths_snapshot(snapshot: Any | None, as_of: date) -> bool:
    if snapshot is None or snapshot.as_of != as_of:
        return False
    if snapshot.status not in {"ok", "partial", "degraded"}:
        return False
    if not isinstance(snapshot.payload, dict):
        return False
    payload_as_of = snapshot.payload.get("asOf")
    if payload_as_of not in (None, as_of.isoformat()):
        return False
    return _ths_catalog_revision(snapshot) is not None


def _ths_block_warning(
    task: "CollectionTaskRecord",
    blocked_by: tuple[str, ...],
    store: Any,
) -> str:
    diagnostic_datasets = (
        DATASET_DEPENDENCIES.get(task.dataset, blocked_by)
        if task.dataset == "sector-breadth"
        else blocked_by
    )
    entries: list[ThsBlockedBy] = []
    mismatch = False
    dependency_revisions: set[str] = set()
    for dataset in diagnostic_datasets:
        snapshot = store.get(dataset, task.as_of)
        revision = _ths_catalog_revision(snapshot)
        if revision is not None:
            dependency_revisions.add(revision)
        entries.append(
            ThsBlockedBy(
                dataset=dataset,
                status=str(getattr(snapshot, "status", "missing")),
                exact_date=task.as_of,
                catalog_revision_id=revision,
            )
        )
        if snapshot is not None and not _accepted_ths_snapshot(snapshot, task.as_of):
            mismatch = True
    if len(dependency_revisions) > 1:
        mismatch = True
    reason = (
        "THS_DEPENDENCY_REVISION_MISMATCH"
        if mismatch
        else "THS_DEPENDENCY_INSUFFICIENT"
    )
    return encode_ths_diagnostic(
        ThsDiagnostic(
            reason_code=reason,
            message="THS downstream task prerequisites are not compatible",
            failure_stage="dependency-coordination",
            exact_date=task.as_of,
            retryable=True,
            blocked_by=tuple(entries),
        )
    )


def _ths_exception_warning(task: "CollectionTaskRecord", error: Exception, store: Any) -> str:
    # Exception text is inspected only to classify a known immutable conflict;
    # it is never persisted or exposed to the client.
    text = str(error).lower()
    existing = store.get(task.dataset, task.as_of)
    catalog_revision = _ths_catalog_revision(existing)
    if "conflicting ths catalog revision" in text or "catalog revision checksum" in text:
        return encode_ths_diagnostic(
            ThsDiagnostic(
                reason_code="THS_CATALOG_REVISION_COLLISION",
                message="THS catalog observation revision conflicts with retained content",
                failure_stage="catalog-persistence",
                exact_date=task.as_of,
                retryable=False,
                catalog_revision_id=catalog_revision,
            )
        )
    if task.dataset == "industry-ranking":
        return encode_ths_diagnostic(
            ThsDiagnostic(
                reason_code="THS_DAILY_SNAPSHOT_INSUFFICIENT",
                message="THS catalog or daily snapshot validation failed",
                failure_stage="collection-commit",
                exact_date=task.as_of,
                retryable=True,
                catalog_revision_id=catalog_revision,
            )
        )
    reason = (
        "THS_DEPENDENCY_REVISION_MISMATCH"
        if "revision" in text or "date" in text
        else "THS_DEPENDENCY_INSUFFICIENT"
    )
    return encode_ths_diagnostic(
        ThsDiagnostic(
            reason_code=reason,
            message="THS dependent dataset could not consume compatible local evidence",
            failure_stage="dependency-collection",
            exact_date=task.as_of,
            retryable=True,
            catalog_revision_id=catalog_revision,
        )
    )


def _ths_exception_failure(
    task: "CollectionTaskRecord",
    error: Exception,
    *,
    retained: bool,
) -> StructuredTaskFailure:
    text = str(error).lower()
    if "conflicting ths catalog revision" in text or "catalog revision checksum" in text:
        return StructuredTaskFailure(
            category=CollectionFailureCategory.CONTRACT,
            message="THS catalog observation revision conflicts with retained content",
            retryable=False,
            retained=retained,
            stage="catalog-persistence",
            code="THS_CATALOG_REVISION_COLLISION",
        )
    if task.dataset == "industry-ranking":
        return StructuredTaskFailure(
            category=CollectionFailureCategory.INSUFFICIENT,
            message="THS catalog or daily snapshot validation failed",
            retryable=True,
            retained=retained,
            stage="collection-commit",
            code="THS_DAILY_SNAPSHOT_INSUFFICIENT",
        )
    return StructuredTaskFailure(
        category=CollectionFailureCategory.DEPENDENCY,
        message="THS dependent dataset could not consume compatible local evidence",
        retryable=True,
        retained=retained,
        stage="dependency-collection",
        code=(
            "THS_DEPENDENCY_REVISION_MISMATCH"
            if "revision" in text or "date" in text
            else "THS_DEPENDENCY_INSUFFICIENT"
        ),
    )


def _outcome_failure(
    outcome: CollectionOutcome,
    *,
    retained: bool,
    fallback_message: str,
) -> StructuredTaskFailure:
    if outcome.failure is not None:
        return StructuredTaskFailure.from_acquisition(
            outcome.failure,
            retained=retained,
        )
    return StructuredTaskFailure(
        category=CollectionFailureCategory.INTERNAL,
        message=fallback_message,
        retryable=True,
        retained=retained,
        stage="collection",
    )


SUCCESSFUL_TASK_STATUSES = frozenset({"success", "partial"})
TERMINAL_TASK_STATUSES = frozenset(
    {"success", "partial", "failed-retained", "failed-missing", "busy", "blocked"}
)


@dataclass(frozen=True, slots=True)
class _UnavailableThsCollector:
    dataset_id: str

    def collect_task(self, task: CollectionTaskRecord, *_args: Any, **_kwargs: Any):
        raise RuntimeError(
            f"{self.dataset_id} requires the normalized Fuyao THS collector configuration"
        )


@dataclass(frozen=True)
class CollectionStartResult:
    run: CollectionRunRecord
    tasks: tuple[CollectionTaskRecord, ...]


class CollectionCoordinator:
    def __init__(
        self,
        provider: Any | None = None,
        store: Any | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        lease_seconds: float = 600.0,
        rebuild_aggregate: Callable[..., Any] | None = None,
        limits_v1_enabled: bool | None = None,
        fuyao_config: FuyaoCollectionConfig | None = None,
        fuyao_adapter: FuyaoMarketAdapter | None = None,
        fuyao_policy: FuyaoCollectionPolicy | None = None,
        core_collector: CoreCollector | None = None,
        breadth_collector: BreadthCollector | None = None,
        active_direction_collector: ActiveDirectionCollector | None = None,
        sectors_collector: SectorsCollector | None = None,
        limits_collector: LimitsCollector | None = None,
        collector_registry: DatasetCollectorRegistry | None = None,
        committer_registry: DatasetCommitterRegistry | None = None,
        commit_request_factories: dict[
            str,
            Callable[..., DatasetCommitRequest],
        ]
        | None = None,
        commit_preparers: dict[str, Any] | None = None,
        detail_projector_registry: DatasetDetailProjectorRegistry | None = None,
        limit_history_preparer: LimitHistoryPreparer | None = None,
        typed_cutover_datasets: Iterable[str] = (),
        sector_analysis_readiness: Callable[[date], dict[str, Any] | None] | None = None,
    ) -> None:
        if provider is None and collector_registry is None:
            raise ValueError("CollectionCoordinator requires an explicit collector provider")
        if store is None:
            raise ValueError("CollectionCoordinator requires an explicit repository")
        self.provider = provider
        self.store = store
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        self.lease_seconds = lease_seconds
        self.rebuild_aggregate = normalize_rebuild_callback(rebuild_aggregate)
        self.committer_registry = committer_registry
        self._commit_request_factories = dict(commit_request_factories or {})
        self._commit_preparers = dict(commit_preparers or {})
        self.typed_cutover_datasets = frozenset(typed_cutover_datasets)
        self._sector_analysis_readiness = sector_analysis_readiness or getattr(
            store, "sector_analysis_readiness", None
        )
        unknown_cutovers = self.typed_cutover_datasets - set(
            SUPPORTED_COLLECTION_DATASETS
        )
        if unknown_cutovers:
            raise ValueError(
                "unsupported typed collector cutovers: "
                + ", ".join(sorted(unknown_cutovers))
            )
        if self.typed_cutover_datasets and self.committer_registry is None:
            raise ValueError(
                "typed collector cutovers require a complete committer registry"
            )
        if self.committer_registry is not None:
            for dataset in self.typed_cutover_datasets:
                self.committer_registry.get(dataset)
        self._limits_v1_override = limits_v1_enabled
        if collector_registry is None:
            self.fuyao_config = fuyao_config or FuyaoCollectionConfig.from_environment()
            self.fuyao_adapter = fuyao_adapter or FuyaoMarketAdapter()
            self.fuyao_policy = fuyao_policy or FuyaoCollectionPolicy(
                self.fuyao_config,
                self.store,
            )
            core_collector = core_collector or CoreCollector(
                self.provider,
                self.store,
                market_now=self._market_now,
                is_settled=self._is_settled,
                fuyao_adapter=self.fuyao_adapter,
                fuyao_is_enabled=self.fuyao_policy.is_enabled,
                fuyao_shadow_enabled=self.fuyao_policy.shadow_enabled,
                fuyao_revision=self.fuyao_policy.revision,
                lease_seconds=self.lease_seconds,
            )
            breadth_collector = breadth_collector or BreadthCollector(
                self.provider,
                self.store,
                market_now=self._market_now,
                is_settled=self._is_settled,
                fuyao_adapter=self.fuyao_adapter,
                fuyao_is_enabled=self.fuyao_policy.is_enabled,
                fuyao_shadow_enabled=self.fuyao_policy.shadow_enabled,
                fuyao_revision=self.fuyao_policy.revision,
            )
            active_direction_collector = (
                active_direction_collector
                or ActiveDirectionCollector(
                    self.provider,
                    self.store,
                    market_now=self._market_now,
                    is_settled=self._is_settled,
                )
            )
            limits_collector = limits_collector or LimitsCollector(
                self.provider,
                self.store,
                market_now=self._market_now,
                is_settled=self._is_settled,
                lease_seconds=self.lease_seconds,
                limits_v1_enabled_override=self._limits_v1_override,
                fuyao_is_enabled=self.fuyao_policy.is_enabled,
                fuyao_shadow_enabled=self.fuyao_policy.shadow_enabled,
                fuyao_revision=self.fuyao_policy.revision,
            )
            collector_registry = DatasetCollectorRegistry.complete(
                (
                    core_collector,
                    breadth_collector,
                    limits_collector,
                    _UnavailableThsCollector("industry-ranking"),
                    _UnavailableThsCollector("sector-turnover"),
                    _UnavailableThsCollector("sector-breadth"),
                    active_direction_collector,
                )
            )
        else:
            self.fuyao_config = fuyao_config
            self.fuyao_adapter = fuyao_adapter
            self.fuyao_policy = fuyao_policy
        self.collector_registry = collector_registry
        self.limit_history_preparer = limit_history_preparer
        if self.limit_history_preparer is None and limits_collector is not None:
            self.limit_history_preparer = CollectorLimitHistoryPreparer(limits_collector)
        self.detail_projector_registry = (
            detail_projector_registry
            or build_local_detail_projector_registry(
                self.store,
                limits_enabled=self._limits_v1_override,
            )
        )

    def start_run(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
    ) -> CollectionStartResult:
        requested = tuple(dict.fromkeys(datasets or SUPPORTED_COLLECTION_DATASETS))
        self.validate_request(
            as_of,
            requested,
            allow_historical_latest_only=allow_historical_latest_only,
        )
        selected = self._expand_dependencies(as_of, requested)
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(now=current.astimezone(ZoneInfo("UTC")))
        run_id = uuid.uuid4().hex
        run = self.store.create_collection_run(run_id, as_of, selected, created_at=current)
        tasks: list[CollectionTaskRecord] = []
        for dataset in selected:
            cutover_error = (
                self.fuyao_policy.preflight_error(dataset)
                if self.fuyao_policy is not None
                else None
            )
            if cutover_error is not None:
                task_id = uuid.uuid4().hex
                retained = self.store.get(dataset, as_of) is not None
                preflight_failure = StructuredTaskFailure(
                    category=CollectionFailureCategory.CONFIGURATION,
                    message=cutover_error,
                    retryable=False,
                    retained=retained,
                    stage="preflight",
                    code="FUYAO_PREFLIGHT_REJECTED",
                )
                task = self.store.create_collection_task(
                    task_id,
                    run_id,
                    dataset,
                    as_of,
                    queued_at=current,
                    status="failed-retained" if retained else "failed-missing",
                    failure=preflight_failure,
                )
                task = self.store.transition_collection_task(
                    task.task_id,
                    task.status,
                    expected_statuses=(task.status,),
                    warning=cutover_error,
                    failure=preflight_failure,
                    completed_at=current,
                )
                tasks.append(task)
                continue
            # Reserve the dataset/date lease before returning the run to close the async startup race.
            lease_started = time.perf_counter()
            active = self.store.active_collection_task(
                dataset,
                as_of,
                now=current.astimezone(ZoneInfo("UTC")),
            )
            task_id = uuid.uuid4().hex
            if active is not None:
                busy_failure = StructuredTaskFailure(
                    category=CollectionFailureCategory.CONCURRENCY,
                    message="another active task already holds the dataset/date lease",
                    retryable=True,
                    retained=False,
                    stage="lease-acquisition",
                )
                task = self.store.create_collection_task(
                    task_id,
                    run_id,
                    dataset,
                    as_of,
                    queued_at=current,
                    status="busy",
                    failure=busy_failure,
                )
                task = self.store.transition_collection_task(
                    task.task_id,
                    "busy",
                    warning=f"active task {active.task_id} already holds the dataset lease",
                    failure=busy_failure,
                    timings={"leaseWaitMs": self._milliseconds(lease_started)},
                    completed_at=current,
                )
                tasks.append(task)
                continue

            task = self.store.create_collection_task(
                task_id,
                run_id,
                dataset,
                as_of,
                queued_at=current,
            )
            acquired = self.store.acquire_lease(
                dataset,
                as_of,
                task_id,
                lease_seconds=self.lease_seconds,
                now=current.astimezone(ZoneInfo("UTC")),
            )
            if not acquired:
                task = self.store.transition_collection_task(
                    task.task_id,
                    "busy",
                    expected_statuses=("queued",),
                    warning="another task acquired the dataset lease",
                    failure=StructuredTaskFailure(
                        category=CollectionFailureCategory.CONCURRENCY,
                        message="another task acquired the dataset/date lease",
                        retryable=True,
                        retained=False,
                        stage="lease-acquisition",
                    ),
                    timings={"leaseWaitMs": self._milliseconds(lease_started)},
                    completed_at=current,
                )
            else:
                task = self.store.transition_collection_task(
                    task.task_id,
                    "queued",
                    expected_statuses=("queued",),
                    timings={"leaseWaitMs": self._milliseconds(lease_started)},
                )
            tasks.append(task)
        run = self.store.update_collection_run(run_id, "collecting", started_at=current)
        return CollectionStartResult(run=run, tasks=tuple(tasks))

    def execute_run(
        self,
        run_id: str,
        *,
        fetch_previous_limit_details: bool = True,
    ) -> CollectionRunRecord:
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(
            now=current.astimezone(ZoneInfo("UTC"))
        )
        run = self.store.get_collection_run(run_id)
        if run is None:
            raise KeyError(f"unknown collection run: {run_id}")
        if run.status in {"success", "partial", "failed"}:
            return run
        if run.status == "queued":
            run = self.store.update_collection_run(
                run_id,
                "collecting",
                started_at=self._market_now(),
            )
        task_order = {
            dataset: index for index, dataset in enumerate(SUPPORTED_COLLECTION_DATASETS)
        }
        pending_tasks = sorted(
            self.store.list_collection_tasks(run_id),
            key=lambda item: task_order[item.dataset],
        )
        for task in pending_tasks:
            if task.status == "queued":
                blocked_by = self._blocked_dependencies(task, run_id)
                if blocked_by:
                    lease = self.store.get_lease_token(
                        task.dataset,
                        task.as_of,
                        owner=task.task_id,
                    )
                    task = self.store.transition_collection_task(
                        task.task_id,
                        "blocked",
                        expected_statuses=("queued",),
                        warning=(
                            _ths_block_warning(task, blocked_by, self.store)
                            if task.dataset in {"sector-turnover", "sector-breadth"}
                            else (
                                "blocked by incompatible sector prerequisites: "
                                + ", ".join(blocked_by)
                            )
                        ),
                        failure=StructuredTaskFailure(
                            category=CollectionFailureCategory.DEPENDENCY,
                            message=(
                                "blocked by incompatible dataset prerequisites: "
                                + ", ".join(blocked_by)
                            ),
                            retryable=True,
                            retained=False,
                            stage="dependency-coordination",
                            blocked_by=blocked_by,
                        ),
                        completed_at=self._market_now(),
                    )
                    if lease is not None:
                        self.store.release_lease(task.dataset, task.as_of, lease=lease)
                    continue
                self._execute_task(
                    task,
                    fetch_previous_limit_details=fetch_previous_limit_details,
                )
        tasks = self.store.list_collection_tasks(run_id)
        if any(task.status not in TERMINAL_TASK_STATUSES for task in tasks):
            current_run = self.store.get_collection_run(run_id)
            if current_run is None:  # pragma: no cover - defensive store contract
                raise KeyError(f"unknown collection run: {run_id}")
            return current_run
        completed = self._market_now()
        status = self._derive_run_status(tasks)
        return self.store.update_collection_run(run_id, status, completed_at=completed)

    def prepare_run_submission(
        self,
        run_id: str,
        *,
        lease_seconds: float,
    ) -> tuple[CollectionTaskRecord, ...]:
        """Reserve leases for a persisted idempotent run before executor submission."""

        if lease_seconds <= 0:
            raise ValueError("collection lease duration must be positive")
        if self.store.get_collection_run(run_id) is None:
            raise KeyError(f"unknown collection run: {run_id}")
        current = self._market_now()
        lease_now = current.astimezone(ZoneInfo("UTC"))
        for task in self.store.list_collection_tasks(run_id):
            if task.status != "queued":
                continue
            cutover_error = (
                self.fuyao_policy.preflight_error(task.dataset)
                if self.fuyao_policy is not None
                else None
            )
            if cutover_error is not None:
                retained = self.store.get(task.dataset, task.as_of) is not None
                preflight_failure = StructuredTaskFailure(
                    category=CollectionFailureCategory.CONFIGURATION,
                    message=cutover_error,
                    retryable=False,
                    retained=retained,
                    stage="preflight",
                    code="FUYAO_PREFLIGHT_REJECTED",
                )
                self.store.transition_collection_task(
                    task.task_id,
                    "failed-retained" if retained else "failed-missing",
                    expected_statuses=("queued",),
                    warning=cutover_error,
                    failure=preflight_failure,
                    completed_at=current,
                )
                continue
            owned = self.store.get_lease_token(
                task.dataset,
                task.as_of,
                owner=task.task_id,
            )
            if owned is not None and owned.expires_at > lease_now:
                continue
            active = self.store.active_collection_task(
                task.dataset,
                task.as_of,
                now=lease_now,
            )
            if active is not None and active.task_id != task.task_id:
                self.store.transition_collection_task(
                    task.task_id,
                    "busy",
                    expected_statuses=("queued",),
                    warning=f"active task {active.task_id} already holds the dataset lease",
                    failure=StructuredTaskFailure(
                        category=CollectionFailureCategory.CONCURRENCY,
                        message="another active task already holds the dataset/date lease",
                        retryable=True,
                        retained=False,
                        stage="lease-acquisition",
                    ),
                    completed_at=current,
                )
                continue
            acquired = self.store.acquire_lease(
                task.dataset,
                task.as_of,
                task.task_id,
                lease_seconds=lease_seconds,
                now=lease_now,
            )
            if not acquired:
                self.store.transition_collection_task(
                    task.task_id,
                    "busy",
                    expected_statuses=("queued",),
                    warning="another task acquired the dataset lease",
                    failure=StructuredTaskFailure(
                        category=CollectionFailureCategory.CONCURRENCY,
                        message="another task acquired the dataset/date lease",
                        retryable=True,
                        retained=False,
                        stage="lease-acquisition",
                    ),
                    completed_at=current,
                )
        return self.store.list_collection_tasks(run_id)

    def release_run_submission(self, run_id: str) -> int:
        """Release queued-task leases after executor admission rejects a run."""

        released = 0
        for task in self.store.list_collection_tasks(run_id):
            if task.status != "queued":
                continue
            lease = self.store.get_lease_token(
                task.dataset,
                task.as_of,
                owner=task.task_id,
            )
            if lease is not None and self.store.release_lease(
                task.dataset,
                task.as_of,
                lease=lease,
            ):
                released += 1
        return released

    def collect(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        fetch_previous_limit_details: bool = True,
        allow_historical_latest_only: bool = False,
    ) -> CollectionStartResult:
        started = self.start_run(
            as_of,
            datasets,
            allow_historical_latest_only=allow_historical_latest_only,
        )
        run = self.execute_run(
            started.run.run_id,
            fetch_previous_limit_details=fetch_previous_limit_details,
        )
        return CollectionStartResult(run=run, tasks=self.store.list_collection_tasks(run.run_id))

    def collect_request(self, request: CollectionRefreshRequest) -> CollectionStartResult:
        return self.collect(
            request.as_of,
            request.datasets,
            fetch_previous_limit_details=request.fetch_previous_limit_details,
            allow_historical_latest_only=request.allow_historical_latest_only,
        )

    def prepare_limit_history_sessions(self, as_of: date, count: int) -> tuple[date, ...]:
        return self.prepare_limit_history(
            LimitHistoryPreparationRequest(as_of=as_of, count=count)
        )

    def prepare_limit_history(
        self,
        request: LimitHistoryPreparationRequest,
    ) -> tuple[date, ...]:
        if self.limit_history_preparer is None:
            raise ValueError("limits history preparation is not configured")
        return self.limit_history_preparer.prepare(request)

    def get_run(self, run_id: str) -> CollectionStartResult | None:
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(now=current.astimezone(ZoneInfo("UTC")))
        run = self.store.get_collection_run(run_id)
        if run is None:
            return None
        tasks = self.store.list_collection_tasks(run_id)
        if run.status in {"queued", "collecting"} and tasks and all(
            task.status in TERMINAL_TASK_STATUSES for task in tasks
        ):
            run = self.store.update_collection_run(
                run_id,
                self._derive_run_status(tasks),
                completed_at=current,
            )
        return CollectionStartResult(run=run, tasks=tasks)

    def collection_status(self, as_of: date) -> dict[str, Any]:
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(now=current.astimezone(ZoneInfo("UTC")))
        datasets: list[dict[str, Any]] = []
        for dataset in SUPPORTED_COLLECTION_DATASETS:
            snapshot = self.store.get(dataset, as_of)
            attempt = self.store.latest_collection_attempt(dataset, as_of)
            active = self.store.active_collection_task(
                dataset,
                as_of,
                now=current.astimezone(ZoneInfo("UTC")),
            )
            historical_allowed = dataset not in LATEST_ONLY_DATASETS or as_of == effective_market_date(current)
            datasets.append(
                {
                    "dataset": dataset,
                    "available": snapshot is not None,
                    "source": snapshot.source if snapshot else "none",
                    "observations": snapshot.observations if snapshot else 0,
                    "lastSuccessAt": snapshot.fetched_at if snapshot else None,
                    "settled": snapshot.settled if snapshot else False,
                    "refreshWarning": snapshot.refresh_warning if snapshot else None,
                    "quality": (
                        dict(snapshot.payload.get("quality") or {})
                        if snapshot is not None and isinstance(snapshot.payload, dict)
                        else None
                    ),
                    "latestAttempt": attempt,
                    "activeTaskId": active.task_id if active else None,
                    "collectionAllowed": historical_allowed,
                    "restriction": None
                    if historical_allowed
                    else "该数据源只支持可验证的最新市场快照，不能采集所选历史日期",
                    "coreIndices": self.store.list_core_index_results(attempt.task_id)
                    if dataset == "core" and attempt is not None
                    else (),
                    "detail": self._collection_detail(dataset, snapshot, as_of),
                }
            )
        readiness = (
            self._sector_analysis_readiness(as_of)
            if callable(self._sector_analysis_readiness)
            else None
        )
        if isinstance(readiness, dict):
            actual = readiness.get("asOf")
            if actual not in (None, as_of, as_of.isoformat()):
                readiness = None
        return {"asOf": as_of, "datasets": datasets, "sectorAnalysis": readiness}

    def _collection_detail(
        self,
        dataset: str,
        snapshot: Any,
        as_of: date,
    ) -> dict[str, Any] | None:
        identity = DatasetDate(dataset, as_of)
        candidate = snapshot_to_candidate(snapshot) if snapshot is not None else None
        projected = self.detail_projector_registry.project(identity, candidate)
        return dict(projected) if projected is not None else None

    def validate_request(
        self,
        as_of: date,
        datasets: Iterable[str],
        *,
        allow_historical_latest_only: bool = False,
    ) -> None:
        selected = tuple(datasets)
        unknown = sorted(set(selected) - set(SUPPORTED_COLLECTION_DATASETS))
        if unknown:
            if "sectors" in unknown:
                raise ValueError(
                    "unsupported collection dataset: sectors; use industry-ranking, "
                    "sector-turnover, or sector-breadth"
                )
            raise ValueError(f"unsupported collection datasets: {', '.join(unknown)}")
        if not selected:
            raise ValueError("at least one collection dataset is required")
        current = effective_market_date(self._market_now())
        if as_of > current:
            raise ValueError("collection date cannot be later than the Shanghai market date")
        restricted = sorted(set(selected) & LATEST_ONLY_DATASETS)
        if restricted and as_of != current and not allow_historical_latest_only:
            raise ValueError(
                "latest-only datasets require the selected date to match the Shanghai market date: "
                + ", ".join(restricted)
            )

    def _expand_dependencies(
        self,
        as_of: date,
        selected: tuple[str, ...],
    ) -> tuple[str, ...]:
        expanded = set(selected)
        for dataset in reversed(SUPPORTED_COLLECTION_DATASETS):
            if dataset not in expanded:
                continue
            for dependency in DATASET_DEPENDENCIES.get(dataset, ()):
                if not self._compatible_local_dependency(dependency, as_of):
                    expanded.add(dependency)
        return tuple(dataset for dataset in SUPPORTED_COLLECTION_DATASETS if dataset in expanded)

    def _blocked_dependencies(
        self,
        task: CollectionTaskRecord,
        run_id: str,
    ) -> tuple[str, ...]:
        dependencies = DATASET_DEPENDENCIES.get(task.dataset, ())
        if not dependencies:
            return ()
        tasks = {item.dataset: item for item in self.store.list_collection_tasks(run_id)}
        blocked: list[str] = []
        for dependency in dependencies:
            if self._compatible_local_dependency(dependency, task.as_of):
                continue
            prerequisite = tasks.get(dependency)
            if prerequisite is None or prerequisite.status not in SUCCESSFUL_TASK_STATUSES:
                blocked.append(dependency)
        return tuple(blocked)

    def _compatible_local_dependency(self, dataset: str, as_of: date) -> bool:
        snapshot = self.store.get(dataset, as_of)
        if dataset not in {"industry-ranking", "sector-turnover"}:
            return snapshot is not None
        if not _accepted_ths_snapshot(snapshot, as_of):
            return False
        if dataset == "industry-ranking":
            return True
        ranking = self.store.get("industry-ranking", as_of)
        return (
            _accepted_ths_snapshot(ranking, as_of)
            and _ths_catalog_revision(snapshot) == _ths_catalog_revision(ranking)
        )

    def _execute_task(
        self,
        task: CollectionTaskRecord,
        *,
        fetch_previous_limit_details: bool = True,
    ) -> CollectionTaskRecord:
        started_at = self._market_now()
        started = time.perf_counter()
        task = self.store.transition_collection_task(
            task.task_id,
            "collecting",
            expected_statuses=("queued",),
            started_at=started_at,
        )
        lease = self.store.get_lease_token(task.dataset, task.as_of, owner=task.task_id)
        lease_now = self._market_now().astimezone(ZoneInfo("UTC"))
        if lease is not None and lease.expires_at > lease_now:
            remaining_seconds = (lease.expires_at - lease_now).total_seconds()
            lease = self.store.renew_lease(
                lease,
                lease_seconds=max(self.lease_seconds, remaining_seconds),
                now=lease_now,
            )
        if lease is None or lease.expires_at <= lease_now:
            retained = self.store.get(task.dataset, task.as_of) is not None
            return self.store.transition_collection_task(
                task.task_id,
                "failed-retained" if retained else "failed-missing",
                expected_statuses=("collecting",),
                warning="collection task lost its dataset lease before provider execution",
                failure=StructuredTaskFailure(
                    category=CollectionFailureCategory.CONCURRENCY,
                    message="collection task lost its dataset/date lease before provider execution",
                    retryable=True,
                    retained=retained,
                    stage="lease-validation",
                ),
                completed_at=started_at,
                duration_ms=self._milliseconds(started),
            )
        try:
            if task.dataset in self.typed_cutover_datasets:
                result = self._collect_and_commit(
                    task,
                    lease,
                    started,
                    fetch_previous_limit_details=fetch_previous_limit_details,
                )
            else:
                collector = self.collector_registry.get(task.dataset)
                if task.dataset == "limits":
                    result = collector.collect_task(
                        task,
                        started,
                        lease,
                        fetch_previous_limit_details=fetch_previous_limit_details,
                    )
                else:
                    result = collector.collect_task(task, started, lease)
            if (
                result.status
                in {"failed-retained", "failed-missing", "busy", "blocked"}
                and result.failure is None
            ):
                result = self.store.transition_collection_task(
                    task.task_id,
                    result.status,
                    expected_statuses=(result.status,),
                    failure=StructuredTaskFailure(
                        category=CollectionFailureCategory.INTERNAL,
                        message=result.warning or "collection task failed",
                        retryable=True,
                        retained=result.status == "failed-retained",
                        stage="collection",
                    ),
                )
            if result.status in {*SUCCESSFUL_TASK_STATUSES, "failed-retained"} and self.rebuild_aggregate is not None:
                rebuild_started = time.perf_counter()
                try:
                    self._rebuild_aggregate(task.as_of, lease, self._market_now())
                    result = self.store.transition_collection_task(
                        task.task_id,
                        result.status,
                        expected_statuses=(result.status,),
                        timings={
                            **(result.timings or {}),
                            "aggregateRebuildMs": self._milliseconds(rebuild_started),
                        },
                    )
                except Exception as exc:
                    warning = "; ".join(
                        value for value in (result.warning, f"aggregate rebuild failed: {exc}") if value
                    )
                    result = self.store.transition_collection_task(
                        task.task_id,
                        "partial" if result.status in SUCCESSFUL_TASK_STATUSES else result.status,
                        expected_statuses=(result.status,),
                        warning=warning,
                        timings={
                            **(result.timings or {}),
                            "aggregateRebuildMs": self._milliseconds(rebuild_started),
                        },
                    )
            return result
        except LeaseFenceError as exc:
            return self._fenced_task_result(task, exc, started)
        except Exception as exc:
            existing = self.store.get(task.dataset, task.as_of)
            if existing is not None:
                try:
                    self.store.set_refresh_warning(
                        task.dataset,
                        task.as_of,
                        (
                            _ths_exception_warning(task, exc, self.store)
                            if task.dataset in {
                                "industry-ranking",
                                "sector-turnover",
                                "sector-breadth",
                            }
                            else str(exc)
                        ),
                        lease=lease,
                        now=self._market_now().astimezone(ZoneInfo("UTC")),
                    )
                except LeaseFenceError as fence_exc:
                    return self._fenced_task_result(task, fence_exc, started)
            warning = (
                _ths_exception_warning(task, exc, self.store)
                if task.dataset
                in {"industry-ranking", "sector-turnover", "sector-breadth"}
                else str(exc)
            )
            result = self.store.transition_collection_task(
                task.task_id,
                "failed-retained" if existing else "failed-missing",
                expected_statuses=("collecting",),
                warning=warning,
                failure=(
                    _ths_exception_failure(task, exc, retained=existing is not None)
                    if task.dataset
                    in {"industry-ranking", "sector-turnover", "sector-breadth"}
                    else StructuredTaskFailure(
                        category=CollectionFailureCategory.INTERNAL,
                        message=str(exc),
                        retryable=True,
                        retained=existing is not None,
                        stage="collection",
                    )
                ),
                completed_at=self._market_now(),
                duration_ms=self._milliseconds(started),
            )
            if existing is not None and self.rebuild_aggregate is not None:
                rebuild_started = time.perf_counter()
                try:
                    self._rebuild_aggregate(task.as_of, lease, self._market_now())
                except Exception as rebuild_exc:
                    warning = f"{exc}; aggregate rebuild failed: {rebuild_exc}"
                    result = self.store.transition_collection_task(
                        task.task_id,
                        result.status,
                        expected_statuses=(result.status,),
                        warning=warning,
                        timings={"aggregateRebuildMs": self._milliseconds(rebuild_started)},
                    )
            return result
        finally:
            self.store.release_lease(task.dataset, task.as_of, lease=lease)

    def _fenced_task_result(
        self,
        task: CollectionTaskRecord,
        error: LeaseFenceError,
        started: float,
    ) -> CollectionTaskRecord:
        current = self.store.get_collection_task(task.task_id)
        if current is None:
            raise KeyError(f"unknown collection task: {task.task_id}")
        status = current.status
        if status not in TERMINAL_TASK_STATUSES:
            status = "failed-retained" if self.store.get(task.dataset, task.as_of) else "failed-missing"
        failure = current.failure
        if status not in SUCCESSFUL_TASK_STATUSES and failure is None:
            failure = StructuredTaskFailure(
                category=CollectionFailureCategory.CONCURRENCY,
                message="collection lease was lost and the fenced write was rejected",
                retryable=True,
                retained=status == "failed-retained",
                stage="collection-commit",
            )
        return self.store.transition_collection_task(
            task.task_id,
            status,
            expected_statuses=(current.status,),
            warning=f"lease lost; write rejected: {error}",
            failure=failure,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
        )

    def _collect_and_commit(
        self,
        task: CollectionTaskRecord,
        lease: LeaseToken,
        started: float,
        *,
        fetch_previous_limit_details: bool = True,
    ) -> CollectionTaskRecord:
        identity = DatasetDate(task.dataset, task.as_of)
        preparer = self._commit_preparers.get(task.dataset)
        context = (
            preparer.prepare(
                task,
                lease,
                fetch_previous_limit_details=fetch_previous_limit_details,
            )
            if preparer is not None
            else nullcontext(None)
        )
        with context as preparation:
            outcome = self.collector_registry.collect(identity)
            if outcome.identity != identity:
                raise ValueError("collector returned a mismatched dataset/date outcome")

            candidate_bearing_retention = (
                task.dataset == "core"
                and outcome.state is CollectionTaskState.FAILED_RETAINED
                and outcome.retained
                and outcome.candidate is not None
            )
            if outcome.state not in {
                CollectionTaskState.SUCCESS,
                CollectionTaskState.PARTIAL,
            } and not candidate_bearing_retention:
                existing = self.store.get(task.dataset, task.as_of)
                warning = outcome.warning or (
                    outcome.failure.message if outcome.failure is not None else "collection failed"
                )
                if existing is not None:
                    self.store.set_refresh_warning(
                        task.dataset,
                        task.as_of,
                        warning,
                        lease=lease,
                        now=self._market_now().astimezone(ZoneInfo("UTC")),
                    )
                return self.store.transition_collection_task(
                    task.task_id,
                    "failed-retained" if existing is not None else "failed-missing",
                    expected_statuses=("collecting",),
                    warning=warning,
                    failure=_outcome_failure(
                        outcome,
                        retained=existing is not None,
                        fallback_message=warning,
                    ),
                    completed_at=self._market_now(),
                    duration_ms=self._milliseconds(started),
                )

            if candidate_bearing_retention:
                existing = self.store.get(task.dataset, task.as_of)
                if existing is None:
                    raise ValueError(
                        "failed-retained outcome requires a same-date snapshot"
                    )
                warning = outcome.warning or (
                    outcome.failure.message
                    if outcome.failure is not None
                    else "collection failed; retained same-date snapshot"
                )
                self.store.set_refresh_warning(
                    task.dataset,
                    task.as_of,
                    warning,
                    lease=lease,
                    now=self._market_now().astimezone(ZoneInfo("UTC")),
                )

            factory = self._commit_request_factories.get(task.dataset)
            if candidate_bearing_retention and factory is None:
                raise ValueError(
                    "candidate-bearing retention requires a typed commit request factory"
                )
            request = (
                factory(task, outcome, lease, preparation)
                if factory is not None
                else DatasetCommitRequest(identity=identity, outcome=outcome, lease=lease)
            )
            committed_outcome = request.outcome
            evidence = self.committer_registry.commit(request)
            candidate = evidence.candidate
            if "collection-task" in evidence.writes:
                committed_task = self.store.get_collection_task(task.task_id)
                if committed_task is None or committed_task.status != committed_outcome.state.value:
                    raise ValueError("committer did not expose the expected atomic task state")
                return committed_task
            phase_timings = dict(candidate.timings.phases_ms)
            if candidate.timings.total_ms is not None:
                phase_timings["providerCollectionMs"] = candidate.timings.total_ms
            catalog_revision_id = _ths_catalog_revision(candidate)
            if catalog_revision_id is not None:
                phase_timings["catalogRevisionId"] = catalog_revision_id
            return self.store.transition_collection_task(
                task.task_id,
                committed_outcome.state.value,
                expected_statuses=("collecting",),
                source=candidate.source,
                observations=candidate.observations,
                warning=committed_outcome.warning,
                failure=None,
                timings=phase_timings,
                completed_at=self._market_now(),
                duration_ms=self._milliseconds(started),
                settled=candidate.settled,
            )

    def _rebuild_aggregate(self, as_of: date, lease: LeaseToken, started_at: datetime) -> None:
        callback = self.rebuild_aggregate
        if callback is None:
            return
        callback(
            as_of,
            lease=lease,
            now=started_at.astimezone(ZoneInfo("UTC")),
        )

    def _market_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=MARKET_TIME_ZONE)
        return value.astimezone(MARKET_TIME_ZONE)

    def _is_settled(self, as_of: date) -> bool:
        current = self._market_now()
        return as_of < current.date() or (
            as_of == current.date() and current.time().replace(tzinfo=None) >= settlement_time()
        )

    @staticmethod
    def _derive_run_status(tasks: tuple[CollectionTaskRecord, ...]) -> str:
        if tasks and all(task.status == "success" for task in tasks):
            return "success"
        if any(task.status in SUCCESSFUL_TASK_STATUSES for task in tasks):
            return "partial"
        return "failed"

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


def manual_refresh_enabled() -> bool:
    return os.getenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
