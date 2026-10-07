"""Core index collector extracted from the legacy collection coordinator."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...fuyao_market import FuyaoMarketAdapter, FuyaoMarketResult
from ...domain.analysis import analyze_index, build_collected_core_summary
from ...provider_shadow import compare_shadow
from ...providers import INDEX_SPECS, MarketDataProvider, ProviderResult
from ...refresh import effective_market_date
from ...snapshot_store import (
    CollectionTaskRecord,
    CoreIndexResultRecord,
    LeaseToken,
    SnapshotRecord,
    SnapshotStore,
    TradingSessionRecord,
)


class CoreCollector:
    """Collect five index sub-results while preserving exact-date retention."""

    dataset_id = "core"

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
        lease_seconds: float,
    ) -> None:
        self.provider = provider
        self.store = store
        self._market_now = market_now
        self._is_settled = is_settled
        self.fuyao_adapter = fuyao_adapter
        self._fuyao_is_enabled = fuyao_is_enabled
        self._fuyao_shadow_enabled = fuyao_shadow_enabled
        self._fuyao_revision = fuyao_revision
        self.lease_seconds = lease_seconds

    def collect_task(
        self,
        task: CollectionTaskRecord,
        started: float,
        lease: LeaseToken,
    ) -> CollectionTaskRecord:
        if task.dataset != self.dataset_id:
            raise ValueError(f"CoreCollector cannot collect {task.dataset}")
        existing = self.store.get("core", task.as_of)
        retained_by_code = {
            item["code"]: item
            for item in (existing.payload.get("indices", []) if existing else [])
            if isinstance(item, dict) and item.get("code")
        }
        warnings: list[str] = []
        fuyao_core_results: dict[str, FuyaoMarketResult] = {}
        shadow_core_results: dict[str, FuyaoMarketResult] = {}
        fuyao_core_degraded = False
        # Independent quotes are valid only for the currently observable
        # Shanghai session. Historical collection never requests live quotes.
        try:
            quotes = (
                self.provider.fetch_quotes(INDEX_SPECS)
                if task.as_of == effective_market_date(self._market_now())
                else {}
            )
        except Exception as exc:
            quotes = {}
            warnings.append(f"腾讯实时报价不可用：{exc}")
        if self._fuyao_is_enabled("core"):
            try:
                fuyao_core_results = self.fuyao_adapter.fetch_core(
                    task.as_of,
                    quotes_by_code=quotes,
                )
            except Exception as exc:
                fuyao_core_degraded = True
                warnings.append(f"扶摇核心指数采集失败，将回退现有 provider：{exc}")
        elif self._fuyao_shadow_enabled("core"):
            try:
                shadow_core_results = self.fuyao_adapter.fetch_core(
                    task.as_of,
                    quotes_by_code=quotes,
                )
            except Exception as exc:
                warnings.append(f"扶摇核心指数 shadow 不可用：{exc}")

        analyses: list[dict[str, Any]] = []
        current_successes = 0
        index_sources: list[str] = []
        effective_dates: list[date] = []
        for spec in INDEX_SPECS:
            index_started = time.perf_counter()
            try:
                quote = quotes.get(spec.code, {})
                fuyao_result = fuyao_core_results.get(spec.code)
                if fuyao_result is not None:
                    quote_available = quote.get("price") not in (None, "")
                    current_quote_missing = (
                        task.as_of == effective_market_date(self._market_now())
                        and not quote_available
                    )
                    if fuyao_result.status != "ok" or current_quote_missing:
                        fuyao_core_degraded = True
                        reason = "；".join(fuyao_result.warnings) or "扶摇核心指数契约校验失败"
                        if current_quote_missing:
                            reason = f"{reason}；当前日期缺少独立腾讯报价校验"
                        result = self.provider.fetch(
                            spec,
                            expected_price=quote.get("price"),
                            quote=quote,
                        )
                        result = ProviderResult(
                            bars=result.bars,
                            source=result.source,
                            warning="；".join(
                                value
                                for value in (
                                    result.warning,
                                    f"扶摇失败并回退：{reason}",
                                )
                                if value
                            ),
                            is_stale=result.is_stale,
                        )
                    else:
                        result = ProviderResult(
                            bars=list(fuyao_result.payload.get("bars") or []),
                            source="fuyao",
                            warning="；".join(fuyao_result.warnings) or None,
                        )
                else:
                    if self._fuyao_is_enabled("core"):
                        fuyao_core_degraded = True
                    result = self.provider.fetch(
                        spec,
                        expected_price=quote.get("price"),
                        quote=quote,
                    )
                bars = [bar for bar in result.bars if bar.date <= task.as_of]
                if not bars:
                    raise RuntimeError("所选日期前无历史数据")
                analysis = analyze_index(spec, bars, result, quote)
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
                        source=(retained or {}).get("dataQuality", {}).get(
                            "source", "none"
                        ),
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
        core_payload = {
            "asOf": effective_date.isoformat(),
            "generatedAt": self._market_now().isoformat(),
            "indices": analyses,
            "summary": build_collected_core_summary(analyses, warnings),
        }
        settled = self._is_settled(task.as_of)
        session_warning = self._persist_session_evidence(
            task.as_of,
            analyses,
            index_sources,
            lease,
        )
        if session_warning:
            warnings.append(session_warning)
        task_status = "success" if current_successes == len(INDEX_SPECS) else "partial"
        if self._fuyao_is_enabled("core") and fuyao_core_degraded and task_status == "success":
            task_status = "partial"
        if current_successes == 0:
            task_status = "failed-retained"
        source = ",".join(sorted(set(index_sources)))
        if not source:
            source = existing.source if existing else "retained"
        warning_text = "；".join(warnings) if warnings else None
        task_timings: dict[str, Any] = {}
        if shadow_core_results:
            task_timings["shadow"] = compare_shadow(
                "core",
                core_payload,
                shadow_core_results,
                formal_revision=source,
                shadow_revision=self._fuyao_revision("core"),
                as_of=task.as_of,
            )
            shadow_status = task_timings["shadow"].get("status")
            if shadow_status != "match":
                warning_text = "；".join(
                    value
                    for value in (
                        warning_text,
                        f"扶摇 shadow: {shadow_status}",
                    )
                    if value
                )
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
            timings=task_timings,
            completed_at=self._market_now(),
            duration_ms=self._milliseconds(started),
            settled=settled,
        )

    def _persist_session_evidence(
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
        source = "core-index-history:" + ",".join(
            sorted(set(sources or ["retained"]))
        )
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
                self.store.release_lease(
                    "core",
                    previous_as_of,
                    lease=previous_lease,
                )
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

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["CoreCollector"]
