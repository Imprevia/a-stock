"""Independent market dataset collection and failure isolation."""

from __future__ import annotations

import copy
import inspect
import logging
import os
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .limit_promotion import limit_v1_enabled
from .providers import INDEX_SPECS, MarketDataProvider
from .refresh import MARKET_TIME_ZONE, SUCCESS_STATUSES, settlement_time
from .schemas import PROMOTION_RULE_VERSION
from .service import MarketEnvironmentService
from .snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    CoreIndexResultRecord,
    SnapshotRecord,
    SnapshotStore,
    LeaseFenceError,
    LeaseToken,
    TradingSessionRecord,
)
from .trading_sessions import TradingDayResolver

logger = logging.getLogger(__name__)

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
    ) -> None:
        self.provider = provider or MarketDataProvider()
        self.store = store or SnapshotStore()
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        self.lease_seconds = lease_seconds
        self.rebuild_aggregate = rebuild_aggregate
        self._limits_v1_override = limits_v1_enabled
        self._analysis_service = MarketEnvironmentService(
            provider=self.provider,
            persistent_cache=False,
            now=self._now,
        )
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
    ) -> CollectionStartResult:
        selected = tuple(dict.fromkeys(datasets or SUPPORTED_COLLECTION_DATASETS))
        self.validate_request(as_of, selected)
        current = self._market_now()
        self.store.expire_inactive_collection_tasks(now=current.astimezone(ZoneInfo("UTC")))
        run_id = uuid.uuid4().hex
        run = self.store.create_collection_run(run_id, as_of, selected, created_at=current)
        tasks: list[CollectionTaskRecord] = []
        for dataset in selected:
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

    def execute_run(self, run_id: str) -> CollectionRunRecord:
        run = self.store.get_collection_run(run_id)
        if run is None:
            raise KeyError(f"unknown collection run: {run_id}")
        for task in self.store.list_collection_tasks(run_id):
            if task.status == "queued":
                self._execute_task(task)
        tasks = self.store.list_collection_tasks(run_id)
        completed = self._market_now()
        status = self._derive_run_status(tasks)
        return self.store.update_collection_run(run_id, status, completed_at=completed)

    def collect(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
    ) -> CollectionStartResult:
        started = self.start_run(as_of, datasets)
        run = self.execute_run(started.run.run_id)
        return CollectionStartResult(run=run, tasks=self.store.list_collection_tasks(run.run_id))

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
            historical_allowed = dataset not in LATEST_ONLY_DATASETS or as_of == current.date()
            datasets.append(
                {
                    "dataset": dataset,
                    "available": snapshot is not None,
                    "source": snapshot.source if snapshot else "none",
                    "observations": snapshot.observations if snapshot else 0,
                    "lastSuccessAt": snapshot.fetched_at if snapshot else None,
                    "settled": snapshot.settled if snapshot else False,
                    "refreshWarning": snapshot.refresh_warning if snapshot else None,
                    "latestAttempt": attempt,
                    "activeTaskId": active.task_id if active else None,
                    "collectionAllowed": historical_allowed,
                    "restriction": None
                    if historical_allowed
                    else "该数据源只支持可验证的最新市场快照，不能采集所选历史日期",
                    "coreIndices": self.store.list_core_index_results(attempt.task_id)
                    if dataset == "core" and attempt is not None
                    else (),
                    "detail": self._limits_collection_detail(snapshot, as_of)
                    if dataset == "limits"
                    else None,
                }
            )
        return {"asOf": as_of, "datasets": datasets}

    def _limits_detail_enabled(self) -> bool:
        return limit_v1_enabled() if self._limits_v1_override is None else bool(self._limits_v1_override)

    def _limits_collection_detail(self, snapshot: SnapshotRecord | None, as_of: date) -> dict[str, Any] | None:
        if snapshot is None:
            resolution = TradingDayResolver(self.store).resolve(as_of)
            return {
                "sampleAsOf": as_of.isoformat(),
                "previousAsOf": resolution.previous_as_of.isoformat() if resolution.previous_as_of else None,
                "excludedCount": None,
                "promotionRequired": self._limits_detail_enabled(),
                "promotionDependency": "前一真实交易日合资格收盘涨停样本 + 当前日同身份收盘涨停状态",
                "warnings": [resolution.reason] if resolution.reason else [],
            }
        payload = snapshot.payload
        quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
        manifest = self.store.get_limit_security_dataset(as_of)
        resolution = TradingDayResolver(self.store).resolve(as_of)
        previous_as_of = payload.get("promotionPreviousAsOf") or (
            resolution.previous_as_of.isoformat() if resolution.previous_as_of else None
        )
        promotion_status = (
            payload.get("promotionQuality", {}).get("status")
            if isinstance(payload.get("promotionQuality"), dict)
            else None
        )
        promotion_warnings: list[str] = []
        if self._limits_detail_enabled() and manifest is not None:
            try:
                from .limit_promotion import build_limit_promotion

                promotion = build_limit_promotion(
                    self.store,
                    as_of,
                    dataset_quality=quality,
                    emit_log=False,
                )
                promotion_quality = promotion.get("promotionQuality")
                if isinstance(promotion_quality, dict):
                    promotion_status = promotion_quality.get("status")
                    promotion_warnings = list(promotion_quality.get("warnings") or [])
            except Exception as exc:
                promotion_warnings = [str(exc)]
        return {
            "sampleAsOf": payload.get("promotionSampleAsOf") or as_of.isoformat(),
            "previousAsOf": previous_as_of,
            "excludedCount": manifest.get("excluded") if manifest else None,
            "promotionRequired": self._limits_detail_enabled(),
            "promotionDependency": "前一真实交易日合资格收盘涨停样本 + 当前日同身份收盘涨停状态",
            "promotionQuality": promotion_status,
            "detailChecksum": quality.get("_detailDatasetChecksum"),
            "warnings": list(dict.fromkeys([*(quality.get("warnings") or []), *promotion_warnings])),
        }

    def validate_request(self, as_of: date, datasets: Iterable[str]) -> None:
        selected = tuple(datasets)
        unknown = sorted(set(selected) - set(SUPPORTED_COLLECTION_DATASETS))
        if unknown:
            raise ValueError(f"unsupported collection datasets: {', '.join(unknown)}")
        if not selected:
            raise ValueError("at least one collection dataset is required")
        current = self._market_now().date()
        if as_of > current:
            raise ValueError("collection date cannot be later than the Shanghai market date")
        restricted = sorted(set(selected) & LATEST_ONLY_DATASETS)
        if restricted and as_of != current:
            raise ValueError(
                "latest-only datasets require the selected date to match the Shanghai market date: "
                + ", ".join(restricted)
            )

    def _execute_task(self, task: CollectionTaskRecord) -> CollectionTaskRecord:
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
            if task.dataset == "core":
                result = self._collect_core(task, started, lease)
            elif task.dataset == "limits" and self._limits_detail_enabled():
                result = self._collect_limits(task, started, lease)
            else:
                result = self._collect_chapter_dataset(task, started, lease)
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

    def _collect_chapter_dataset(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        provider_started = time.perf_counter()
        payload = self._fetch_chapter_dataset(task.dataset, task.as_of)
        provider_ms = self._milliseconds(provider_started)
        payload = copy.deepcopy(payload)
        quality = self._validate_payload(task.dataset, task.as_of, payload)
        quality_status = str(quality["status"])
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        warning = str(quality.get("warning")) if quality.get("warning") else None
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(warning or f"dataset collection returned {quality_status}")
        settled = self._is_settled(task.as_of)
        self.store.put(
            SnapshotRecord(
                dataset=task.dataset,
                as_of=task.as_of,
                payload=payload,
                source=source,
                status=quality_status,
                observations=observations,
                warnings=tuple(str(value) for value in quality.get("warnings") or []),
                fetched_at=self._market_now(),
                settled=settled,
            ),
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        return self.store.transition_collection_task(
            task.task_id,
            "partial" if quality_status == "partial" else "success",
            expected_statuses=("collecting",),
            source=source,
            observations=observations,
            warning=warning,
            timings={"providerCollectionMs": provider_ms},
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    def _collect_limits(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        fetch = getattr(self.provider, "fetch_chapter01_limit_dataset_strict", None)
        if not callable(fetch):
            fetch = getattr(self.provider, "fetch_chapter01_limit_dataset", None)
        if not callable(fetch):
            result = self._collect_chapter_dataset(task, started, lease)
            warning = "limits V1 detail collection is unavailable from this provider"
            return self.store.transition_collection_task(
                task.task_id,
                "partial",
                expected_statuses=(result.status,),
                warning=warning,
                timings=result.timings,
            )

        provider_calls = 0
        timings: dict[str, float] = dict(task.timings or {})
        warnings: list[str] = []
        resolution = TradingDayResolver(self.store).resolve(task.as_of)
        previous_as_of = resolution.previous_as_of if resolution.sufficient else None
        if not resolution.sufficient:
            warnings.append(resolution.reason or "missing session evidence")

        if previous_as_of is not None and not self._has_complete_limit_details(previous_as_of):
            lease_started = time.perf_counter()
            previous_lease = self.store.acquire_lease(
                "limits",
                previous_as_of,
                task.task_id,
                lease_seconds=self.lease_seconds,
                now=self._market_now().astimezone(ZoneInfo("UTC")),
            )
            timings["previousLeaseWaitMs"] = self._milliseconds(lease_started)
            if not previous_lease:
                warnings.append("previous session limit detail lease is busy")
            else:
                try:
                    previous_started = time.perf_counter()
                    previous_result = fetch(previous_as_of)
                    provider_calls += 1
                    timings["previousProviderCollectionMs"] = self._milliseconds(previous_started)
                    previous_store_started = time.perf_counter()
                    self._store_limit_provider_result(
                        previous_as_of,
                        previous_result,
                        previous_lease,
                    )
                    timings["previousStoreWriteMs"] = self._milliseconds(previous_store_started)
                except Exception as exc:
                    warnings.append(f"previous session detail unavailable: {exc}")
                finally:
                    self.store.release_lease("limits", previous_as_of, lease=previous_lease)

        provider_started = time.perf_counter()
        current_result = fetch(task.as_of)
        provider_calls += 1
        timings["providerCollectionMs"] = self._milliseconds(provider_started)
        payload, normalization = self._unpack_limit_provider_result(current_result)
        quality = self._validate_payload("limits", task.as_of, payload)
        quality_status = str(quality["status"])
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(str(quality.get("warning") or f"dataset collection returned {quality_status}"))
        if normalization is None or normalization.actual_as_of != task.as_of:
            actual_as_of = getattr(normalization, "actual_as_of", None)
            raise RuntimeError(
                "limits provider date mismatch: "
                f"requested {task.as_of.isoformat()}, "
                f"actual {actual_as_of.isoformat() if actual_as_of else 'missing'}"
            )

        store_started = time.perf_counter()
        checksum: str | None = None
        payload = self._with_normalization_warnings(payload, normalization.warnings)
        snapshot = self._limit_snapshot(task.as_of, payload, source, quality_status, observations)
        _, checksum = self.store.put_limit_collection(
            snapshot,
            normalization,
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        if not normalization.complete:
            warnings.append("normalized limit detail is incomplete")
        timings["storeWriteMs"] = self._milliseconds(store_started)

        if previous_as_of is not None and not self._has_complete_limit_details(previous_as_of):
            warnings.append("previous session normalized detail is unavailable")
        status = "partial" if warnings else ("partial" if quality_status == "partial" else "success")
        warning = "; ".join(dict.fromkeys(warnings)) or None
        settled = self._is_settled(task.as_of)
        logger.info(
            "limit collection",
            extra={
                "event": "limit_collection",
                "requested_as_of": task.as_of.isoformat(),
                "actual_as_of": normalization.actual_as_of.isoformat()
                if normalization is not None and normalization.actual_as_of
                else None,
                "previous_as_of": previous_as_of.isoformat() if previous_as_of else None,
                "rule_version": PROMOTION_RULE_VERSION,
                "provider_calls": provider_calls,
                "excluded_count": normalization.excluded if normalization is not None else None,
                "dataset_checksum": checksum,
                "phase_timings": timings,
                "warning": warning,
            },
        )
        return self.store.transition_collection_task(
            task.task_id,
            status,
            expected_statuses=("collecting",),
            source=source,
            observations=observations,
            warning=warning,
            timings=timings,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    @staticmethod
    def _unpack_limit_provider_result(result: Any) -> tuple[dict[str, Any], Any | None]:
        if hasattr(result, "payload"):
            return copy.deepcopy(result.payload), getattr(result, "normalization", None)
        if isinstance(result, dict) and isinstance(result.get("payload"), dict):
            return copy.deepcopy(result["payload"]), result.get("normalization")
        if isinstance(result, dict):
            return copy.deepcopy(result), None
        raise ValueError("limits collection returned an unsupported provider result")

    def _store_limit_provider_result(
        self,
        as_of: date,
        result: Any,
        lease: LeaseToken,
    ) -> str:
        payload, normalization = self._unpack_limit_provider_result(result)
        quality = self._validate_payload("limits", as_of, payload)
        if str(quality["status"]) not in SUCCESS_STATUSES:
            raise RuntimeError(str(quality.get("warning") or "previous limits collection failed"))
        if normalization is None or normalization.actual_as_of != as_of:
            detail = "; ".join(getattr(normalization, "warnings", ()))
            raise ValueError(detail or "normalized limit detail is incomplete")
        payload = self._with_normalization_warnings(payload, normalization.warnings)
        source = str(quality.get("source") or quality.get("provider") or "none")
        snapshot = self._limit_snapshot(
            as_of,
            payload,
            source,
            str(quality["status"]),
            int(quality.get("observations") or 0),
        )
        _, checksum = self.store.put_limit_collection(
            snapshot,
            normalization,
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        if not normalization.complete:
            raise ValueError("; ".join(normalization.warnings) or "normalized limit detail is incomplete")
        return checksum

    def _limit_snapshot(
        self,
        as_of: date,
        payload: dict[str, Any],
        source: str,
        status: str,
        observations: int,
    ) -> SnapshotRecord:
        return SnapshotRecord(
            dataset="limits",
            as_of=as_of,
            payload=payload,
            source=source,
            status=status,
            observations=observations,
            warnings=tuple(str(value) for value in payload["quality"].get("warnings") or []),
            fetched_at=self._market_now(),
            settled=self._is_settled(as_of),
        )

    @staticmethod
    def _with_normalization_warnings(payload: dict[str, Any], warnings: tuple[str, ...]) -> dict[str, Any]:
        result = copy.deepcopy(payload)
        quality = result["quality"]
        combined = list(dict.fromkeys([*(quality.get("warnings") or []), *warnings]))
        quality["warnings"] = combined
        quality["warning"] = "; ".join(combined) if combined else None
        return result

    def _has_complete_limit_details(self, as_of: date) -> bool:
        manifest = self.store.get_limit_security_dataset(as_of)
        return bool(
            manifest
            and manifest["complete"]
            and manifest["actual_as_of"] == as_of
            and manifest["rule_version"] == PROMOTION_RULE_VERSION
        )

    def _collect_core(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        existing = self.store.get("core", task.as_of)
        retained_by_code = {
            item["code"]: item
            for item in (existing.payload.get("indices", []) if existing else [])
            if isinstance(item, dict) and item.get("code")
        }
        warnings: list[str] = []
        try:
            quotes = self.provider.fetch_quotes(INDEX_SPECS) if task.as_of == self._market_now().date() else {}
        except Exception as exc:
            quotes = {}
            warnings.append(f"腾讯实时报价不可用：{exc}")

        analyses: list[dict[str, Any]] = []
        current_successes = 0
        index_sources: list[str] = []
        effective_dates: list[date] = []
        for spec in INDEX_SPECS:
            index_started = time.perf_counter()
            try:
                quote = quotes.get(spec.code, {})
                result = self.provider.fetch(
                    spec,
                    expected_price=quote.get("price"),
                    quote=quote,
                )
                bars = [bar for bar in result.bars if bar.date <= task.as_of]
                if not bars:
                    raise RuntimeError("所选日期前无历史数据")
                analysis = self._analysis_service._analyse(spec, bars, result, quote)
                analyses.append(analysis)
                effective_dates.append(bars[-1].date)
                current_successes += 1
                index_sources.append(result.source)
                warning = result.warning or analysis["dataQuality"].get("warning")
                if warning:
                    warnings.append(f"{spec.name}：{warning}")
                self.store.put_core_index_result(
                    CoreIndexResultRecord(
                        task_id=task.task_id,
                        code=spec.code,
                        name=spec.name,
                        status="success",
                        source=result.source,
                        observations=len(bars),
                        warning=warning,
                        duration_ms=self._milliseconds(index_started),
                        payload=analysis,
                    ),
                    lease=lease,
                    now=self._market_now().astimezone(ZoneInfo("UTC")),
                )
            except Exception as exc:
                # Core sub-results retain only an exact-date index value; cross-date fallback is forbidden.
                retained = retained_by_code.get(spec.code)
                status = "failed-retained" if retained is not None else "failed-missing"
                if retained is not None:
                    analyses.append(copy.deepcopy(retained))
                    retained_date = retained.get("history", [{}])[-1].get("date")
                    if retained_date:
                        effective_dates.append(date.fromisoformat(retained_date))
                warnings.append(f"{spec.name}：{exc}")
                self.store.put_core_index_result(
                    CoreIndexResultRecord(
                        task_id=task.task_id,
                        code=spec.code,
                        name=spec.name,
                        status=status,
                        source=(retained or {}).get("dataQuality", {}).get("source", "none"),
                        observations=len((retained or {}).get("history", [])),
                        warning=str(exc),
                        duration_ms=self._milliseconds(index_started),
                        payload=copy.deepcopy(retained) if retained is not None else None,
                    ),
                    lease=lease,
                    now=self._market_now().astimezone(ZoneInfo("UTC")),
                )

        if not analyses:
            raise RuntimeError("全部指数数据源不可用且没有同日期可保留结果")
        effective_date = min(effective_dates) if effective_dates else task.as_of
        trends = Counter(item["trendState"] for item in analyses)
        core_payload = {
            "asOf": effective_date.isoformat(),
            "generatedAt": self._market_now().isoformat(),
            "indices": analyses,
            "summary": {
                "synchronization": self._analysis_service._synchronization(analyses),
                "dominantTrend": trends.most_common(1)[0][0] if trends else "数据不足",
                "warnings": warnings,
            },
        }
        settled = self._is_settled(task.as_of)
        session_warning = self._persist_core_session_evidence(task.as_of, analyses, index_sources, lease)
        if session_warning:
            warnings.append(session_warning)
        task_status = "success" if current_successes == len(INDEX_SPECS) else "partial"
        if current_successes == 0:
            task_status = "failed-retained"
        source = ",".join(sorted(set(index_sources)))
        if not source:
            source = existing.source if existing else "retained"
        warning_text = "；".join(warnings) if warnings else None
        if task_status == "failed-retained":
            self.store.set_refresh_warning(
                "core",
                task.as_of,
                warning_text,
                lease=lease,
                now=self._market_now().astimezone(ZoneInfo("UTC")),
            )
        else:
            self.store.put(
                SnapshotRecord(
                    dataset="core",
                    as_of=task.as_of,
                    payload=core_payload,
                    source=source,
                    status="ok" if task_status == "success" else "partial",
                    observations=len(analyses),
                    warnings=tuple(warnings),
                    fetched_at=self._market_now(),
                    settled=settled,
                ),
                lease=lease,
                now=self._market_now().astimezone(ZoneInfo("UTC")),
            )
        return self.store.transition_collection_task(
            task.task_id,
            task_status,
            expected_statuses=("collecting",),
            source=source,
            observations=len(analyses),
            warning=warning_text,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    def _persist_core_session_evidence(
        self,
        as_of: date,
        analyses: list[dict[str, Any]],
        sources: list[str],
        lease: LeaseToken,
    ) -> str | None:
        histories: list[list[date]] = []
        for analysis in analyses:
            dates = [
                date.fromisoformat(point["date"])
                for point in analysis.get("history", [])
                if isinstance(point, dict) and point.get("date")
            ]
            if len(dates) < 2 or dates[-1] != as_of:
                return "core index history could not prove the requested session"
            histories.append(dates)
        if not histories:
            return "core index history did not contain session evidence"
        previous_dates = {history[-2] for history in histories}
        if len(previous_dates) != 1:
            return "core indices did not agree on the previous trading session"
        previous_as_of = next(iter(previous_dates))
        prior_dates = {history[-3] for history in histories if len(history) >= 3}
        prior_as_of = next(iter(prior_dates)) if len(prior_dates) == 1 else None
        source = "core-index-history:" + ",".join(sorted(set(sources or ["retained"])))
        fetched_at = self._market_now()
        lease_now = self._market_now().astimezone(ZoneInfo("UTC"))
        previous_lease = self.store.acquire_lease(
            "core",
            previous_as_of,
            lease.owner,
            lease_seconds=self.lease_seconds,
            now=lease_now,
        )
        warning = None
        if previous_lease is None:
            warning = "previous session core lease is busy; retained existing session evidence"
        else:
            try:
                self.store.put_trading_session(
                    TradingSessionRecord(
                        previous_as_of,
                        prior_as_of,
                        True,
                        source,
                        actual_as_of=previous_as_of,
                        fetched_at=fetched_at,
                    ),
                    lease=previous_lease,
                    now=self._market_now().astimezone(ZoneInfo("UTC")),
                )
            finally:
                self.store.release_lease("core", previous_as_of, lease=previous_lease)
        self.store.put_trading_session(
            TradingSessionRecord(
                as_of,
                previous_as_of,
                True,
                source,
                actual_as_of=as_of,
                fetched_at=fetched_at,
            ),
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        return warning

    def _fetch_chapter_dataset(self, dataset: str, as_of: date) -> dict[str, Any]:
        if dataset == "breadth":
            return self.provider.fetch_chapter01_breadth(as_of, allow_current_snapshot=True)
        if dataset == "limits":
            return self.provider.fetch_chapter01_limits(as_of)
        if dataset == "sectors":
            return self.provider.fetch_chapter01_sectors(as_of, allow_current_snapshot=True)
        if dataset == "activeDirection":
            return self.provider.fetch_chapter01_active_direction(
                as_of,
                allow_current_snapshot=True,
            )
        raise ValueError(f"unsupported collection dataset: {dataset}")

    @staticmethod
    def _validate_payload(dataset: str, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(f"{dataset} collection returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError(f"{dataset} collection payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(f"{dataset} collection returned mismatched asOf {quality_as_of}")
        return quality

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
