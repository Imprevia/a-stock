"""Application service for loading and calculating market environment data."""

from __future__ import annotations

import copy
import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Lock
from time import monotonic, perf_counter, sleep
from typing import Any
from zoneinfo import ZoneInfo

from .calculations import (
    Bar,
    amount_ratio,
    classify_index_combination,
    classify_sync_pattern,
    classify_trend,
    classify_volume_price,
    advance_efficiency_percentile,
    bullish_alignment_ratio,
    build_summary_sentence,
    build_synchronization_assessment,
    ma20_slope_percentile,
    moving_average,
    position_label,
    range_position,
)
from .providers import INDEX_SPECS, MarketDataProvider, ProviderResult
from .refresh import SnapshotRefresher
from .limit_promotion import limit_v1_enabled, without_promotion_fields
from .limit_ecosystem import build_limit_ecosystem
from .schemas import LimitEvidence, MarketEnvironmentResponse
from .snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    MATERIALIZED_COMPONENT_REVISION_KEY,
    LeaseToken,
    STORAGE_SCHEMA_VERSION,
    MaterializedAggregateRecord,
    MaterializedAggregateConflict,
    SnapshotIntegrityError,
    SnapshotStore,
    cache_state,
    payload_checksum,
    persistent_cache_enabled,
)

MARKET_TIME_ZONE = ZoneInfo("Asia/Shanghai")
CHAPTER_SECTIONS = frozenset({"breadth", "limits", "sectors", "activeDirection", "summary"})
SNAPSHOT_GROUPS = frozenset({"breadth", "activeDirection"})
CHAPTER_GROUP_KEYS = {
    "breadth": ("breadth",),
    "activeDirection": ("activeDirection",),
    "limits": ("limits",),
    "sectors": ("sectors",),
}
logger = logging.getLogger(__name__)
_MATERIALIZED_SCHEMA_VERSION_KEY = "_storageSchemaVersion"
_MATERIALIZED_LIMITS_STATE_KEY = "_limitsSnapshotState"
_MATERIALIZED_REBUILD_ATTEMPTS = 3


def market_today() -> date:
    return datetime.now(MARKET_TIME_ZONE).date()


