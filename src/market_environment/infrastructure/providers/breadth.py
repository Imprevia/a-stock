"""Market breadth collector preserving established provider gates."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...fuyao_market import FuyaoMarketAdapter
from ...provider_shadow import compare_shadow
from ...providers import MarketDataProvider
from ...refresh import SUCCESS_STATUSES
from ...snapshot_store import (
    CollectionTaskRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
)


class BreadthCollector:
    """Collect breadth through Fuyao gating or the existing TDX/Eastmoney chain."""

    dataset_id = "breadth"

    def __init__(
        self,
        provider: MarketDataProvider,
        store: SnapshotStore,
        *,
        market_now: Callable[[], datetime],
        is_settled: Callable[[date], bool],
        fuyao_adapter: FuyaoMarketAdapter,
        fuyao_is_enabled: Callable[[str], bool],
        fuyao_shadow_enabled: Callable[[str], bool],
        fuyao_revision: Callable[[str], str],
    ) -> None:
        self.provider = provider
        self.store = store
        self._market_now = market_now
        self._is_settled = is_settled
        self.fuyao_adapter = fuyao_adapter
        self._fuyao_is_enabled = fuyao_is_enabled
        self._fuyao_shadow_enabled = fuyao_shadow_enabled
        self._fuyao_revision = fuyao_revision

    def collect_task(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        if task.dataset != self.dataset_id:
            raise ValueError(f"BreadthCollector cannot collect {task.dataset}")
        provider_started = time.perf_counter()
        fallback_warning: str | None = None
        try:
            payload = self._fetch(task.as_of)
        except Exception as exc:
            if self._fuyao_is_enabled(self.dataset_id):
                fallback_warning = f"扶摇采集失败，已回退现有 provider：{exc}"
                payload = self._fetch(task.as_of, use_fuyao=False)
            else:
                raise
        provider_ms = self._milliseconds(provider_started)
        payload = copy.deepcopy(payload)
        quality = self._validate_payload(task.as_of, payload)
        quality_status = str(quality["status"])
        if (
            quality_status not in SUCCESS_STATUSES
            and self._fuyao_is_enabled(self.dataset_id)
            and not fallback_warning
        ):
            fallback_warning = f"扶摇采集质量为 {quality_status}，已回退现有 provider"
            payload = copy.deepcopy(self._fetch(task.as_of, use_fuyao=False))
            quality = self._validate_payload(task.as_of, payload)
            quality_status = str(quality["status"])
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        warning = str(quality.get("warning")) if quality.get("warning") else None
        if fallback_warning:
            warning = "; ".join(
                value for value in (warning, fallback_warning) if value
            )
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(warning or f"breadth collection returned {quality_status}")
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
        timings: dict[str, Any] = {"providerCollectionMs": provider_ms}
        if fallback_warning:
            timings["fuyaoFallback"] = True
        if self._fuyao_shadow_enabled(self.dataset_id) and not self._fuyao_is_enabled(
            self.dataset_id
        ):
            try:
                candidate = self._fetch(task.as_of, use_fuyao=True)
                timings["shadow"] = compare_shadow(
                    self.dataset_id,
                    payload,
                    candidate,
                    formal_revision=source,
                    shadow_revision=self._fuyao_revision(self.dataset_id),
                    as_of=task.as_of,
                )
                shadow_status = timings["shadow"].get("status")
                if shadow_status not in {"match", "degraded"}:
                    warning = "; ".join(
                        value
                        for value in (
                            warning,
                            f"扶摇 shadow: {shadow_status}",
                        )
                        if value
                    )
            except Exception as exc:
                timings["shadow"] = {
                    "dataset": self.dataset_id,
                    "status": "insufficient",
                    "warnings": [str(exc)],
                }
                warning = "; ".join(
                    value
                    for value in (warning, f"扶摇 shadow 不可用：{exc}")
                    if value
                )
        return self.store.transition_collection_task(
            task.task_id,
            "partial" if quality_status in {"partial", "fallback-derived"} else "success",
            expected_statuses=("collecting",),
            source=source,
            observations=observations,
            warning=warning,
            timings=timings,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    def _fetch(
        self,
        as_of: date,
        *,
        use_fuyao: bool | None = None,
    ) -> dict[str, Any]:
        if use_fuyao is None:
            use_fuyao = self._fuyao_is_enabled(self.dataset_id)
        if use_fuyao:
            return self.fuyao_adapter.fetch_breadth(as_of).as_dict()
        return self.provider.fetch_chapter01_breadth(
            as_of,
            allow_current_snapshot=True,
        )

    @staticmethod
    def _validate_payload(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("breadth collection returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("breadth collection payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(
                f"breadth collection returned mismatched asOf {quality_as_of}"
            )
        return quality

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["BreadthCollector"]
