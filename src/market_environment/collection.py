"""Independent market dataset collection and failure isolation."""

from __future__ import annotations

import inspect
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .application.collection import DatasetCollectorRegistry
from .fuyao_config import FuyaoCollectionConfig
from .fuyao_market import FuyaoMarketAdapter
from .infrastructure.providers import (
    ActiveDirectionCollector,
    BreadthCollector,
    CoreCollector,
    FuyaoCollectionPolicy,
    LimitsCollector,
    SectorsCollector,
)
from .providers import MarketDataProvider
from .refresh import MARKET_TIME_ZONE, effective_market_date, settlement_time
from .service import MarketEnvironmentService
from .snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    SnapshotStore,
    LeaseFenceError,
    LeaseToken,
)

SUPPORTED_COLLECTION_DATASETS = (
    "core",
    "breadth",
    "limits",
    "sectors",
    "activeDirection",
)
LATEST_ONLY_DATASETS = frozenset({"breadth", "sectors", "activeDirection"})
SUCCESSFUL_TASK_STATUSES = frozenset({"success", "partial"})
TERMINAL_TASK_STATUSES = frozenset(
    {"success", "partial", "failed-retained", "failed-missing", "busy"}
)
@dataclass(frozen=True)
class CollectionStartResult:
    run: CollectionRunRecord
    tasks: tuple[CollectionTaskRecord, ...]


