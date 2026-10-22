"""Deterministic, provider-free facts for the active-direction research page.

The composer intentionally exposes observations and evidence gaps.  It does
not evaluate QTS-04 thresholds or assign trading roles.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RuleMaturity:
    ruleId: str
    implementationState: str = "documented-only"
    calibrationState: str = "needs-backtest"
    score: float | None = None


@dataclass(frozen=True, slots=True)
class EvidenceTrace:
    ruleId: str
    state: str
    value: Any = None
    source: str | None = None
    coverage: float | None = None
    missingInputs: tuple[str, ...] = ()
    confirmation: str | None = None
    invalidation: str | None = None


@dataclass(frozen=True, slots=True)
class NextSessionValidation:
    priority: str
    subject: str | None
    check: str
    confirmation: str
    invalidation: str


def _maturity(rule_id: str) -> dict[str, Any]:
    return asdict(RuleMaturity(rule_id))


def _quality(status: str, warnings: list[str], observations: int) -> dict[str, Any]:
    return {
        "status": status,
        "observations": observations,
        "warnings": list(dict.fromkeys(warnings)),
        "missingInputs": [],
    }


def compose_active_direction_workbench(
    active_direction: Mapping[str, Any] | None,
    as_of: date,
    *,
    limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded page contract from one already-materialized payload."""

    source = active_direction or {}
    quality = dict(source.get("quality") or {})
    raw_rows = source.get("researchRows")
    if not isinstance(raw_rows, list):
        raw_rows = source.get("topStocks") if isinstance(source.get("topStocks"), list) else []
    rows = [dict(row) for row in raw_rows[:30] if isinstance(row, Mapping)]
    complete = len(rows) >= 30 and bool(source.get("researchRows"))
    status = str(quality.get("status") or "missing")
    warnings = [str(item) for item in quality.get("warnings") or []]
    if not complete:
        warnings.append("旧快照仅提供 Top-10 或缺少验证过的 Top-30 researchRows")

    observed = Counter(
        str(row.get("rawDirectionLabel") or row.get("industry") or "未映射观察")
        for row in rows
    )
    observations = [
        {"label": label, "count": count, "canonical": False}
        for label, count in observed.most_common(10)
    ]
    canonical = [
        dict(row)
        for row in rows
        if row.get("canonicalDirectionId") or row.get("canonicalSectorId")
    ][:3]

    turnover_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        turnover_rows.append(
            {
                **row,
                "rank": int(row.get("rank") or index),
                "priorRank": row.get("priorRank"),
                "newEntry": row.get("newEntry"),
                "rankContinuity": row.get("rankContinuity"),
                "amount5dRatio": row.get("amount5dRatio"),
                "amount20dRatio": row.get("amount20dRatio"),
                "historyQuality": row.get("historyQuality") or "missing",
            }
        )

    trace_ids = (
        "QTS-04-03-market-position",
        "QTS-04-03-sector-leadership",
        "QTS-04-03-persistence",
        "QTS-04-03-capacity-tradability",
        "QTS-04-03-divergence-repair",
        "QTS-04-03-space-breakout",
    )
    security_evidence = {
        str(row.get("code")): {
            "securityId": row.get("securityId") or row.get("code"),
            "name": row.get("name"),
            "traces": [asdict(EvidenceTrace(rule_id, "missing", missingInputs=("approved exact-date fact",))) for rule_id in trace_ids],
            "ruleMaturity": _maturity("QTS-04-03"),
            "score": None,
            "role": None,
            "vetoes": [],
            "quality": _quality("insufficient", ["核心辨识规则仍为 documented-only"], 0),
        }
        for row in rows
        if row.get("code")
    }

    candidate_pools = {
        "abnormalCapital": {"state": "insufficient", "items": [], "ruleMaturity": _maturity("QTS-04-04")},
        "longUpperShadow": {"state": "insufficient", "items": [], "ruleMaturity": _maturity("QTS-04-05")},
        "firstToSecond": {"state": "insufficient", "strictNextSession": [], "fiveSession": [], "ruleMaturity": _maturity("QTS-04-06")},
    }
    fundamental_items = []
    for row in rows:
        metrics = {
            "pe": row.get("pe"),
            "pb": row.get("pb"),
            "marketCap": row.get("marketCap"),
            "circulatingMarketCap": row.get("circulatingMarketCap"),
            "turnoverRatePct": row.get("turnoverRatePct"),
            "changePct60d": row.get("changePct60d"),
            "changePctYtd": row.get("changePctYtd"),
        }
        available = [key for key, value in metrics.items() if value is not None]
        if available:
            fundamental_items.append({
                "securityId": row.get("securityId") or row.get("code"),
                "code": row.get("code"),
                "name": row.get("name"),
                "period": row.get("fundamentalAsOf") or as_of.isoformat(),
                "source": row.get("fundamentalSource") or quality.get("source"),
                "metrics": metrics,
                "availableFields": available,
                "missingFields": ["profitability", "growth", "cashFlow", "leverage"],
                "score": None,
                "vetoes": [],
            })
    fundamental_status = "partial" if fundamental_items else "missing"
    fundamentals = {
        "state": fundamental_status,
        "quality": _quality(
            fundamental_status,
            (["仅有行情快照估值字段，未接入带期间财务报表"] if fundamental_items else ["没有已批准的带期间财务事实和可比行业样本"]),
            len(fundamental_items),
        ),
        "gaps": ["profitability", "growth", "cashFlow", "leverage", "industryComparableValuation"],
        "items": fundamental_items[:30],
        "ruleMaturity": _maturity("QTS-04-07"),
        "safe": None,
    }

    limit_details = ((limits or {}).get("securityDetails") or {}) if isinstance(limits, Mapping) else {}
    promoted_rows = (((limit_details.get("promoted") or {}).get("rows")) if isinstance(limit_details, Mapping) else []) or []
    promoted_rows = [dict(row) for row in promoted_rows if isinstance(row, Mapping)]
    intraday_rows = []
    for row in promoted_rows[:30]:
        intraday_rows.append({
            "securityId": row.get("securityId"),
            "code": row.get("code"),
            "name": row.get("name"),
            "firstLimitTime": row.get("firstLimitTime"),
            "lastLimitTime": row.get("lastLimitTime"),
            "openTimes": row.get("openTimes"),
            "sealMoney": row.get("sealMoney"),
            "maxSealMoney": row.get("maxSealMoney"),
            "turnoverRatioPct": row.get("turnoverRatioPct"),
            "source": row.get("source"),
            "quality": row.get("rowQuality") or "ok",
        })
    validation = asdict(
        NextSessionValidation(
            priority="evidence-recovery",
            subject=(str(rows[0].get("code")) if rows else None),
            check="补齐精确日期的 Top-30 身份、历史和候选确认事实",
            confirmation="下一交易日获得同一规范身份的可追溯确认事实",
            invalidation="日期不一致、身份无法映射或关键事实仍缺失",
        )
    )
    return {
        "asOf": as_of.isoformat(),
        "state": status if complete else ("partial" if rows else "missing"),
        "quality": _quality("ok" if complete else ("partial" if rows else "missing"), warnings, len(rows)),
        "lineage": {
            "source": quality.get("source"),
            "sourceRevision": quality.get("sourceRevision") or quality.get("providerRevision"),
            "rankingMethod": quality.get("rankingMethod"),
            "industryMappingRevision": quality.get("industryMappingRevision"),
            "industryMappingCoverage": quality.get("industryMappingCoverage"),
        },
        "directionOverview": {
            "observations": observations,
            "canonicalCandidates": canonical,
            "coverage": 1.0 if canonical else 0.0,
            "ruleMaturity": _maturity("QTS-04-01"),
            "triggeredRules": [],
            "vetoes": ["未建立日期有效的规范板块映射"] if not canonical else [],
            "confirmation": "补齐规范板块 identity、宽度和持续性证据" if not canonical else None,
            "invalidation": "映射 revision 不一致或宽度证据不足",
        },
        "turnoverMap": {"rows": turnover_rows, "availableCount": len(turnover_rows), "complete": complete},
        "securityEvidence": security_evidence,
        "candidatePools": {
            **candidate_pools,
            "firstToSecond": {
                "state": "partial" if promoted_rows else "missing",
                "strictNextSession": [row for row in promoted_rows if row.get("streakDays") in (2, "2")][:30],
                "fiveSession": promoted_rows[:30],
                "anchors": promoted_rows[:30],
                "auction": {
                    "state": "pending",
                    "missingInputs": ["auctionChangePct", "auctionAmount", "unmatchedVolume", "sameSectorAuctionBreadth"],
                    "reason": "当前本地事实未保存 09:15-09:25 集合竞价序列",
                },
                "intraday": {
                    "state": "partial" if intraday_rows else "missing",
                    "rows": intraday_rows,
                    "missingInputs": ["minuteBars", "firstPushTime", "sealDuration"],
                    "reason": "已接入涨停事实中的封板/开板字段；分钟序列仍未入库" if intraday_rows else "没有精确日期涨停明细",
                },
                "ruleMaturity": _maturity("QTS-04-06"),
            },
        },
        "fundamentals": fundamentals,
        "validation": validation,
    }


__all__ = [
    "EvidenceTrace",
    "NextSessionValidation",
    "RuleMaturity",
    "compose_active_direction_workbench",
]
