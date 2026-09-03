"""Independent market dataset collection and failure isolation."""

from __future__ import annotations

import copy
import os
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .providers import INDEX_SPECS, MarketDataProvider
from .refresh import MARKET_TIME_ZONE, SUCCESS_STATUSES, settlement_time
from .service import MarketEnvironmentService
from .snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    CoreIndexResultRecord,
    SnapshotRecord,
    SnapshotStore,
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
        rebuild_aggregate: Callable[[date], None] | None = None,
    ) -> None:
        self.provider = provider or MarketDataProvider()
        self.store = store or SnapshotStore()
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        self.lease_seconds = lease_seconds
        self.rebuild_aggregate = rebuild_aggregate
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
                    completed_at=current,
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
                }
            )
        return {"asOf": as_of, "datasets": datasets}

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
        try:
            if task.dataset == "core":
                result = self._collect_core(task, started)
            else:
                result = self._collect_chapter_dataset(task, started)
            if result.status in {*SUCCESSFUL_TASK_STATUSES, "failed-retained"} and self.rebuild_aggregate is not None:
                self.rebuild_aggregate(task.as_of)
            return result
        except Exception as exc:
            existing = self.store.get(task.dataset, task.as_of)
            if existing is not None:
                self.store.set_refresh_warning(task.dataset, task.as_of, str(exc))
            result = self.store.transition_collection_task(
                task.task_id,
                "failed-retained" if existing else "failed-missing",
                expected_statuses=("collecting",),
                warning=str(exc),
                completed_at=self._market_now(),
                duration_ms=self._milliseconds(started),
            )
            if existing is not None and self.rebuild_aggregate is not None:
                self.rebuild_aggregate(task.as_of)
            return result
        finally:
            self.store.release_lease(task.dataset, task.as_of, task.task_id)

    def _collect_chapter_dataset(
        self,
        task: CollectionTaskRecord,
        started: float,
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
            )
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

    def _collect_core(
        self,
        task: CollectionTaskRecord,
        started: float,
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
                    )
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
                    )
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
        task_status = "success" if current_successes == len(INDEX_SPECS) else "partial"
        if current_successes == 0:
            task_status = "failed-retained"
        source = ",".join(sorted(set(index_sources)))
        if not source:
            source = existing.source if existing else "retained"
        warning_text = "；".join(warnings) if warnings else None
        if task_status == "failed-retained":
            self.store.set_refresh_warning("core", task.as_of, warning_text)
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
                )
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
    return os.getenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
