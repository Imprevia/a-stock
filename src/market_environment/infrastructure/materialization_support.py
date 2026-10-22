"""Provider-free support functions used by materialized aggregate commands.

This module is deliberately independent from ``MarketEnvironmentService``.  It
contains only local snapshot reads, deterministic analysis and response-shape
assembly needed when a collection command rebuilds the persisted aggregate.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..application.queries.breadth_analysis import BreadthHistoryReader
from ..application.queries.limit_ecosystem import LimitEcosystemComposer
from ..domain.analysis.calculations import (
    build_market_review_evidence,
    build_review_sentence,
    build_summary_sentence,
)
from ..domain.analysis import analyze_breadth, combination_overview, synchronization_assessment
from ..domain.analysis.active_direction_workbench import compose_active_direction_workbench
from ..limit_ecosystem import build_limit_ecosystem
from ..limit_promotion import limit_v1_enabled, without_promotion_fields
from ..schemas import (
    BreadthHistoryEvidence,
    BreadthHistoryPoint,
    EvidenceQuality,
    LimitEvidence,
    MetricQuality,
)
from ..snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    SnapshotIntegrityError,
    cache_state,
    payload_checksum,
)


MARKET_TIME_ZONE = ZoneInfo("Asia/Shanghai")
CHAPTER_GROUP_KEYS: dict[str, tuple[str, ...]] = {
    "breadth": ("breadth",),
    "activeDirection": ("activeDirection",),
    "limits": ("limits",),
    "industry-ranking": ("industryRanking",),
    "sector-turnover": ("sectorTurnover",),
    "sector-breadth": ("sectorBreadth",),
}


class MaterializationSupport:
    """Compose the aggregate from exact-date local repository records only."""

    def __init__(
        self,
        repository: Any,
        *,
        now: Callable[[], datetime],
        snapshot_ttl_seconds: int,
        limits_enabled: Callable[[], bool] = limit_v1_enabled,
        continuity_repository: Any | None = None,
    ) -> None:
        self.snapshot_store = repository
        self.continuity_repository = continuity_repository or getattr(repository, "sector_continuity", None)
        self._now = now
        self.snapshot_ttl_seconds = snapshot_ttl_seconds
        self._limit_ecosystem_composer = LimitEcosystemComposer(
            repository,
            enabled=limits_enabled,
            strip_disabled_fields=without_promotion_fields,
            build_ecosystem=build_limit_ecosystem,
            validate=lambda value: LimitEvidence.model_validate(value).model_dump(
                exclude_unset=True
            ),
            checksum=payload_checksum,
        )
        self._breadth_history_reader = BreadthHistoryReader(
            repository,
            integrity_error=SnapshotIntegrityError,
        )

    def market_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=MARKET_TIME_ZONE)
        return value.astimezone(MARKET_TIME_ZONE)

    @staticmethod
    def local_core_context(as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        effective_date = date.fromisoformat(payload["asOf"])
        return {
            **copy.deepcopy(payload),
            "requestedAsOf": as_of,
            "effectiveDate": effective_date,
        }

    def snapshot_payload(self, record: Any, state: str, *, refreshing: bool) -> dict[str, Any]:
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

    def limit_payload_for_response(self, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        return self._limit_ecosystem_composer.compose(as_of, payload)

    @staticmethod
    def limits_snapshot_state(record: Any | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "checksum": record.checksum,
            "status": record.status,
            "refreshWarning": record.refresh_warning,
            "fetchedAt": record.fetched_at.isoformat(),
            "settled": record.settled,
        }

    @staticmethod
    def core_payload(core: dict[str, Any]) -> dict[str, Any]:
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

    @staticmethod
    def quality(
        dataset: str,
        provider: str,
        status: str,
        observations: int,
        as_of: date,
        warnings: list[str],
    ) -> dict[str, Any]:
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

    @classmethod
    def missing_chapter_provider_data(
        cls,
        as_of: date,
        warning: str,
        status: str = "failed",
    ) -> dict[str, Any]:
        quality = cls.quality("chapter-01-extended", "none", status, 0, as_of, [warning])
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
            "industry-ranking": {
                "rows": [],
                "state": "insufficient",
                "quality": {**quality, "dataset": "industry-ranking"},
            },
            "sector-turnover": {
                "rows": [],
                "state": "insufficient",
                "quality": {**quality, "dataset": "sector-turnover"},
            },
            "sector-breadth": {
                "rows": [],
                "state": "insufficient",
                "quality": {**quality, "dataset": "sector-breadth"},
            },
            "activeDirection": {
                "state": "insufficient",
                "summary": None,
                "topStocks": [],
                "quality": {**quality, "dataset": "active-direction"},
            },
            "activeDirectionWorkbench": {
                "asOf": as_of.isoformat(),
                "state": "missing",
                "quality": {**quality, "dataset": "active-direction-workbench"},
                "turnoverMap": {"rows": [], "availableCount": 0, "complete": False},
                "directionOverview": {"observations": [], "canonicalCandidates": [], "coverage": 0.0},
                "securityEvidence": {},
                "candidatePools": {},
                "fundamentals": {"state": "missing", "items": [], "gaps": []},
                "validation": None,
            },
        }

    @staticmethod
    def chapter_documents(
        breadth: dict[str, Any],
        limits: dict[str, Any],
        sector_evidence: dict[str, Any],
        active_direction: dict[str, Any],
    ) -> list[dict[str, Any]]:
        def evidence_status(quality: dict[str, Any]) -> str:
            return (
                "partial"
                if quality["status"] in {"ok", "fallback", "fallback-derived", "partial"}
                else "insufficient"
            )

        definitions = (
            ("01", "指数、趋势位置和成交额", "partial"),
            ("02", "上涨家数、下跌家数和涨跌幅中位数", evidence_status(breadth["quality"])),
            ("03", "涨停、跌停、炸板和连板晋级", evidence_status(limits["quality"])),
            ("04", "高位股、中位股和低位股的亏钱效应", "insufficient"),
            ("05", "主线持续性和成交额集中度", evidence_status(sector_evidence["quality"])),
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

    def _previous_breadth(self, core: dict[str, Any]) -> dict[str, Any] | None:
        return self._breadth_history_reader.previous_for_core(core)

    def _enrich_breadth(
        self,
        breadth: dict[str, Any],
        as_of: date,
        analyses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        recent_history = self._breadth_history_reader.list_payloads(
            as_of, exclude_today=True, limit=5
        )
        percentile_history = self._breadth_history_reader.list_payloads(
            as_of, exclude_today=False, limit=250
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

    def build_chapter01(
        self,
        core: dict[str, Any],
        provider_data: dict[str, Any],
    ) -> dict[str, Any]:
        as_of = core["effectiveDate"]
        analyses = core["indices"]
        synchronization = core["summary"]["synchronization"]
        dominant_trend = core["summary"]["dominantTrend"]
        breadth = self._enrich_breadth(provider_data["breadth"], as_of, analyses)
        limits = provider_data["limits"]
        industry_ranking = provider_data["industry-ranking"]
        sector_turnover = provider_data["sector-turnover"]
        sector_breadth = provider_data["sector-breadth"]
        sector_analysis = self._continuity_analysis(as_of)
        active_direction = provider_data["activeDirection"]
        try:
            active_direction_workbench = compose_active_direction_workbench(
                active_direction,
                as_of,
                limits=limits,
            )
        except Exception as exc:
            active_direction_workbench = {
                "asOf": as_of.isoformat(),
                "state": "failed-missing",
                "quality": {
                    "status": "failed-missing",
                    "observations": 0,
                    "warnings": [f"主动进攻方向工作台物化失败，保留 activeDirection：{type(exc).__name__}"],
                },
                "turnoverMap": {"rows": [], "availableCount": 0, "complete": False},
                "directionOverview": {"observations": [], "canonicalCandidates": [], "coverage": 0.0},
                "securityEvidence": {},
                "candidatePools": {},
                "fundamentals": {"state": "missing", "items": [], "gaps": []},
                "validation": None,
            }
        events = {
            "state": "unverified",
            "items": [],
            "quality": self.quality(
                "traceable-events",
                "not-connected",
                "missing",
                0,
                as_of,
                ["未提供带来源、发布时间、有效期和失效条件的结构化事件输入"],
            ),
        }
        documents = self.chapter_documents(
            breadth,
            limits,
            sector_breadth if sector_breadth.get("quality") else industry_ranking,
            active_direction,
        )
        qualities = [
            breadth["quality"],
            limits["quality"],
            industry_ranking["quality"],
            sector_turnover["quality"],
            sector_breadth["quality"],
            active_direction["quality"],
            events["quality"],
        ]
        status_weight = {"ok": 1.0, "fallback": 0.75, "partial": 0.5, "missing": 0.0, "failed": 0.0}
        coverage = round((1.0 + sum(status_weight.get(item["status"], 0.0) for item in qualities)) / 8.0, 4)
        status = "partial" if coverage >= 0.5 else "insufficient"
        synchronization_assessment_value = synchronization_assessment(
            core,
            breadth,
            self._previous_breadth(core),
        )
        core["summary"]["synchronizationAssessment"] = synchronization_assessment_value
        combination = combination_overview(analyses, synchronization_assessment_value, breadth)
        market_evidence = build_market_review_evidence(
            analyses, breadth, core["summary"].get("syncPattern")
        )
        review_sentence = build_review_sentence(market_evidence)
        core["summary"]["marketEvidence"] = market_evidence
        core["summary"]["reviewSentence"] = review_sentence
        summary_sentence = build_summary_sentence(
            core["summary"].get("syncPattern", {}).get("label")
            if core["summary"].get("syncPattern")
            else synchronization,
            next((item.get("ma20PositionLabel") for item in analyses if item.get("ma20PositionLabel")), None),
            next((item.get("rangePosition60Label") for item in analyses if item.get("rangePosition60Label")), None),
            next((item.get("amountRatio5") for item in analyses if item.get("amountRatio5") is not None), None),
            next((item.get("volumePriceState") for item in analyses if item.get("volumePriceState")), None),
            combination.get("tradingMode"),
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
        if industry_ranking.get("rows"):
            names = "、".join(
                item.get("name") or "未知"
                for item in industry_ranking["rows"][:3]
            )
            evidence.append(f"行业当日排名：{names}")
        if active_direction.get("summary"):
            evidence.append(f"容量方向：{active_direction['summary']}")
        confidence = "low" if coverage >= 0.5 else "insufficient"
        return {
            "status": status,
            "coverage": coverage,
            "documents": documents,
            "breadth": breadth,
            "limits": limits,
            "industryRanking": industry_ranking,
            "sectorTurnover": sector_turnover,
            "sectorBreadth": sector_breadth,
            "sectorAnalysis": sector_analysis,
            "activeDirection": active_direction,
            "activeDirectionWorkbench": active_direction_workbench,
            "events": events,
            "combinationOverview": combination,
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
                "risks": [
                    "高位股、中位股和低位股亏钱效应尚未接入",
                    "事件、政策和突发信息未提供可追溯结构化输入",
                    "滚动分位和历史阈值尚未校准，不输出验证分数",
                ],
                "nextConfirmation": "补齐分层亏钱效应、主线连续性和可追溯事件后再确认环境分类",
                "invalidation": "任一证据日期不一致、provider 失败或风险证据显著恶化时，不使用候选判断",
            },
        }

    def _continuity_analysis(self, as_of: date) -> dict[str, Any] | None:
        reader = self.continuity_repository
        if reader is None:
            return None
        try:
            if hasattr(reader, "get_result"):
                result = reader.get_result(as_of)
            elif hasattr(reader, "get_continuity_result"):
                result = reader.get_continuity_result(as_of)
            else:
                return None
        except Exception:
            # A failed derived read must not hide a valid provider observation.
            return None
        if result is None:
            return None
        if isinstance(result, dict):
            if result.get("asOf") not in (None, as_of.isoformat()):
                return None
            return copy.deepcopy(result)

        def convert(value: Any) -> Any:
            if dataclasses.is_dataclass(value):
                return {key: convert(item) for key, item in dataclasses.asdict(value).items()}
            if isinstance(value, dict):
                return {str(key): convert(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [convert(item) for item in value]
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            return value

        payload = convert(result)
        def camelize(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    "".join((part if index == 0 else part[:1].upper() + part[1:]) for index, part in enumerate(str(key).split("_"))): camelize(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [camelize(item) for item in value]
            return value

        result_payload = camelize(payload)
        if result_payload.get("asOf") != as_of.isoformat():
            return None
        if "metricTraces" not in result_payload and isinstance(result_payload.get("metrics"), list):
            result_payload["metricTraces"] = result_payload.pop("metrics")
        if "quality" not in result_payload:
            result_payload["quality"] = {
                "status": result_payload.get("status", "insufficient"),
                "confidence": result_payload.get("confidence", "insufficient"),
                "coverage": result_payload.get("coverage"),
                "asOf": as_of.isoformat(),
                "requiredObservations": 60,
                "availableObservations": min(
                    (
                        int(item.get("observations", 0) or 0)
                        for item in result_payload.get("metricTraces", [])
                        if isinstance(item, dict)
                    ),
                    default=0,
                ),
                "warnings": list(result_payload.get("warnings") or []),
                "missingInputs": list(result_payload.get("missingInputs") or []),
            }
        if "history" not in result_payload:
            result_payload["history"] = {
                "requiredObservations": 60,
                "windowDays": 250,
                "validObservations": int(result_payload["quality"].get("availableObservations", 0) or 0),
                "actualDateRange": [],
                "gaps": [],
                "quality": None,
            }
        result_payload.setdefault("risk", {})
        result_payload.setdefault("warnings", [])
        return result_payload


__all__ = ["CHAPTER_GROUP_KEYS", "MARKET_TIME_ZONE", "MaterializationSupport"]