class MarketEnvironmentService:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        ttl_seconds: int = 30,
        clock: Callable[[], float] = monotonic,
        snapshot_store: SnapshotStore | None = None,
        persistent_cache: bool | None = None,
        snapshot_ttl_seconds: int = 30,
        now: Callable[[], datetime] | None = None,
        cold_wait_seconds: float = 30.0,
        local_reads_only: bool | None = None,
    ) -> None:
        provider_was_injected = provider is not None
        self.provider = provider or MarketDataProvider()
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._now = now or (lambda: datetime.now(MARKET_TIME_ZONE))
        if persistent_cache is None:
            persistent_cache = snapshot_store is not None or (
                not provider_was_injected and persistent_cache_enabled()
            )
        self.persistent_cache = persistent_cache
        self.snapshot_store = snapshot_store or (SnapshotStore() if persistent_cache else None)
        self.local_reads_only = (
            local_reads_only
            if local_reads_only is not None
            else bool(persistent_cache and not provider_was_injected)
        )
        self.snapshot_ttl_seconds = snapshot_ttl_seconds
        self.cold_wait_seconds = cold_wait_seconds
        self._refresh_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-snapshot")
        self._core_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._chapter_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()
        self._core_load_lock = Lock()
        self._chapter_load_lock = Lock()
        self._limit_response_cache: dict[tuple[str, bool, str, str], dict[str, Any]] = {}

    def get(self, as_of: date) -> dict:
        """Return the legacy complete aggregate response."""
        if self.local_reads_only:
            return self._get_local_aggregate(as_of)
        core = self._get_core(as_of)
        provider_data = self._chapter_provider_data(core, "summary")
        chapter = self._build_chapter01(core, provider_data)
        payload = self._core_payload(core)
        payload["chapter01"] = chapter
        if chapter["status"] != "ok":
            payload["summary"]["warnings"].append("第 01 章扩展证据未完整覆盖，结论保持低置信度或数据不足")
        return payload

    def get_core(self, as_of: date) -> dict:
        """Return index data without calling Chapter 01 providers."""
        if self.local_reads_only:
            core = self._local_core_context(as_of, self._get_local_core(as_of))
            provider_data = self._missing_chapter_provider_data(
                core["effectiveDate"],
                "该接口只返回已采集的核心指数数据",
                status="missing",
            )
            # Core reads may use an existing same-date breadth snapshot, but never refresh it.
            if breadth := self._read_snapshot_group(core, "breadth", refresh_stale=False):
                provider_data.update(breadth)
            chapter = self._build_chapter01(core, provider_data)
            payload = self._core_payload(core)
            payload["chapter01"] = chapter
            return payload
        core = self._get_core(as_of)
        provider_data = self._missing_chapter_provider_data(
            core["effectiveDate"],
            "该章节数据尚未按需加载",
            status="missing",
        )
        chapter = self._build_chapter01(core, provider_data)
        payload = self._core_payload(core)
        payload["chapter01"] = chapter
        return payload

    def get_chapter01(self, as_of: date, section: str) -> dict:
        if section not in CHAPTER_SECTIONS:
            raise ValueError(f"未知第 01 章 section：{section}")
        if self.local_reads_only:
            aggregate = self._get_local_aggregate(as_of)
            return {
                "asOf": aggregate["asOf"],
                "generatedAt": aggregate["generatedAt"],
                "summary": aggregate["summary"],
                "chapter01": aggregate["chapter01"],
            }
        core = self._get_core(as_of)
        provider_data = self._chapter_provider_data(core, section)
        chapter = self._build_chapter01(core, provider_data)
        return {
            "asOf": core["asOf"],
            "generatedAt": core["generatedAt"],
            "summary": self._core_payload(core)["summary"],
            "chapter01": chapter,
        }

    def rebuild_materialized_aggregate(
        self,
        as_of: date,
        *,
        lease: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        rebuild_started = perf_counter()
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        for _attempt in range(_MATERIALIZED_REBUILD_ATTEMPTS):
            revision = self.snapshot_store.materialization_revision(as_of)
            composed = self._compose_materialized_aggregate(as_of, revision)
            if composed is None:
                return None
            validated, record = composed
            if lease is None:
                if self.snapshot_store.materialization_revision(as_of) != revision:
                    continue
                stored_record = record
                persisted = False
            else:
                try:
                    stored_record = self.snapshot_store.put_materialized_aggregate(
                        record,
                        lease=lease,
                        expected_revision=revision,
                        now=lambda: self._market_now().astimezone(ZoneInfo("UTC")),
                    )
                except MaterializedAggregateConflict:
                    continue
                persisted = True
            logger.info(
                "market aggregate rebuild",
                extra={
                    "event": "market_aggregate_rebuild",
                    "requested_as_of": as_of.isoformat(),
                    "actual_as_of": validated["asOf"],
                    "limits_v1_enabled": limit_v1_enabled(),
                    "aggregate_checksum": stored_record.checksum,
                    "component_revision": revision,
                    "persisted": persisted,
                    "rebuild_ms": round((perf_counter() - rebuild_started) * 1000, 3),
                },
            )
            return validated
        raise MaterializedAggregateConflict(
            f"materialized aggregate inputs kept changing: {as_of.isoformat()}"
        )

    def _compose_materialized_aggregate(
        self,
        as_of: date,
        revision: str,
    ) -> tuple[dict[str, Any], MaterializedAggregateRecord] | None:
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        core_record = self.snapshot_store.get("core", as_of)
        if core_record is None:
            return None
        core_payload = copy.deepcopy(core_record.payload)
        core = self._local_core_context(as_of, core_payload)
        provider_data = self._missing_chapter_provider_data(
            core["effectiveDate"],
            "该日期尚未采集对应数据集",
            status="missing",
        )
        limits_record = None
        for group in CHAPTER_GROUP_KEYS:
            record = self.snapshot_store.get(group, as_of)
            if record is not None:
                if group == "limits":
                    limits_record = record
                provider_data[group] = self._snapshot_payload(
                    record,
                    cache_state(
                        record,
                        now=self._market_now(),
                        soft_ttl_seconds=self.snapshot_ttl_seconds,
                    ),
                    refreshing=False,
                )
        provider_data["limits"] = self._limit_payload_for_response(
            as_of,
            provider_data["limits"],
        )
        chapter = self._build_chapter01(core, provider_data)
        payload = self._core_payload(core)
        payload["chapter01"] = chapter
        validated = MarketEnvironmentResponse.model_validate(payload).model_dump()
        stored_payload = {
            **validated,
            _MATERIALIZED_SCHEMA_VERSION_KEY: STORAGE_SCHEMA_VERSION,
            _MATERIALIZED_LIMITS_STATE_KEY: self._limits_snapshot_state(limits_record),
            MATERIALIZED_COMPONENT_REVISION_KEY: revision,
        }
        return validated, MaterializedAggregateRecord(
            as_of=as_of,
            payload=stored_payload,
            generated_at=self._market_now(),
        ).normalized()

    def _get_local_aggregate(self, as_of: date) -> dict[str, Any]:
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        for _attempt in range(_MATERIALIZED_REBUILD_ATTEMPTS):
            revision = self.snapshot_store.materialization_revision(as_of)
            record = self.snapshot_store.get_materialized_aggregate(as_of)
            if record is None:
                break
            payload = copy.deepcopy(record.payload)
            stored_revision = payload.pop(MATERIALIZED_COMPONENT_REVISION_KEY, None)
            stored_limits_state = payload.pop(_MATERIALIZED_LIMITS_STATE_KEY, object())
            payload.pop(_MATERIALIZED_SCHEMA_VERSION_KEY, None)
            current_limits_state = self._limits_snapshot_state(
                self.snapshot_store.get("limits", as_of)
            )
            if stored_revision != revision or stored_limits_state != current_limits_state:
                break
            self._apply_local_limits_policy(as_of, payload)
            self._apply_local_refreshing_state(as_of, payload)
            payload = self._refresh_materialized_synchronization(as_of, payload)
            if self.snapshot_store.materialization_revision(as_of) == revision:
                return payload
        payload = self.rebuild_materialized_aggregate(as_of)
        if payload is None:
            raise RuntimeError("所选日期没有已采集的核心指数快照")
        self._apply_local_refreshing_state(as_of, payload)
        return payload

    def _apply_local_limits_policy(self, as_of: date, payload: dict[str, Any]) -> None:
        chapter = payload.get("chapter01")
        if not isinstance(chapter, dict) or not isinstance(chapter.get("limits"), dict):
            return
        if self.snapshot_store is None:
            return
        record = self.snapshot_store.get("limits", as_of)
        if record is None:
            limits = self._missing_chapter_provider_data(
                as_of,
                "该日期尚未采集涨跌停数据",
                status="missing",
            )["limits"]
        else:
            limits = self._snapshot_payload(
                record,
                cache_state(
                    record,
                    now=self._market_now(),
                    soft_ttl_seconds=self.snapshot_ttl_seconds,
                ),
                refreshing=self.snapshot_store.has_active_lease("limits", as_of),
            )
        chapter["limits"] = self._limit_payload_for_response(as_of, limits)

    def _apply_local_refreshing_state(self, as_of: date, payload: dict[str, Any]) -> None:
        if self.snapshot_store is None:
            return
        chapter = payload.get("chapter01")
        if not isinstance(chapter, dict):
            return
        for group, keys in CHAPTER_GROUP_KEYS.items():
            refreshing = self.snapshot_store.has_active_lease(group, as_of)
            for key in keys:
                section = chapter.get(key)
                quality = section.get("quality") if isinstance(section, dict) else None
                if isinstance(quality, dict):
                    quality["refreshing"] = refreshing

    @staticmethod
    def _limits_snapshot_state(record: Any | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "checksum": record.checksum,
            "status": record.status,
            "refreshWarning": record.refresh_warning,
            "fetchedAt": record.fetched_at.isoformat(),
            "settled": record.settled,
        }

    def _limit_payload_for_response(self, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(payload)
        limits_enabled = limit_v1_enabled()
        if not limits_enabled:
            value = without_promotion_fields(value)
            for field in ("ladder", "stratifications", "history", "ruleEvidence", "riskEvidence", "confirmation", "invalidation"):
                value.pop(field, None)
        elif self.snapshot_store is not None:
            cache_key = (
                as_of.isoformat(),
                limits_enabled,
                payload_checksum(value),
                self.snapshot_store.materialization_revision(as_of),
            )
            cached = self._limit_response_cache.get(cache_key)
            if cached is not None:
                return copy.deepcopy(cached)
            value = build_limit_ecosystem(self.snapshot_store, as_of, value)
            promotion = {"promotionQuality": value["promotionQuality"]}
            if promotion["promotionQuality"]["status"] == "degraded":
                quality = value.get("quality")
                if isinstance(quality, dict):
                    quality["status"] = "degraded"
                    warnings = list(
                        dict.fromkeys(
                            [
                                *(quality.get("warnings") or []),
                                *(promotion["promotionQuality"].get("warnings") or []),
                            ]
                        )
                    )
                    quality["warnings"] = warnings
                    quality["warning"] = "；".join(warnings) if warnings else quality.get("warning")
            result = LimitEvidence.model_validate(value).model_dump(exclude_unset=True)
            self._limit_response_cache[cache_key] = copy.deepcopy(result)
            if len(self._limit_response_cache) > 32:
                self._limit_response_cache.pop(next(iter(self._limit_response_cache)))
            return result
        return LimitEvidence.model_validate(value).model_dump(exclude_unset=True)

    def _refresh_materialized_synchronization(self, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        """Recalculate the additive assessment when older aggregates lack the new field."""
        chapter = payload.get("chapter01")
        if not isinstance(chapter, dict):
            return payload
        breadth = chapter.get("breadth")
        if not isinstance(breadth, dict):
            breadth = self._missing_chapter_provider_data(
                date.fromisoformat(payload["asOf"]),
                "该日期尚未采集市场广度数据",
                status="missing",
            )["breadth"]
        core = self._local_core_context(as_of, payload)
        synchronization_assessment = self._synchronization_assessment(core, breadth)
        core["summary"]["synchronizationAssessment"] = synchronization_assessment
        payload["summary"] = self._core_payload(core)["summary"]
        chapter["combinationOverview"] = self._combination_overview(
            core["indices"],
            synchronization_assessment,
            breadth,
        )
        return payload

    def _get_local_core(self, as_of: date) -> dict[str, Any]:
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        record = self.snapshot_store.get("core", as_of)
        if record is None:
            raise RuntimeError("所选日期没有已采集的核心指数快照")
        return copy.deepcopy(record.payload)

    @staticmethod
    def _local_core_context(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        effective_date = date.fromisoformat(payload["asOf"])
        return {
            **copy.deepcopy(payload),
            "requestedAsOf": as_of,
            "effectiveDate": effective_date,
        }

    def _get_core(self, as_of: date) -> dict[str, Any]:
        cache_key = as_of.isoformat()
        cached = self._cache_get(self._core_cache, cache_key)
        if cached is not None:
            return cached
        with self._core_load_lock:
            cached = self._cache_get(self._core_cache, cache_key)
            if cached is not None:
                return cached
            return self._fetch_core(as_of, cache_key)

    def _fetch_core(self, as_of: date, cache_key: str) -> dict[str, Any]:
        warnings: list[str] = []
        data_gaps: list[dict[str, str]] = []
        try:
            quotes = self.provider.fetch_quotes(INDEX_SPECS)
        except Exception as exc:
            quotes = {}
            warnings.append(f"腾讯实时报价不可用：{exc}")

        results: list[tuple[object, ProviderResult | None, str | None]] = []
        for spec in INDEX_SPECS:
            try:
                expected_price = quotes.get(spec.code, {}).get("price")
                result = self.provider.fetch(spec, expected_price=expected_price, quote=quotes.get(spec.code, {}))
                results.append((spec, result, None))
            except Exception as exc:
                results.append((spec, None, str(exc)))

        if not any(result for _, result, _ in results):
            raise RuntimeError("全部指数数据源不可用")

        analyses = []
        effective_dates: list[date] = []
        for spec, result, error in results:
            if result is None:
                warnings.append(f"{spec.name}：{error or '无数据'}")
                data_gaps.append({"field": f"indices.{spec.code}", "reason": "provider-failed"})
                continue
            bars = [bar for bar in result.bars if bar.date <= as_of]
            if not bars:
                warnings.append(f"{spec.name}：所选日期前无历史数据")
                data_gaps.append({"field": f"indices.{spec.code}", "reason": "missing-today"})
                continue
            effective_dates.append(bars[-1].date)
            quote = quotes.get(spec.code, {})
            analysis = self._analyse(spec, bars, result, quote)
            analyses.append(analysis)
            if result.warning:
                warnings.append(f"{spec.name}：{result.warning}")
            if analysis["dataQuality"]["warning"] and not result.warning:
                warnings.append(f"{spec.name}：{analysis['dataQuality']['warning']}")

        if not analyses:
            raise RuntimeError("所选日期前没有可用指数数据")
        effective_date = min(effective_dates)
        for item in analyses:
            if item["dataQuality"]["warning"] is None and effective_date < as_of:
                item["dataQuality"]["warning"] = f"非交易日，已回退到 {effective_date.isoformat()}"

        trends = Counter(item["trendState"] for item in analyses)
        sync_pattern = self._sync_pattern(analyses)
        sync = sync_pattern["label"]
        dominant = trends.most_common(1)[0][0] if trends else "数据不足"
        alignment = bullish_alignment_ratio(analyses)
        core = {
            "asOf": effective_date.isoformat(),
            "generatedAt": datetime.now(MARKET_TIME_ZONE).isoformat(),
            "indices": analyses,
            "summary": {
                "synchronization": sync,
                "syncPattern": sync_pattern,
                "bullishAlignmentRatio": alignment,
                "dominantTrend": dominant,
                "warnings": warnings,
                "dataGaps": data_gaps,
            },
            "requestedAsOf": as_of,
            "effectiveDate": effective_date,
        }
        self._cache_set(self._core_cache, cache_key, core)
        return core

    def _core_payload(self, core: dict[str, Any]) -> dict[str, Any]:
        return {
            "asOf": core["asOf"],
            "generatedAt": core["generatedAt"],
            "indices": core["indices"],
            "summary": {
                "synchronization": core["summary"]["synchronization"],
                "syncPattern": core["summary"].get("syncPattern"),
                "synchronizationAssessment": core["summary"].get("synchronizationAssessment"),
                "bullishAlignmentRatio": core["summary"].get("bullishAlignmentRatio"),
                "dominantTrend": core["summary"]["dominantTrend"],
                "warnings": list(core["summary"]["warnings"]),
                "dataGaps": list(core["summary"].get("dataGaps", [])),
            },
        }

    def _chapter_provider_data(self, core: dict[str, Any], section: str) -> dict[str, Any]:
        as_of = core["effectiveDate"]
        provider_data = self._missing_chapter_provider_data(
            as_of,
            "该章节数据尚未按需加载",
            status="missing",
        )
        requested_groups = {
            "breadth": ("breadth",),
            "activeDirection": ("activeDirection",),
            "limits": ("limits",),
            "sectors": ("sectors",),
            "summary": ("breadth", "activeDirection", "limits", "sectors"),
        }[section]
        loaded = {group: self._load_chapter_group(core, group) for group in requested_groups}
        for group in CHAPTER_GROUP_KEYS:
            cached = loaded.get(group)
            if cached is None and (group not in SNAPSHOT_GROUPS or not self.persistent_cache):
                cached = self._cache_get(
                    self._chapter_cache,
                    (core["requestedAsOf"].isoformat(), group),
                )
            if cached is None and group in SNAPSHOT_GROUPS and self.persistent_cache:
                cached = self._read_snapshot_group(core, group, refresh_stale=False)
            if cached is not None:
                provider_data.update(cached)
        return provider_data

    def _load_chapter_group(self, core: dict[str, Any], group: str) -> dict[str, Any]:
        if group in SNAPSHOT_GROUPS and self.persistent_cache:
            with self._chapter_load_lock:
                return self._read_snapshot_group(core, group, refresh_stale=True)
        cache_key = (core["requestedAsOf"].isoformat(), group)
        cached = self._cache_get(self._chapter_cache, cache_key)
        if cached is not None:
            return cached
        with self._chapter_load_lock:
            cached = self._cache_get(self._chapter_cache, cache_key)
            if cached is not None:
                return cached
            return self._fetch_chapter_group(core, group, cache_key)

    def _fetch_chapter_group(
        self,
        core: dict[str, Any],
        group: str,
        cache_key: tuple[str, str],
    ) -> dict[str, Any]:
        as_of = core["effectiveDate"]
        allow_current_snapshot = core["requestedAsOf"] == market_today()
        try:
            if group == "breadth" and callable(fetch := getattr(self.provider, "fetch_chapter01_breadth", None)):
                value = {"breadth": fetch(as_of, allow_current_snapshot=allow_current_snapshot)}
            elif group == "activeDirection" and callable(
                fetch := getattr(self.provider, "fetch_chapter01_active_direction", None)
            ):
                value = {"activeDirection": fetch(as_of, allow_current_snapshot=allow_current_snapshot)}
            elif group in SNAPSHOT_GROUPS and callable(fetch := getattr(self.provider, "fetch_chapter01_stock", None)):
                stock_value = fetch(as_of, allow_current_snapshot=allow_current_snapshot)
                value = {key: stock_value[key] for key in CHAPTER_GROUP_KEYS[group]}
            elif group == "limits" and callable(fetch := getattr(self.provider, "fetch_chapter01_limits", None)):
                value = {"limits": fetch(as_of)}
            elif group == "sectors" and callable(fetch := getattr(self.provider, "fetch_chapter01_sectors", None)):
                value = {"sectors": fetch(as_of, allow_current_snapshot=allow_current_snapshot)}
            else:
                legacy = self._load_legacy_chapter(core)
                keys = CHAPTER_GROUP_KEYS[group]
                value = {key: legacy[key] for key in keys}
        except Exception as exc:
            missing = self._missing_chapter_provider_data(as_of, f"第 01 章 {group} 数据获取失败：{exc}")
            keys = CHAPTER_GROUP_KEYS[group]
            value = {key: missing[key] for key in keys}

        self._cache_set(self._chapter_cache, cache_key, value)
        return value

    def _read_snapshot_group(
        self,
        core: dict[str, Any],
        group: str,
        *,
        refresh_stale: bool,
    ) -> dict[str, Any] | None:
        if self.snapshot_store is None:
            return None
        as_of = core["effectiveDate"]
        lookup_started = perf_counter()
        refresh_generation = (
            self.snapshot_store.get_completed_refresh_generation(group, as_of)
            if refresh_stale
            else 0
        )
        record = self.snapshot_store.get(group, as_of)
        state = cache_state(
            record,
            now=self._market_now(),
            soft_ttl_seconds=self.snapshot_ttl_seconds,
        )
        lookup_ms = round((perf_counter() - lookup_started) * 1000, 3)
        logger.info(
            "market snapshot cache lookup",
            extra={
                "event": "market_snapshot_cache_lookup",
                "dataset": group,
                "snapshot_as_of": as_of.isoformat(),
                "cache_state": state,
                "lookup_ms": lookup_ms,
            },
        )
        if record is not None:
            refreshing = self.snapshot_store.has_active_lease(group, as_of)
            if state == "stale" and refresh_stale and self._allows_current_snapshot(core) and not refreshing:
                self._refresh_executor.submit(
                    self._refresh_snapshot_dataset,
                    group,
                    as_of,
                    refresh_generation,
                )
                refreshing = True
            return {group: self._snapshot_payload(record, state, refreshing=refreshing)}

        if not refresh_stale:
            return None
        if not self._allows_current_snapshot(core):
            return self._missing_snapshot_group(as_of, group, "该交易日没有持久化快照，且历史请求不使用当前数据回填")

        result = self._refresh_snapshot_dataset(group, as_of, refresh_generation)
        record = self.snapshot_store.get(group, as_of)
        if record is None and result["datasets"][0]["cacheResult"] == "busy":
            deadline = monotonic() + self.cold_wait_seconds
            while record is None and monotonic() < deadline:
                sleep(0.05)
                record = self.snapshot_store.get(group, as_of)
        if record is None:
            warning = result["datasets"][0].get("warning") or "快照刷新未生成可用结果"
            return self._missing_snapshot_group(as_of, group, warning)
        return {group: self._snapshot_payload(record, cache_state(record, now=self._market_now(), soft_ttl_seconds=self.snapshot_ttl_seconds), refreshing=False)}

    def _refresh_snapshot_dataset(
        self,
        group: str,
        as_of: date,
        observed_refresh_generation: int,
    ) -> dict[str, Any]:
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        refresher = SnapshotRefresher(
            self.provider,
            self.snapshot_store,
            now=self._now,
            lease_seconds=max(120.0, self.cold_wait_seconds),
        )
        return refresher.refresh(
            as_of,
            [group],
            force=True,
            reuse_fresh_within_seconds=self.snapshot_ttl_seconds,
            observed_refresh_generation=observed_refresh_generation,
        )

    def _snapshot_payload(self, record, state: str, *, refreshing: bool) -> dict[str, Any]:
        payload = copy.deepcopy(record.payload)
        quality = payload.get("quality")
        if isinstance(quality, dict):
            quality.pop(LIMIT_DETAIL_CHECKSUM_KEY, None)
            quality["cacheState"] = state
            quality["snapshotFetchedAt"] = record.fetched_at.isoformat()
            quality["refreshing"] = refreshing
            quality["refreshWarning"] = record.refresh_warning
            if record.refresh_warning is not None:
                quality["status"] = "degraded"
                retained_warning = f"同交易日刷新失败，保留上次成功值：{record.refresh_warning}"
                warnings = list(quality.get("warnings") or [])
                if retained_warning not in warnings:
                    warnings.append(retained_warning)
                quality["warnings"] = warnings
                quality["warning"] = "；".join(warnings)
            if state == "stale":
                stale_warning = "持久化快照已过 freshness 窗口，正在使用同交易日旧值"
                warnings = list(quality.get("warnings") or [])
                if stale_warning not in warnings:
                    warnings.append(stale_warning)
                quality["warnings"] = warnings
                quality["warning"] = "；".join(warnings) if warnings else stale_warning
        return payload

    def _missing_snapshot_group(self, as_of: date, group: str, warning: str) -> dict[str, Any]:
        missing = self._missing_chapter_provider_data(as_of, warning, status="missing")
        payload = missing[group]
        payload["quality"].update(
            {
                "cacheState": "missing",
                "snapshotFetchedAt": None,
                "refreshing": self.snapshot_store.has_active_lease(group, as_of) if self.snapshot_store else False,
                "refreshWarning": warning,
            }
        )
        return {group: payload}

    def _market_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=MARKET_TIME_ZONE)
        return value.astimezone(MARKET_TIME_ZONE)

    def _allows_current_snapshot(self, core: dict[str, Any]) -> bool:
        return core["requestedAsOf"] == self._market_now().date()

    def _load_legacy_chapter(self, core: dict[str, Any]) -> dict[str, Any]:
        cache_key = (core["requestedAsOf"].isoformat(), "legacy")
        cached = self._cache_get(self._chapter_cache, cache_key)
        if cached is not None:
            return cached
        as_of = core["effectiveDate"]
        fetch = getattr(self.provider, "fetch_chapter01", None)
        if fetch is None:
            value = self._missing_chapter_provider_data(as_of, "provider 未实现第 01 章扩展接口")
        else:
            try:
                value = fetch(as_of, allow_current_snapshot=core["requestedAsOf"] == market_today())
            except Exception as exc:
                value = self._missing_chapter_provider_data(as_of, f"第 01 章扩展接口失败：{exc}")
        self._cache_set(self._chapter_cache, cache_key, value)
        return value

    def _cache_get(self, cache: dict, key: object) -> Any | None:
        now = self._clock()
        with self._lock:
            cached = cache.get(key)
            if cached is None:
                return None
            if now - cached[0] < self.ttl_seconds:
                return cached[1]
            cache.pop(key, None)
        return None

    def _cache_set(self, cache: dict, key: object, value: Any) -> None:
        completed_at = self._clock()
        with self._lock:
            cache[key] = (completed_at, value)

    def _build_chapter01(self, core: dict[str, Any], provider_data: dict[str, Any]) -> dict:
        as_of = core["effectiveDate"]
        analyses = core["indices"]
        synchronization = core["summary"]["synchronization"]
        dominant_trend = core["summary"]["dominantTrend"]

        breadth = provider_data["breadth"]
        limits = provider_data["limits"]
        sectors = provider_data["sectors"]
        active_direction = provider_data["activeDirection"]
        events = {
            "state": "unverified",
            "items": [],
            "quality": self._quality(
                "traceable-events",
                "not-connected",
                "missing",
                0,
                as_of,
                ["未提供带来源、发布时间、有效期和失效条件的结构化事件输入"],
            ),
        }
        documents = self._chapter_documents(breadth, limits, sectors, active_direction)
        qualities = [breadth["quality"], limits["quality"], sectors["quality"], active_direction["quality"], events["quality"]]
        status_weight = {"ok": 1.0, "fallback": 0.75, "partial": 0.5, "missing": 0.0, "failed": 0.0}
        coverage = round((1.0 + sum(status_weight.get(item["status"], 0.0) for item in qualities)) / 6.0, 4)
        status = "partial" if coverage >= 0.5 else "insufficient"
        synchronization_assessment = self._synchronization_assessment(core, breadth)
        core["summary"]["synchronizationAssessment"] = synchronization_assessment
        combination_overview = self._combination_overview(analyses, synchronization_assessment, breadth)
        summary_sentence = build_summary_sentence(
            core["summary"].get("syncPattern", {}).get("label") if core["summary"].get("syncPattern") else synchronization,
            next((item.get("ma20PositionLabel") for item in analyses if item.get("ma20PositionLabel")), None),
            next((item.get("rangePosition60Label") for item in analyses if item.get("rangePosition60Label")), None),
            next((item.get("amountRatio5") for item in analyses if item.get("amountRatio5") is not None), None),
            next((item.get("volumePriceState") for item in analyses if item.get("volumePriceState")), None),
            combination_overview.get("tradingMode"),
        )

        evidence = [f"指数：{synchronization}，主导趋势 {dominant_trend}，有效指数 {len(analyses)} 个"]
        if breadth.get("validCount") is not None:
            evidence.append(
                f"广度：涨 {breadth['advanceCount']} / 跌 {breadth['declineCount']} / 平 {breadth['flatCount']}，中位涨跌幅 {breadth['medianReturn']:.2f}%"
            )
        if limits.get("limitUpCount") is not None:
            evidence.append(
                f"涨跌停：涨停 {limits['limitUpCount']}，跌停 {limits['limitDownCount']}，炸板 {limits['failedLimitUpCount']}"
            )
        if sectors.get("rows"):
            names = "、".join(item.get("name") or "未知" for item in sectors["rows"][:3])
            evidence.append(f"行业当日排名：{names}")
        if active_direction.get("summary"):
            evidence.append(f"容量方向：{active_direction['summary']}")

        risks = [
            "高位股、中位股和低位股亏钱效应尚未接入",
            "事件、政策和突发信息未提供可追溯结构化输入",
            "滚动分位和历史阈值尚未校准，不输出验证分数",
        ]
        confidence = "low" if coverage >= 0.5 else "insufficient"
        return {
            "status": status,
            "coverage": coverage,
            "documents": documents,
            "breadth": breadth,
            "limits": limits,
            "sectors": sectors,
            "activeDirection": active_direction,
            "events": events,
            "combinationOverview": combination_overview,
            "summarySentence": summary_sentence,
            "dataGaps": [
                *core["summary"].get("dataGaps", []),
                *(gap for item in analyses for gap in item.get("dataGaps", [])),
            ],
            "assessment": {
                "state": "证据不完整" if confidence == "low" else "insufficient",
                "confidence": confidence,
                "evidence": evidence,
                "risks": risks,
                "nextConfirmation": "补齐分层亏钱效应、主线连续性和可追溯事件后再确认环境分类",
                "invalidation": "任一证据日期不一致、provider 失败或风险证据显著恶化时，不使用候选判断",
            },
        }

    @classmethod
    def _missing_chapter_provider_data(cls, as_of: date, warning: str, status: str = "failed") -> dict:
        quality = cls._quality("chapter-01-extended", "none", status, 0, as_of, [warning])
        return {
            "breadth": {
                "advanceCount": None,
                "declineCount": None,
                "flatCount": None,
                "validCount": None,
                "advanceRatio": None,
                "medianReturn": None,
                "state": "insufficient",
                "quality": {**quality, "dataset": "market-breadth"},
            },
            "limits": {
                "limitUpCount": None,
                "limitDownCount": None,
                "failedLimitUpCount": None,
                "failedLimitUpRatio": None,
                "maxStreak": None,
                "state": "insufficient",
                "quality": {**quality, "dataset": "limit-pools"},
            },
            "sectors": {
                "rows": [],
                "state": "insufficient",
                "quality": {**quality, "dataset": "industry-ranking"},
            },
            "activeDirection": {
                "state": "insufficient",
                "summary": None,
                "topStocks": [],
                "quality": {**quality, "dataset": "active-direction"},
            },
        }

    @staticmethod
    def _quality(dataset: str, provider: str, status: str, observations: int, as_of: date, warnings: list[str]) -> dict:
        return {
            "dataset": dataset,
            "source": provider,
            "provider": provider,
            "status": status,
            "observations": observations,
            "asOf": as_of.isoformat(),
            "warning": "；".join(warnings) if warnings else None,
            "warnings": warnings,
        }

    @staticmethod
    def _chapter_documents(breadth: dict, limits: dict, sectors: dict, active_direction: dict) -> list[dict]:
        def evidence_status(quality: dict) -> str:
            return "partial" if quality["status"] in {"ok", "fallback", "partial"} else "insufficient"

        definitions = (
            ("01", "指数、趋势位置和成交额", "partial"),
            ("02", "上涨家数、下跌家数和涨跌幅中位数", evidence_status(breadth["quality"])),
            ("03", "涨停、跌停、炸板和连板晋级", evidence_status(limits["quality"])),
            ("04", "高位股、中位股和低位股的亏钱效应", "insufficient"),
            ("05", "主线持续性和成交额集中度", evidence_status(sectors["quality"])),
            ("06", "大成交额个股中是否出现主动进攻方向", evidence_status(active_direction["quality"])),
            ("07", "公告、政策、外围和突发事件", "unverified"),
            ("08", "如何归类市场环境", "insufficient"),
            ("09", "如何综合判断市场环境", "insufficient"),
        )
        return [
            {
                "id": doc_id,
                "title": title,
                "document": f"01-如何判断市场环境/{doc_id}.{title}.md",
                "status": status,
                "ruleVersion": "0.1",
            }
            for doc_id, title, status in definitions
        ]

    @staticmethod
    def _combination_overview(analyses: list[dict], synchronization_assessment: dict, breadth: dict) -> dict:
        breadth_available = breadth.get("advanceRatio") is not None and breadth.get("medianReturn") is not None
        strength = synchronization_assessment["conclusion"]

        matched = [item["combination"] for item in analyses if item["combination"]["matched"]]
        stage_counts = Counter(item["key"] for item in matched)
        stage_key, stage_count = stage_counts.most_common(1)[0] if stage_counts else (None, 0)
        stage_match = next((item for item in matched if item["key"] == stage_key), None)
        if stage_match and stage_count >= 3:
            stage = stage_match["state"]
        elif matched:
            stage = "组合分化"
        else:
            stage = "未形成明确组合"

        volume_states = [item["volumePriceState"] for item in analyses if item.get("volumePriceState") not in {None, "数据不足"}]
        volume_counts = Counter(volume_states)
        volume_state, volume_count = volume_counts.most_common(1)[0] if volume_counts else (None, 0)
        capital_map = {
            "上涨放量": "资金认可价格推进",
            "上涨缩量": "上涨但增量资金不足",
            "放量滞涨": "成交活跃但价格推进不足",
            "下跌缩量": "抛压或承接仍待确认",
            "放量下跌": "资金主动撤退风险",
            "量价平稳": "量价整体平稳",
        }
        capital_acceptance = capital_map.get(volume_state, "量价信号分化或未分类") if volume_count >= 3 else "量价信号分化或未分类"

        if synchronization_assessment["conclusionCode"] == "systemic-decline-confirmed" or stage == "趋势破坏或退潮":
            trading_mode = "风险控制"
        elif stage == "高位分歧或派发风险":
            trading_mode = "降低追高，等待承接"
        elif stage == "趋势加速或突破确认":
            trading_mode = "趋势跟随，防止追高"
        elif stage == "上升趋势或主升阶段":
            trading_mode = "顺势跟踪"
        elif stage == "底部修复或启动尝试":
            trading_mode = "观察修复确认"
        elif stage == "震荡轮动":
            trading_mode = "轮动应对"
        else:
            trading_mode = "保持观察"

        confidence = "medium" if synchronization_assessment["confidence"] in {"high", "medium"} and stage_count >= 3 else "low"
        evidence = [
            f"五大指数同步性：{synchronization_assessment['patternLabel']}（{synchronization_assessment['status']}）",
            f"明确组合覆盖：{len(matched)} / {len(analyses)}",
        ]
        if breadth_available:
            evidence.append(f"市场广度：上涨占比 {breadth['advanceRatio']:.0%}，中位涨跌幅 {breadth['medianReturn']:.2f}%")
        else:
            evidence.append("市场广度缺失，市场是否真强仍待确认")
        evidence.append(f"一致量价状态：{volume_state or '无'}（{volume_count} / {len(analyses)}）")
        return {
            "strength": strength,
            "stage": stage,
            "capitalAcceptance": capital_acceptance,
            "tradingMode": trading_mode,
            "confidence": confidence,
            "evidence": evidence,
        }

    @staticmethod
    def _analyse(spec, bars: list[Bar], result: ProviderResult, quote: dict) -> dict:
        ma = {f"ma{window}": moving_average(bars, window) for window in (5, 10, 20, 60)}
        ratio5 = amount_ratio(bars, 5)
        ratio20 = amount_ratio(bars, 20)
        combination = classify_index_combination(bars, ratio5)
        slope_percentile = ma20_slope_percentile(bars)
        efficiency_percentile = advance_efficiency_percentile(bars)
        close = bars[-1].close
        change_pct = quote.get("change_pct")
        if change_pct is None or quote.get("is_stale"):
            change_pct = ((close / bars[-2].close) - 1) * 100 if len(bars) > 1 and bars[-2].close else 0
        warning = result.warning
        quality_warnings: list[str] = []
        if not quote:
            quality_warnings.append("腾讯实时行情不可用，涨跌幅使用历史 K 线计算")
        if len(bars) >= 20 and range_position(bars, 20) is None:
            quality_warnings.append("20 日最高价与最低价相同，区间位置不可计算")
        if len(bars) >= 60 and range_position(bars, 60) is None:
            quality_warnings.append("60 日最高价与最低价相同，区间位置不可计算")
        if quote.get("is_stale"):
            quality_warnings.insert(0, "腾讯报价疑似停牌或过期，涨跌幅已使用历史 K 线计算")
        if quality_warnings:
            warning = "；".join(filter(None, [warning, *quality_warnings]))
        data_gaps: list[dict[str, str]] = []
        for field, metric in (("ma20SlopePercentile", slope_percentile), ("advanceEfficiencyPercentile", efficiency_percentile)):
            if metric["value"] is None:
                data_gaps.append({"field": field, "reason": metric["reason"]})
        if len(bars) < 20:
            data_gaps.append({"field": "rangePosition20", "reason": "insufficient-history"})
        elif range_position(bars, 20) is None:
            data_gaps.append({"field": "rangePosition20", "reason": "not-computable"})
        if len(bars) < 60:
            data_gaps.append({"field": "rangePosition60", "reason": "insufficient-history"})
        elif range_position(bars, 60) is None:
            data_gaps.append({"field": "rangePosition60", "reason": "not-computable"})
        history = []
        for index in range(max(0, len(bars) - 60), len(bars)):
            sample = bars[: index + 1]
            history.append(
                {
                    "date": bars[index].date.isoformat(),
                    "open": bars[index].open,
                    "close": bars[index].close,
                    "low": bars[index].low,
                    "high": bars[index].high,
                    "ma5": moving_average(sample, 5),
                    "ma10": moving_average(sample, 10),
                    "ma20": moving_average(sample, 20),
                    "ma60": moving_average(sample, 60),
                    "amount": bars[index].amount,
                }
            )
        return {
            "code": spec.code,
            "name": quote.get("name") or spec.name,
            "representative": spec.representative,
            "changePct": round(float(change_pct or 0), 2),
            "close": round(close, 2),
            "movingAverages": {key: round(value, 2) if value is not None else None for key, value in ma.items()},
            "rangePosition20": range_position(bars, 20),
            "rangePosition60": range_position(bars, 60),
            "rangePosition20Label": position_label(range_position(bars, 20)),
            "rangePosition60Label": position_label(range_position(bars, 60)),
            "ma20SlopePercentile": slope_percentile["value"],
            "advanceEfficiencyPercentile": efficiency_percentile["value"],
            "ma20SlopeConfidence": slope_percentile["confidence"],
            "advanceEfficiencyConfidence": efficiency_percentile["confidence"],
            "ma20PositionLabel": "上方" if ma["ma20"] is not None and close >= ma["ma20"] else ("下方" if ma["ma20"] is not None else None),
            "amount": round(bars[-1].amount, 2),
            "amountRatio5": round(ratio5, 2) if ratio5 is not None else None,
            "amountRatio20": round(ratio20, 2) if ratio20 is not None else None,
            "trendState": classify_trend(bars, ratio20),
            "volumePriceState": classify_volume_price(bars, ratio5),
            "combination": combination,
            "history": history,
            "dataQuality": {"source": result.source, "isStale": bool(quote.get("is_stale")), "warning": warning},
            "dataGaps": data_gaps,
        }

    @staticmethod
    def _sync_pattern(analyses: list[dict]) -> dict:
        changes = {item["name"]: item.get("changePct") for item in analyses}
        return classify_sync_pattern(changes)

    def _synchronization_assessment(self, core: dict[str, Any], breadth: dict) -> dict[str, object]:
        previous_breadth = self._previous_breadth(core)
        sync_pattern = core["summary"].get("syncPattern") or self._sync_pattern(core["indices"])
        return build_synchronization_assessment(sync_pattern, core["indices"], breadth, previous_breadth)

    def _previous_breadth(self, core: dict[str, Any]) -> dict[str, Any] | None:
        if self.snapshot_store is None:
            return None
        previous_date = self._previous_trading_date(core)
        if previous_date is None:
            return None
        try:
            record = self.snapshot_store.get("breadth", previous_date)
        except SnapshotIntegrityError as exc:
            logger.warning(
                "previous breadth snapshot rejected",
                extra={"event": "previous_breadth_snapshot_invalid", "as_of": previous_date.isoformat(), "error": str(exc)},
            )
            return None
        if record is None:
            return None
        payload = copy.deepcopy(record.payload)
        quality = payload.setdefault("quality", {})
        quality["asOf"] = previous_date.isoformat()
        return payload

    @staticmethod
    def _previous_trading_date(core: dict[str, Any]) -> date | None:
        as_of = core["effectiveDate"]
        candidates: list[date] = []
        for item in core["indices"]:
            for point in item.get("history", []):
                try:
                    observed = date.fromisoformat(point["date"])
                except (KeyError, TypeError, ValueError):
                    continue
                if observed < as_of:
                    candidates.append(observed)
        return max(candidates) if candidates else None

    @staticmethod
    def _synchronization(analyses: list[dict]) -> str:
        return MarketEnvironmentService._sync_pattern(analyses)["label"]
