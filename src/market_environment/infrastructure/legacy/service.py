"""Application service for loading and calculating market environment data."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Lock
from time import monotonic, perf_counter, sleep
from typing import Any
from zoneinfo import ZoneInfo

from ...application.commands.materialized_aggregate import (
    MaterializedAggregateComposer,
    MaterializedAggregateRebuilder,
)
from ...application.queries.breadth_analysis import BreadthHistoryReader
from ...application.queries.limit_ecosystem import LimitEcosystemComposer
from ...calculations import (
    Bar,
    build_summary_sentence,
    build_market_review_evidence,
    build_review_sentence,
)
from ...domain.analysis import (
    analyze_index,
    analyze_breadth,
    build_core_summary,
    combination_overview,
    previous_trading_date,
    percentile_value,
    sync_pattern,
    synchronization_assessment,
    synchronization_label,
)
from ...providers import INDEX_SPECS, MarketDataProvider, ProviderResult
from ...refresh import SnapshotRefresher, effective_market_date
from ...limit_promotion import limit_v1_enabled, without_promotion_fields
from ...limit_ecosystem import build_limit_ecosystem
from ...schemas import BreadthHistoryEvidence, BreadthHistoryPoint, EvidenceQuality, LimitEvidence, MarketEnvironmentResponse, MetricQuality
from ...snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    MATERIALIZED_COMPONENT_REVISION_KEY,
    LeaseToken,
    STORAGE_SCHEMA_VERSION,
    MaterializedAggregateRecord,
    MaterializedAggregateConflict,
    SnapshotIntegrityError,
    SnapshotRecord,
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


def market_today(now: datetime | None = None) -> date:
    """Return the effective Shanghai market date, not a pre-open calendar date."""

    return effective_market_date(now)


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
        refresh_executor: Any | None = None,
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
        self._refresh_executor = refresh_executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="market-snapshot",
        )
        self._core_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._chapter_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()
        self._core_load_lock = Lock()
        self._chapter_load_lock = Lock()
        self._limit_ecosystem_composer = LimitEcosystemComposer(
            self.snapshot_store,
            enabled=limit_v1_enabled,
            strip_disabled_fields=without_promotion_fields,
            build_ecosystem=build_limit_ecosystem,
            validate=lambda value: LimitEvidence.model_validate(value).model_dump(
                exclude_unset=True
            ),
            checksum=payload_checksum,
        )
        self._limit_response_cache = self._limit_ecosystem_composer.cache
        self._breadth_history_reader = BreadthHistoryReader(
            self.snapshot_store,
            integrity_error=SnapshotIntegrityError,
        )
        self._materialized_aggregate_composer = MaterializedAggregateComposer(
            repository=self.snapshot_store,
            market_now=self._market_now,
            snapshot_ttl_seconds=self.snapshot_ttl_seconds,
            chapter_group_keys=CHAPTER_GROUP_KEYS,
            local_core_context=self._local_core_context,
            missing_chapter_provider_data=self._missing_chapter_provider_data,
            snapshot_payload=self._snapshot_payload,
            cache_state=cache_state,
            limit_payload_for_response=self._limit_payload_for_response,
            build_chapter01=self._build_chapter01,
            core_payload=self._core_payload,
            validate_response=lambda payload: MarketEnvironmentResponse.model_validate(
                payload
            ).model_dump(),
            limits_snapshot_state=self._limits_snapshot_state,
            record_factory=lambda as_of, payload, generated_at: MaterializedAggregateRecord(
                as_of=as_of,
                payload=payload,
                generated_at=generated_at,
            ).normalized(),
            storage_schema_version=STORAGE_SCHEMA_VERSION,
            schema_version_key=_MATERIALIZED_SCHEMA_VERSION_KEY,
            limits_state_key=_MATERIALIZED_LIMITS_STATE_KEY,
            component_revision_key=MATERIALIZED_COMPONENT_REVISION_KEY,
        )
        self._materialized_aggregate_rebuilder = MaterializedAggregateRebuilder(
            repository=self.snapshot_store,
            composer=self._materialized_aggregate_composer,
            market_now=self._market_now,
            utc_now_factory=lambda: self._market_now().astimezone(ZoneInfo("UTC")),
            limits_v1_enabled=limit_v1_enabled,
            conflict_error=MaterializedAggregateConflict,
            attempts=_MATERIALIZED_REBUILD_ATTEMPTS,
        )

    def close(self) -> None:
        """Release the refresh executor owned by the composition container."""

        shutdown = getattr(self._refresh_executor, "shutdown", None)
        if shutdown is None:
            return
        try:
            shutdown(wait=True, cancel_futures=True)
        except TypeError:
            shutdown(wait=True)

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

    def get_next_session_comparison(self, as_of: date) -> dict[str, Any]:
        """Read an exact next trading session without invoking any provider.

        Trading sessions are the authority for date navigation.  We deliberately
        read existing snapshots/materialized aggregates only; a missing next
        session payload is a pending/insufficient result rather than a refresh.
        """

        requested = as_of.isoformat()
        base: dict[str, Any] = {
            "status": "insufficient",
            "requestedAsOf": requested,
            "currentAsOf": None,
            "nextAsOf": None,
            "current": None,
            "next": None,
            "deltas": {},
            "warnings": [],
        }
        if self.snapshot_store is None:
            base["warnings"] = ["持久化快照未启用，无法解析精确下一交易日"]
            return base
        try:
            sessions = tuple(
                item for item in self.snapshot_store.list_trading_sessions()
                if item.is_session and item.as_of > as_of
            )
        except SnapshotIntegrityError as exc:
            base["warnings"] = [f"交易日证据校验失败：{exc}"]
            return base
        if not sessions:
            base["warnings"] = ["本地没有严格晚于当前日期的真实交易日"]
            return base
        next_date = min(item.as_of for item in sessions)
        base["nextAsOf"] = next_date.isoformat()
        contexts: dict[date, tuple[dict[str, Any] | None, list[str]]] = {}
        for target in (as_of, next_date):
            contexts[target] = self._read_exact_review_context(target)
        current_evidence, current_warnings = contexts[as_of]
        next_evidence, next_warnings = contexts[next_date]
        base["warnings"] = list(dict.fromkeys([*current_warnings, *next_warnings]))
        if current_evidence is None:
            base["warnings"].append("当前日期缺少精确核心指数或市场广度快照")
            return base
        base["currentAsOf"] = as_of.isoformat()
        base["current"] = current_evidence
        if next_evidence is None:
            base["status"] = "pending"
            base["warnings"].append(f"下一真实交易日 {next_date.isoformat()} 的核心或广度聚合尚未就绪")
            return base
        base["next"] = next_evidence
        base["status"] = "available"
        base["deltas"] = self._review_evidence_deltas(current_evidence, next_evidence)
        return base

    def _read_exact_review_context(self, as_of: date) -> tuple[dict[str, Any] | None, list[str]]:
        """Return a review evidence object from one exact date, read-only."""

        if self.snapshot_store is None:
            return None, []
        warnings: list[str] = []
        payload: dict[str, Any] | None = None
        try:
            aggregate = self.snapshot_store.get_materialized_aggregate(as_of)
        except SnapshotIntegrityError as exc:
            return None, [f"{as_of.isoformat()} 聚合校验失败：{exc}"]
        if aggregate is not None:
            payload = copy.deepcopy(aggregate.payload)
            payload.pop(_MATERIALIZED_SCHEMA_VERSION_KEY, None)
            payload.pop(_MATERIALIZED_LIMITS_STATE_KEY, None)
            payload.pop(MATERIALIZED_COMPONENT_REVISION_KEY, None)
        else:
            try:
                core_record = self.snapshot_store.get("core", as_of)
                breadth_record = self.snapshot_store.get("breadth", as_of)
            except SnapshotIntegrityError as exc:
                return None, [f"{as_of.isoformat()} 快照校验失败：{exc}"]
            if core_record is None:
                return None, [f"{as_of.isoformat()} 缺少精确核心指数快照"]
            payload = copy.deepcopy(core_record.payload)
            if breadth_record is not None:
                payload.setdefault("chapter01", {})["breadth"] = copy.deepcopy(breadth_record.payload)
            else:
                warnings.append(f"{as_of.isoformat()} 缺少精确市场广度快照")
        if isinstance(payload, dict) and payload.get("asOf") not in (None, as_of.isoformat()):
            return None, [*warnings, f"{as_of.isoformat()} 聚合实际日期与请求日期不一致"]
        indices = payload.get("indices") if isinstance(payload, dict) else None
        summary = payload.get("summary") if isinstance(payload, dict) else None
        chapter = payload.get("chapter01") if isinstance(payload, dict) else None
        breadth = chapter.get("breadth") if isinstance(chapter, dict) else None
        if not isinstance(breadth, dict):
            try:
                breadth_record = self.snapshot_store.get("breadth", as_of)
            except SnapshotIntegrityError as exc:
                return None, [*warnings, f"{as_of.isoformat()} 市场广度快照校验失败：{exc}"]
            if breadth_record is not None:
                breadth = copy.deepcopy(breadth_record.payload)
                if isinstance(chapter, dict):
                    chapter["breadth"] = breadth
        if not isinstance(indices, list) or not isinstance(summary, dict) or not isinstance(breadth, dict):
            return None, [*warnings, f"{as_of.isoformat()} 缺少核心指数或市场广度聚合"]
        breadth_quality = breadth.get("quality")
        if isinstance(breadth_quality, dict) and breadth_quality.get("asOf") not in (None, as_of.isoformat()):
            return None, [*warnings, f"{as_of.isoformat()} 市场广度实际日期与请求日期不一致"]
        sync = summary.get("syncPattern") or self._sync_pattern(indices)
        evidence = chapter.get("marketEvidence") if isinstance(chapter, dict) else None
        if not isinstance(evidence, dict):
            evidence = build_market_review_evidence(indices, breadth, sync)
        return evidence, warnings

    @staticmethod
    def _review_evidence_deltas(current: Mapping[str, Any], next_value: Mapping[str, Any]) -> dict[str, Any]:
        numeric_fields = (
            "advancingIndexCount", "decliningIndexCount", "aboveMa20Count",
            "medianAmountRatio5", "volumeBackedAdvanceCount", "volumeBackedDeclineCount",
            "advanceRatio", "medianReturn",
        )
        result: dict[str, Any] = {}
        for field in numeric_fields:
            before, after = current.get(field), next_value.get(field)
            result[field] = round(float(after) - float(before), 4) if before is not None and after is not None else None
        result["directionPattern"] = (
            f"{current.get('directionLabel') or current.get('directionPattern')} → "
            f"{next_value.get('directionLabel') or next_value.get('directionPattern')}"
            if current.get("directionPattern") != next_value.get("directionPattern") else None
        )
        return result

    def rebuild_materialized_aggregate(
        self,
        as_of: date,
        *,
        lease: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        return self._materialized_aggregate_rebuilder.rebuild(
            as_of,
            lease=lease,
            now=now,
        )

    def _compose_materialized_aggregate(
        self,
        as_of: date,
        revision: str,
    ) -> tuple[dict[str, Any], MaterializedAggregateRecord] | None:
        return self._materialized_aggregate_composer.compose(as_of, revision)

    def _get_local_aggregate(self, as_of: date) -> dict[str, Any]:
        if self.snapshot_store is None:
            raise RuntimeError("persistent snapshot store is disabled")
        for _attempt in range(_MATERIALIZED_REBUILD_ATTEMPTS):
            record, limits_record, active_leases, revision = self.snapshot_store.get_materialized_aggregate_state(
                as_of,
                now=self._market_now(),
            )
            if record is None:
                break
            payload = copy.deepcopy(record.payload)
            stored_revision = payload.pop(MATERIALIZED_COMPONENT_REVISION_KEY, None)
            stored_limits_state = payload.pop(_MATERIALIZED_LIMITS_STATE_KEY, object())
            payload.pop(_MATERIALIZED_SCHEMA_VERSION_KEY, None)
            current_limits_state = self._limits_snapshot_state(limits_record)
            if stored_revision != revision or stored_limits_state != current_limits_state:
                break
            self._apply_local_limits_policy(
                as_of,
                payload,
                record=limits_record,
                record_loaded=True,
            )
            self._apply_local_refreshing_state(as_of, payload, active_leases=active_leases)
            payload = self._refresh_materialized_synchronization(as_of, payload)
            return payload
        payload = self.rebuild_materialized_aggregate(as_of)
        if payload is None:
            raise RuntimeError("所选日期没有已采集的核心指数快照")
        self._apply_local_refreshing_state(as_of, payload)
        return payload

    def _apply_local_limits_policy(
        self,
        as_of: date,
        payload: dict[str, Any],
        *,
        record: SnapshotRecord | None = None,
        record_loaded: bool = False,
    ) -> None:
        chapter = payload.get("chapter01")
        if not isinstance(chapter, dict) or not isinstance(chapter.get("limits"), dict):
            return
        if self.snapshot_store is None:
            return
        if not record_loaded:
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

    def _apply_local_refreshing_state(
        self,
        as_of: date,
        payload: dict[str, Any],
        *,
        active_leases: frozenset[str] | None = None,
    ) -> None:
        if self.snapshot_store is None:
            return
        chapter = payload.get("chapter01")
        if not isinstance(chapter, dict):
            return
        if active_leases is None:
            active_leases = self.snapshot_store.active_lease_datasets(
                as_of,
                now=self._market_now(),
            )
        for group, keys in CHAPTER_GROUP_KEYS.items():
            refreshing = group in active_leases
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

    def _limit_payload_for_response(
        self,
        as_of: date,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._limit_ecosystem_composer.compose(as_of, payload)

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
        market_evidence = build_market_review_evidence(
            core["indices"],
            breadth,
            core["summary"].get("syncPattern"),
        )
        core["summary"]["marketEvidence"] = market_evidence
        core["summary"]["reviewSentence"] = build_review_sentence(market_evidence)
        payload["summary"] = self._core_payload(core)["summary"]
        chapter["marketEvidence"] = market_evidence
        chapter["reviewSentence"] = core["summary"]["reviewSentence"]
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

        core = {
            "asOf": effective_date.isoformat(),
            "generatedAt": datetime.now(MARKET_TIME_ZONE).isoformat(),
            "indices": analyses,
            "summary": build_core_summary(analyses, warnings, data_gaps),
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
                "marketEvidence": core["summary"].get("marketEvidence"),
                "reviewSentence": core["summary"].get("reviewSentence"),
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
        allow_current_snapshot = core["requestedAsOf"] == effective_market_date(self._market_now())
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
                refresh_generation = self.snapshot_store.get_completed_refresh_generation(group, as_of)
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
        refresh_generation = self.snapshot_store.get_completed_refresh_generation(group, as_of)
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
        return core["requestedAsOf"] == effective_market_date(self._market_now())

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
                value = fetch(
                    as_of,
                    allow_current_snapshot=core["requestedAsOf"] == effective_market_date(self._market_now()),
                )
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
        breadth = self._enrich_breadth(breadth, as_of, analyses)
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
        market_evidence = build_market_review_evidence(
            analyses,
            breadth,
            core["summary"].get("syncPattern"),
        )
        review_sentence = build_review_sentence(market_evidence)
        core["summary"]["marketEvidence"] = market_evidence
        core["summary"]["reviewSentence"] = review_sentence
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
            "marketEvidence": market_evidence,
            "reviewSentence": review_sentence,
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
                "declineRatio": None,
                "advanceDeclineSpread": None,
                "advanceRatioPercentile": None,
                "medianReturnPercentile": None,
                "spreadPercentile": None,
                "momentum": None,
                "momentumPercentile": None,
                "indexConsistent": None,
                "widthLabel": "数据不足",
                "widthLabelReason": "市场广度快照不可用，无法派生宽度标签与历史证据。",
                "history": None,
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
            return "partial" if quality["status"] in {"ok", "fallback", "fallback-derived", "partial"} else "insufficient"

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
    def _combination_overview(
        analyses: list[dict],
        synchronization_assessment_value: dict,
        breadth: dict,
    ) -> dict:
        return combination_overview(
            analyses,
            synchronization_assessment_value,
            breadth,
        )

    @staticmethod
    def _analyse(spec, bars: list[Bar], result: ProviderResult, quote: dict) -> dict:
        return analyze_index(spec, bars, result, quote)

    @staticmethod
    def _sync_pattern(analyses: list[dict]) -> dict:
        return sync_pattern(analyses)

    def _synchronization_assessment(
        self,
        core: dict[str, Any],
        breadth: dict,
    ) -> dict[str, object]:
        return synchronization_assessment(
            core,
            breadth,
            self._previous_breadth(core),
        )

    def _previous_breadth(self, core: dict[str, Any]) -> dict[str, Any] | None:
        return self._breadth_reader().previous_for_core(core)

    def _breadth_reader(self) -> BreadthHistoryReader:
        reader = getattr(self, "_breadth_history_reader", None)
        if reader is None:
            reader = BreadthHistoryReader(
                getattr(self, "snapshot_store", None),
                integrity_error=SnapshotIntegrityError,
            )
            self._breadth_history_reader = reader
        return reader

    @staticmethod
    def _previous_trading_date(core: dict[str, Any]) -> date | None:
        return previous_trading_date(core)

    @staticmethod
    def _synchronization(analyses: list[dict]) -> str:
        return synchronization_label(analyses)

    def _enrich_breadth(
        self,
        breadth: dict[str, Any],
        as_of: date,
        analyses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        recent_history = self._breadth_reader().list_payloads(
            as_of,
            exclude_today=True,
            limit=5,
        )
        percentile_history = self._breadth_reader().list_payloads(
            as_of,
            exclude_today=False,
            limit=250,
        )
        result = analyze_breadth(
            breadth,
            as_of,
            analyses,
            recent_history=recent_history,
            percentile_history=percentile_history,
        )
        points = [self._build_history_point(record) for record in result.history_points]
        result.payload["history"] = BreadthHistoryEvidence(
            points=points,
            validObservations=result.history_observations,
            requiredObservations=60,
            windowDays=250,
            coverage=result.history_coverage,
            percentile250={
                "advanceRatio": result.payload.get("advanceRatioPercentile"),
                "medianReturn": result.payload.get("medianReturnPercentile"),
                "advanceDeclineSpread": result.payload.get("spreadPercentile"),
                "momentum": result.payload.get("momentumPercentile"),
            },
            quality=MetricQuality(
                status=result.history_quality_status,
                reason=(
                    "insufficient-history"
                    if result.history_quality_status == "insufficient"
                    else None
                ),
                observations=result.history_observations,
                asOf=as_of.isoformat(),
                source=result.payload.get("quality", {}).get("source"),
                warnings=[],
            ),
        ).model_dump(mode="json", exclude_none=False)
        return result.payload

    @staticmethod
    def _percentile_value(samples: list[float | None]) -> float | None:
        return percentile_value(samples)

    def _breadth_history_records(
        self,
        as_of: date,
        *,
        exclude_today: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._breadth_reader().list_payloads(
            as_of,
            exclude_today=exclude_today,
            limit=limit,
        )

    @staticmethod
    def _build_history_point(record: dict[str, Any]) -> BreadthHistoryPoint:
        quality = record.get("quality") or {}
        history_quality = EvidenceQuality(
            dataset=quality.get("dataset", "market-breadth"),
            source=quality.get("source", "eastmoney-clist"),
            provider=quality.get("provider", quality.get("source", "eastmoney-clist")),
            status=quality.get("status", "insufficient"),
            observations=quality.get("observations", 0),
            asOf=quality.get("asOf"),
            warning=quality.get("warning"),
            warnings=list(quality.get("warnings") or []),
            cacheState=quality.get("cacheState"),
            snapshotFetchedAt=quality.get("snapshotFetchedAt"),
            refreshing=quality.get("refreshing"),
            refreshWarning=quality.get("refreshWarning"),
        )
        return BreadthHistoryPoint(
            asOf=record.get("asOf"),
            advanceCount=record.get("advanceCount"),
            declineCount=record.get("declineCount"),
            flatCount=record.get("flatCount"),
            validCount=record.get("validCount"),
            advanceRatio=record.get("advanceRatio"),
            declineRatio=record.get("declineRatio"),
            advanceDeclineSpread=record.get("advanceDeclineSpread"),
            medianReturn=record.get("medianReturn"),
            momentum=record.get("momentum"),
            widthLabel=record.get("widthLabel"),
            indexConsistent=record.get("indexConsistent"),
            quality=history_quality,
        )

    @staticmethod
    def _breadth_history_quality(breadth: dict[str, Any]) -> Any:
        quality = breadth.get("quality") or {}
        return EvidenceQuality(
            dataset=quality.get("dataset", "market-breadth"),
            source=quality.get("source", "eastmoney-clist"),
            provider=quality.get("provider", quality.get("source", "eastmoney-clist")),
            status=quality.get("status", "insufficient"),
            observations=quality.get("observations", 0),
            asOf=quality.get("asOf"),
            warning=quality.get("warning"),
            warnings=list(quality.get("warnings") or []),
            cacheState=quality.get("cacheState"),
            snapshotFetchedAt=quality.get("snapshotFetchedAt"),
            refreshing=quality.get("refreshing"),
            refreshWarning=quality.get("refreshWarning"),
        )