class CollectionCoordinator:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        store: SnapshotStore | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        lease_seconds: float = 600.0,
        rebuild_aggregate: Callable[..., Any] | None = None,
        limits_v1_enabled: bool | None = None,
        fuyao_config: FuyaoCollectionConfig | None = None,
        fuyao_adapter: FuyaoMarketAdapter | None = None,
        fuyao_policy: FuyaoCollectionPolicy | None = None,
        analysis_service: MarketEnvironmentService | None = None,
        core_collector: CoreCollector | None = None,
        breadth_collector: BreadthCollector | None = None,
        active_direction_collector: ActiveDirectionCollector | None = None,
        sectors_collector: SectorsCollector | None = None,
        limits_collector: LimitsCollector | None = None,
        collector_registry: DatasetCollectorRegistry | None = None,
    ) -> None:
        self.provider = provider or MarketDataProvider()
        self.store = store or SnapshotStore()
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        self.lease_seconds = lease_seconds
        self.rebuild_aggregate = rebuild_aggregate
        self._limits_v1_override = limits_v1_enabled
        self.fuyao_config = fuyao_config or FuyaoCollectionConfig.from_environment()
        self.fuyao_adapter = fuyao_adapter or FuyaoMarketAdapter()
        self.fuyao_policy = fuyao_policy or FuyaoCollectionPolicy(
            self.fuyao_config,
            self.store,
        )
        self._analysis_service = analysis_service or MarketEnvironmentService(
            provider=self.provider,
            persistent_cache=False,
            now=self._now,
        )
        if collector_registry is None:
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
            sectors_collector = sectors_collector or SectorsCollector(
                self.provider,
                self.store,
                market_now=self._market_now,
                is_settled=self._is_settled,
                fuyao_adapter=self.fuyao_adapter,
                fuyao_is_enabled=self.fuyao_policy.is_enabled,
                fuyao_gate_warning=self.fuyao_policy.gate_warning,
                fuyao_shadow_enabled=self.fuyao_policy.shadow_enabled,
                fuyao_revision=self.fuyao_policy.revision,
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
                    sectors_collector,
                    active_direction_collector,
                )
            )
        self.collector_registry = collector_registry
        if self.rebuild_aggregate is None:
            aggregate_service = MarketEnvironmentService(
                provider=self.provider,
                snapshot_store=self.store,
                persistent_cache=True,
                local_reads_only=True,
                now=self._now,
            )
            self.rebuild_aggregate = aggregate_service.rebuild_materialized_aggregate

    def start_run(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
    ) -> CollectionStartResult:
        selected = tuple(dict.fromkeys(datasets or SUPPORTED_COLLECTION_DATASETS))
        self.validate_request(
            as_of,
            selected,
            allow_historical_latest_only=allow_historical_latest_only,
        )
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(now=current.astimezone(ZoneInfo("UTC")))
        run_id = uuid.uuid4().hex
        run = self.store.create_collection_run(run_id, as_of, selected, created_at=current)
        tasks: list[CollectionTaskRecord] = []
        for dataset in selected:
            cutover_error = self.fuyao_policy.preflight_error(dataset)
            if cutover_error is not None:
                task_id = uuid.uuid4().hex
                task = self.store.create_collection_task(
                    task_id,
                    run_id,
                    dataset,
                    as_of,
                    queued_at=current,
                    status="failed-missing" if self.store.get(dataset, as_of) is None else "failed-retained",
                )
                task = self.store.transition_collection_task(
                    task.task_id,
                    task.status,
                    expected_statuses=(task.status,),
                    warning=cutover_error,
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
                task = self.store.create_collection_task(
                    task_id,
                    run_id,
                    dataset,
                    as_of,
                    queued_at=current,
                    status="busy",
                )
                task = self.store.transition_collection_task(
                    task.task_id,
                    "busy",
                    warning=f"active task {active.task_id} already holds the dataset lease",
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
        run = self.store.get_collection_run(run_id)
        if run is None:
            raise KeyError(f"unknown collection run: {run_id}")
        for task in self.store.list_collection_tasks(run_id):
            if task.status == "queued":
                self._execute_task(
                    task,
                    fetch_previous_limit_details=fetch_previous_limit_details,
                )
        tasks = self.store.list_collection_tasks(run_id)
        completed = self._market_now()
        status = self._derive_run_status(tasks)
        return self.store.update_collection_run(run_id, status, completed_at=completed)

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

    def prepare_limit_history_sessions(self, as_of: date, count: int) -> tuple[date, ...]:
        prepare = self._collector_method("limits", "prepare_history_sessions")
        return prepare(as_of, count)

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
        return {"asOf": as_of, "datasets": datasets}

    def _collection_detail(
        self,
        dataset: str,
        snapshot: Any,
        as_of: date,
    ) -> dict[str, Any] | None:
        collector = self.collector_registry.get(dataset)
        callback = getattr(collector, "collection_detail", None)
        return callback(snapshot, as_of) if callable(callback) else None

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
        if lease is None:
            return self.store.transition_collection_task(
                task.task_id,
                "failed-retained" if self.store.get(task.dataset, task.as_of) is not None else "failed-missing",
                expected_statuses=("collecting",),
                warning="collection task lost its dataset lease before provider execution",
                completed_at=started_at,
                duration_ms=self._milliseconds(started),
            )
        try:
            collect_task = self._collector_method(task.dataset, "collect_task")
            parameters = inspect.signature(collect_task).parameters.values()
            accepts_options = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                or parameter.name == "fetch_previous_limit_details"
                for parameter in parameters
            )
            options = (
                {"fetch_previous_limit_details": fetch_previous_limit_details}
                if accepts_options
                else {}
            )
            result = collect_task(task, started, lease, **options)
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
                        str(exc),
                        lease=lease,
                        now=self._market_now().astimezone(ZoneInfo("UTC")),
                    )
                except LeaseFenceError as fence_exc:
                    return self._fenced_task_result(task, fence_exc, started)
            result = self.store.transition_collection_task(
                task.task_id,
                "failed-retained" if existing else "failed-missing",
                expected_statuses=("collecting",),
                warning=str(exc),
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
        return self.store.transition_collection_task(
            task.task_id,
            status,
            expected_statuses=(current.status,),
            warning=f"lease lost; write rejected: {error}",
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
        )

    def _rebuild_aggregate(self, as_of: date, lease: LeaseToken, started_at: datetime) -> None:
        callback = self.rebuild_aggregate
        if callback is None:
            return
        parameters = inspect.signature(callback).parameters
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        if accepts_kwargs or {"lease", "now"} <= set(parameters):
            callback(
                as_of,
                lease=lease,
                now=started_at.astimezone(ZoneInfo("UTC")),
            )
        else:
            callback(as_of)


    def _collector_method(self, dataset: str, method: str) -> Callable[..., Any]:
        collector = self.collector_registry.get(dataset)
        callback = getattr(collector, method, None)
        if not callable(callback):
            raise TypeError(f"collector {dataset} does not implement {method}")
        return callback


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
