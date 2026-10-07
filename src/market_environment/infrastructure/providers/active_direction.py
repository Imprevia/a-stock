"""Active-direction collector preserving the Eastmoney/TDX chain."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...providers import MarketDataProvider
from ...refresh import SUCCESS_STATUSES
from ...snapshot_store import (
    CollectionTaskRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
)


class ActiveDirectionCollector:
    """Collect active direction without routing through an unapproved Fuyao path."""

    dataset_id = "activeDirection"

    def __init__(
        self,
        provider: MarketDataProvider,
        store: SnapshotStore,
        *,
        market_now: Callable[[], datetime],
        is_settled: Callable[[date], bool],
    ) -> None:
        self.provider = provider
        self.store = store
        self._market_now = market_now
        self._is_settled = is_settled

    def collect_task(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        if task.dataset != self.dataset_id:
            raise ValueError(f"ActiveDirectionCollector cannot collect {task.dataset}")
        provider_started = time.perf_counter()
        payload = copy.deepcopy(
            self.provider.fetch_chapter01_active_direction(
                task.as_of,
                allow_current_snapshot=True,
            )
        )
        provider_ms = self._milliseconds(provider_started)
        quality = self._validate_payload(task.as_of, payload)
        quality_status = str(quality["status"])
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        warning = str(quality.get("warning")) if quality.get("warning") else None
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(
                warning or f"activeDirection collection returned {quality_status}"
            )
        settled = self._is_settled(task.as_of)
        self.store.put(
            SnapshotRecord(
                dataset=self.dataset_id,
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
            "partial" if quality_status in {"partial", "fallback-derived"} else "success",
            expected_statuses=("collecting",),
            source=source,
            observations=observations,
            warning=warning,
            timings={"providerCollectionMs": provider_ms},
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    @staticmethod
    def _validate_payload(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("activeDirection collection returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("activeDirection collection payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(
                "activeDirection collection returned mismatched asOf "
                f"{quality_as_of}"
            )
        return quality

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["ActiveDirectionCollector"]
