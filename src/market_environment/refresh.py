"""After-market snapshot refresh orchestration."""

from __future__ import annotations

import copy
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime, time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

from .providers import MarketDataProvider
from .snapshot_store import SnapshotRecord, SnapshotStore

MARKET_TIME_ZONE = ZoneInfo("Asia/Shanghai")
SUPPORTED_SNAPSHOT_DATASETS = ("breadth", "activeDirection")
SUCCESS_STATUSES = frozenset({"ok", "fallback", "partial"})
logger = logging.getLogger(__name__)


def settlement_time() -> clock_time:
    raw = os.getenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    try:
        hour, minute = (int(part) for part in raw.split(":"))
        return clock_time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValueError("MARKET_ENVIRONMENT_SETTLEMENT_TIME must use HH:MM") from exc


class SnapshotRefresher:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        store: SnapshotStore | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        lease_seconds: float = 120.0,
    ) -> None:
        self.provider = provider or MarketDataProvider()
        self.store = store or SnapshotStore()
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        self.lease_seconds = lease_seconds

    def refresh(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        selected = tuple(dict.fromkeys(datasets or SUPPORTED_SNAPSHOT_DATASETS))
        unknown = sorted(set(selected) - set(SUPPORTED_SNAPSHOT_DATASETS))
        if unknown:
            raise ValueError(f"unsupported snapshot datasets: {', '.join(unknown)}")
        current = self._market_now()
        self._validate_refresh_boundary(as_of, current, force=force)
        run_id = uuid.uuid4().hex
        results = [self._refresh_dataset(run_id, dataset, as_of, current) for dataset in selected]
        succeeded = sum(result["cacheResult"] == "stored" for result in results)
        if succeeded == len(results):
            status = "ok"
        elif succeeded:
            status = "partial"
        else:
            status = "failed"
        return {
            "runId": run_id,
            "asOf": as_of.isoformat(),
            "status": status,
            "forced": force,
            "datasets": results,
        }

    def _market_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=MARKET_TIME_ZONE)
        return value.astimezone(MARKET_TIME_ZONE)

    @staticmethod
    def _validate_refresh_boundary(as_of: date, current: datetime, *, force: bool) -> None:
        if force:
            return
        if as_of != current.date():
            raise ValueError("current-snapshot refresh requires --as-of to match the Shanghai market date")
        if current.time().replace(tzinfo=None) < settlement_time():
            raise ValueError("current-snapshot refresh is only allowed after the configured settlement time")

    def _refresh_dataset(
        self,
        run_id: str,
        dataset: str,
        as_of: date,
        current: datetime,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        owner = f"{os.getpid()}-{uuid.uuid4().hex}"
        lease_started = time.perf_counter()
        acquired = self.store.acquire_lease(
            dataset,
            as_of,
            owner,
            lease_seconds=self.lease_seconds,
            now=current.astimezone(ZoneInfo("UTC")),
        )
        lease_ms = self._milliseconds(lease_started)
        if not acquired:
            result = self._result(
                dataset,
                as_of,
                cache_result="busy",
                quality="refreshing",
                source="none",
                observations=0,
                settled=False,
                warning="another worker holds the refresh lease",
                started=started,
                timings={"leaseWaitMs": lease_ms},
            )
            return self._record_result(run_id, dataset, as_of, result)

        timings: dict[str, float] = {"leaseWaitMs": lease_ms}
        try:
            provider_started = time.perf_counter()
            payload = self._fetch(dataset, as_of)
            timings["providerCollectionMs"] = self._milliseconds(provider_started)

            derivation_started = time.perf_counter()
            payload = copy.deepcopy(payload)
            timings["derivationMs"] = self._milliseconds(derivation_started)

            validation_started = time.perf_counter()
            quality = self._validate_payload(dataset, as_of, payload)
            timings["validationMs"] = self._milliseconds(validation_started)
            status = str(quality["status"])
            source = str(quality.get("source") or quality.get("provider") or "none")
            observations = int(quality.get("observations") or 0)
            warnings = tuple(str(value) for value in quality.get("warnings") or [])
            warning = str(quality.get("warning")) if quality.get("warning") else None
            if status not in SUCCESS_STATUSES:
                existing = self.store.get(dataset, as_of)
                if existing is not None:
                    self.store.set_refresh_warning(dataset, as_of, warning or f"dataset refresh returned {status}")
                result = self._result(
                    dataset,
                    as_of,
                    cache_result="retained" if existing else "missing",
                    quality=status,
                    source=source,
                    observations=observations,
                    settled=False,
                    warning=warning or f"dataset refresh returned {status}",
                    started=started,
                    timings=timings,
                )
                return self._record_result(run_id, dataset, as_of, result)

            store_started = time.perf_counter()
            settled = as_of == current.date() and current.time().replace(tzinfo=None) >= settlement_time()
            record = self.store.put(
                SnapshotRecord(
                    dataset=dataset,
                    as_of=as_of,
                    payload=payload,
                    source=source,
                    status=status,
                    observations=observations,
                    warnings=warnings,
                    fetched_at=current,
                    settled=settled,
                )
            )
            timings["storeWriteMs"] = self._milliseconds(store_started)
            result = self._result(
                dataset,
                as_of,
                cache_result="stored",
                quality=record.status,
                source=record.source,
                observations=record.observations,
                settled=record.settled,
                warning=warning,
                started=started,
                timings=timings,
            )
            return self._record_result(run_id, dataset, as_of, result)
        except Exception as exc:
            existing = self.store.get(dataset, as_of)
            if existing is not None:
                self.store.set_refresh_warning(dataset, as_of, str(exc))
            result = self._result(
                dataset,
                as_of,
                cache_result="retained" if existing else "missing",
                quality="failed",
                source="none",
                observations=0,
                settled=False,
                warning=str(exc),
                started=started,
                timings=timings,
            )
            return self._record_result(run_id, dataset, as_of, result)
        finally:
            self.store.release_lease(dataset, as_of, owner)

    def _fetch(self, dataset: str, as_of: date) -> dict[str, Any]:
        if dataset == "breadth":
            return self.provider.fetch_chapter01_breadth(as_of, allow_current_snapshot=True)
        if dataset == "activeDirection":
            return self.provider.fetch_chapter01_active_direction(as_of, allow_current_snapshot=True)
        raise ValueError(f"unsupported snapshot dataset: {dataset}")

    def _record_result(
        self,
        run_id: str,
        dataset: str,
        as_of: date,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        self.store.record_refresh_result(run_id, dataset, as_of, result)
        logger.info(
            "market snapshot refresh",
            extra={
                "event": "market_snapshot_refresh",
                "dataset": dataset,
                "snapshot_as_of": as_of.isoformat(),
                "cache_result": result["cacheResult"],
                "quality_status": result["quality"],
                "duration_ms": result["durationMs"],
                "phase_timings": result["timings"],
                "refresh_warning": result["warning"],
            },
        )
        return result

    @staticmethod
    def _validate_payload(dataset: str, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(f"{dataset} refresh returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError(f"{dataset} refresh payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(f"{dataset} refresh returned mismatched asOf {quality_as_of}")
        return quality

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @classmethod
    def _result(
        cls,
        dataset: str,
        as_of: date,
        *,
        cache_result: str,
        quality: str,
        source: str,
        observations: int,
        settled: bool,
        warning: str | None,
        started: float,
        timings: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "dataset": dataset,
            "asOf": as_of.isoformat(),
            "source": source,
            "observations": observations,
            "durationMs": cls._milliseconds(started),
            "cacheResult": cache_result,
            "quality": quality,
            "settled": settled,
            "warning": warning,
            "timings": timings,
        }
