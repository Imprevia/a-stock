"""Limit-pool collector preserving detail and promotion evidence contracts."""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...limit_promotion import limit_v1_enabled
from .shadow import compare_shadow
from ...providers import MarketDataProvider
from ..collection.refresh import SUCCESS_STATUSES
from ...schemas import PROMOTION_RULE_VERSION
from ...snapshot_store import (
    CollectionTaskRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
    TradingSessionRecord,
)
from ...trading_sessions import TradingDayResolver


logger = logging.getLogger("src.market_environment.collection")


class LimitsCollector:
    """Collect limit summaries and transactionally persist normalized details."""

    dataset_id = "limits"

    def __init__(
        self,
        provider: MarketDataProvider,
        store: SnapshotStore,
        *,
        market_now: Callable[[], datetime],
        is_settled: Callable[[date], bool],
        lease_seconds: float,
        limits_v1_enabled_override: bool | None = None,
        fuyao_is_enabled: Callable[[str], bool],
        fuyao_shadow_enabled: Callable[[str], bool],
        fuyao_revision: Callable[[str], str],
    ) -> None:
        self.provider = provider
        self.store = store
        self._market_now = market_now
        self._is_settled = is_settled
        self.lease_seconds = lease_seconds
        self._limits_v1_override = limits_v1_enabled_override
        self._fuyao_is_enabled = fuyao_is_enabled
        self._fuyao_shadow_enabled = fuyao_shadow_enabled
        self._fuyao_revision = fuyao_revision

    def detail_enabled(self) -> bool:
        return (
            limit_v1_enabled()
            if self._limits_v1_override is None
            else bool(self._limits_v1_override)
        )

    def collect_task(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
        *,
        fetch_previous_limit_details: bool = True,
    ) -> CollectionTaskRecord:
        if task.dataset != self.dataset_id:
            raise ValueError(f"LimitsCollector cannot collect {task.dataset}")
        if not self.detail_enabled():
            return self._collect_legacy_summary(task, started, lease)

        fetch = getattr(
            self.provider,
            "fetch_chapter01_limit_dataset_strict",
            None,
        )
        if not callable(fetch):
            fetch = getattr(self.provider, "fetch_chapter01_limit_dataset", None)
        if not callable(fetch):
            result = self._collect_legacy_summary(task, started, lease)
            warning = "limits V1 detail collection is unavailable from this provider"
            return self.store.transition_collection_task(
                task.task_id,
                "partial",
                expected_statuses=(result.status,),
                warning=warning,
                timings=result.timings,
            )

        provider_calls = 0
        timings: dict[str, Any] = dict(task.timings or {})
        warnings: list[str] = []
        resolution = TradingDayResolver(self.store).resolve(task.as_of)
        previous_as_of = resolution.previous_as_of if resolution.sufficient else None
        if not resolution.sufficient:
            warnings.append(resolution.reason or "missing session evidence")

        if (
            fetch_previous_limit_details
            and previous_as_of is not None
            and not self._has_complete_details(previous_as_of)
        ):
            lease_started = time.perf_counter()
            previous_lease = self.store.acquire_lease(
                self.dataset_id,
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
                    timings["previousProviderCollectionMs"] = self._milliseconds(
                        previous_started
                    )
                    previous_store_started = time.perf_counter()
                    self._store_provider_result(
                        previous_as_of,
                        previous_result,
                        previous_lease,
                    )
                    timings["previousStoreWriteMs"] = self._milliseconds(
                        previous_store_started
                    )
                except Exception as exc:
                    warnings.append(f"previous session detail unavailable: {exc}")
                finally:
                    self.store.release_lease(
                        self.dataset_id,
                        previous_as_of,
                        lease=previous_lease,
                    )

        provider_started = time.perf_counter()
        current_result = fetch(task.as_of)
        provider_calls += 1
        timings["providerCollectionMs"] = self._milliseconds(provider_started)
        payload, normalization = self._unpack_provider_result(current_result)
        quality = self._validate_payload(task.as_of, payload)
        quality_status = str(quality["status"])
        source = str(quality.get("source") or quality.get("provider") or "none")
        observations = int(quality.get("observations") or 0)
        if quality_status not in SUCCESS_STATUSES:
            raise RuntimeError(
                str(
                    quality.get("warning")
                    or f"dataset collection returned {quality_status}"
                )
            )
        if normalization is None or normalization.actual_as_of != task.as_of:
            actual_as_of = getattr(normalization, "actual_as_of", None)
            raise RuntimeError(
                "limits provider date mismatch: "
                f"requested {task.as_of.isoformat()}, "
                f"actual {actual_as_of.isoformat() if actual_as_of else 'missing'}"
            )

        store_started = time.perf_counter()
        payload = self._with_normalization_warnings(
            payload,
            normalization.warnings,
        )
        snapshot = self._snapshot(
            task.as_of,
            payload,
            source,
            quality_status,
            observations,
        )
        _, checksum = self.store.put_limit_collection(
            snapshot,
            normalization,
            lease=lease,
            now=self._market_now().astimezone(ZoneInfo("UTC")),
        )
        if not normalization.complete:
            warnings.append("normalized limit detail is incomplete")
        timings["storeWriteMs"] = self._milliseconds(store_started)

        if (
            fetch_previous_limit_details
            and previous_as_of is not None
            and not self._has_complete_details(previous_as_of)
        ):
            warnings.append("previous session normalized detail is unavailable")
        status = (
            "partial"
            if warnings
            else ("partial" if quality_status == "partial" else "success")
        )
        warning = "; ".join(dict.fromkeys(warnings)) or None
        settled = self._is_settled(task.as_of)
        logger.info(
            "limit collection",
            extra={
                "event": "limit_collection",
                "requested_as_of": task.as_of.isoformat(),
                "actual_as_of": (
                    normalization.actual_as_of.isoformat()
                    if normalization is not None and normalization.actual_as_of
                    else None
                ),
                "previous_as_of": (
                    previous_as_of.isoformat() if previous_as_of else None
                ),
                "rule_version": PROMOTION_RULE_VERSION,
                "provider_calls": provider_calls,
                "excluded_count": (
                    normalization.excluded if normalization is not None else None
                ),
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

    def prepare_history_sessions(self, as_of: date, count: int) -> tuple[date, ...]:
        if count < 1:
            raise ValueError("history session count must be at least 1")
        fetch_calendar = getattr(self.provider, "fetch_trading_days", None)
        if not callable(fetch_calendar):
            raise ValueError("limits provider does not expose a trading calendar")
        calendar = tuple(fetch_calendar())
        if as_of not in calendar:
            raise ValueError(f"{as_of.isoformat()} is not a confirmed trading session")
        target_index = calendar.index(as_of)
        if target_index + 1 < count:
            raise ValueError(
                f"trading calendar has only {target_index + 1} sessions through "
                f"{as_of.isoformat()}"
            )
        selected = calendar[target_index - count + 1 : target_index + 1]
        fetched_at = self._market_now()
        for session in selected:
            calendar_index = calendar.index(session)
            previous = calendar[calendar_index - 1] if calendar_index else None
            self.store.put_trading_session(
                TradingSessionRecord(
                    as_of=session,
                    previous_as_of=previous,
                    is_session=True,
                    source="fuyao-calendar",
                    actual_as_of=session,
                    fetched_at=fetched_at,
                )
            )
        return selected

    def _collect_legacy_summary(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        provider_started = time.perf_counter()
        fallback_warning: str | None = None
        try:
            payload = self.provider.fetch_chapter01_limits(task.as_of)
        except Exception as exc:
            if self._fuyao_is_enabled(self.dataset_id):
                fallback_warning = f"扶摇采集失败，已回退现有 provider：{exc}"
                payload = self.provider.fetch_chapter01_limits(task.as_of)
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
            payload = copy.deepcopy(self.provider.fetch_chapter01_limits(task.as_of))
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
            raise RuntimeError(
                warning or f"dataset collection returned {quality_status}"
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
        timings: dict[str, Any] = {"providerCollectionMs": provider_ms}
        if fallback_warning:
            timings["fuyaoFallback"] = True
        if self._fuyao_shadow_enabled(self.dataset_id) and not self._fuyao_is_enabled(
            self.dataset_id
        ):
            try:
                candidate = self.provider.fetch_chapter01_limits(task.as_of)
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

    @staticmethod
    def _unpack_provider_result(result: Any) -> tuple[dict[str, Any], Any | None]:
        if hasattr(result, "payload"):
            return copy.deepcopy(result.payload), getattr(result, "normalization", None)
        if isinstance(result, dict) and isinstance(result.get("payload"), dict):
            return copy.deepcopy(result["payload"]), result.get("normalization")
        if isinstance(result, dict):
            return copy.deepcopy(result), None
        raise ValueError("limits collection returned an unsupported provider result")

    def _store_provider_result(
        self,
        as_of: date,
        result: Any,
        lease: LeaseToken,
    ) -> str:
        payload, normalization = self._unpack_provider_result(result)
        quality = self._validate_payload(as_of, payload)
        if str(quality["status"]) not in SUCCESS_STATUSES:
            raise RuntimeError(
                str(quality.get("warning") or "previous limits collection failed")
            )
        if normalization is None or normalization.actual_as_of != as_of:
            detail = "; ".join(getattr(normalization, "warnings", ()))
            raise ValueError(detail or "normalized limit detail is incomplete")
        payload = self._with_normalization_warnings(
            payload,
            normalization.warnings,
        )
        source = str(quality.get("source") or quality.get("provider") or "none")
        snapshot = self._snapshot(
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
            raise ValueError(
                "; ".join(normalization.warnings)
                or "normalized limit detail is incomplete"
            )
        return checksum

    def _snapshot(
        self,
        as_of: date,
        payload: dict[str, Any],
        source: str,
        status: str,
        observations: int,
    ) -> SnapshotRecord:
        return SnapshotRecord(
            dataset=self.dataset_id,
            as_of=as_of,
            payload=payload,
            source=source,
            status=status,
            observations=observations,
            warnings=tuple(
                str(value) for value in payload["quality"].get("warnings") or []
            ),
            fetched_at=self._market_now(),
            settled=self._is_settled(as_of),
        )

    @staticmethod
    def _with_normalization_warnings(
        payload: dict[str, Any],
        warnings: tuple[str, ...],
    ) -> dict[str, Any]:
        result = copy.deepcopy(payload)
        quality = result["quality"]
        combined = list(
            dict.fromkeys([*(quality.get("warnings") or []), *warnings])
        )
        quality["warnings"] = combined
        quality["warning"] = "; ".join(combined) if combined else None
        return result

    def _has_complete_details(self, as_of: date) -> bool:
        manifest = self.store.get_limit_security_dataset(as_of)
        return bool(
            manifest
            and manifest.get("membership_complete") is True
            and manifest["actual_as_of"] == as_of
            and manifest["rule_version"] == PROMOTION_RULE_VERSION
        )

    @staticmethod
    def _validate_payload(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("limits collection returned a non-object payload")
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("limits collection payload is missing quality")
        quality_as_of = quality.get("asOf")
        if quality_as_of is not None and quality_as_of != as_of.isoformat():
            raise ValueError(
                f"limits collection returned mismatched asOf {quality_as_of}"
            )
        return quality

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["LimitsCollector"]
