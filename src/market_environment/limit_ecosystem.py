"""Backend-only aggregation for the Chapter 01 limits ecosystem.

All values are derived from exact-date local snapshots and normalized security
facts. Missing history or unverifiable rows remain explicit ``insufficient``
evidence; this module never fills values from another date.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from math import isfinite
from typing import Any

from .limit_promotion import build_limit_promotion
from .snapshot_store import LIMIT_DETAIL_CHECKSUM_KEY
from .trading_sessions import TradingDayResolver

_LIMIT_RULES = (
    ("QTS-01-03-01", "limitUpCount", 0.20),
    ("QTS-01-03-02", "limitDownCount", 0.25),
    ("QTS-01-03-03", "failedLimitUpRatio", 0.20),
    ("QTS-01-03-04", "promotionRatio", 0.25),
    ("QTS-01-03-05", "maxStreak", 0.10),
)
_HISTORY_WINDOW_DAYS = 250
_MIN_VALID_OBSERVATIONS = 60


def _quality(status: str, reason: str, observations: int, as_of: date | None, source: str | None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "observations": observations,
        "asOf": as_of.isoformat() if as_of else None,
        "source": source,
        "warnings": list(warnings or []),
    }


def _empty_quality(as_of: date, reason: str = "missing-limit-security-dataset") -> dict[str, Any]:
    return _quality("insufficient", reason, 0, as_of, None)


def _percentile(values: list[float], value: float | None) -> float | None:
    if not values or value is None:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return 0.5
    rank = sum(item <= value for item in ordered) - 1
    return round(max(0.0, min(1.0, rank / (len(ordered) - 1))), 4)


def _finite_number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        return False
    number = float(value)
    return (minimum is None or number >= minimum) and (maximum is None or number <= maximum)


def _metric_value(payload: dict[str, Any], key: str) -> float | int | None:
    value = payload.get(key)
    if key in {"limitUpCount", "limitDownCount", "maxStreak"}:
        return int(value) if _finite_number(value, minimum=0) and float(value).is_integer() else None
    return float(value) if _finite_number(value, minimum=0, maximum=1) else None


def _band_score(percentile: float | None, *, inverse: bool = False) -> int | None:
    if percentile is None or not _finite_number(percentile, minimum=0, maximum=1):
        return None
    bands = (0, 25, 50, 75, 100)
    if percentile <= 0.2:
        index = 0
    elif percentile <= 0.4:
        index = 1
    elif percentile <= 0.6:
        index = 2
    elif percentile <= 0.8:
        index = 3
    else:
        index = 4
    return bands[4 - index] if inverse else bands[index]


def _history_chain(store: Any, as_of: date) -> list[tuple[date, Any]]:
    """Walk the persisted previous-session chain without filling missing dates."""

    get_session = getattr(store, "get_trading_session", None)
    current = as_of
    chain: list[tuple[date, Any]] = []
    for _ in range(_HISTORY_WINDOW_DAYS):
        snapshot = store.get("limits", current)
        if snapshot is None:
            break
        chain.append((current, snapshot))
        if not callable(get_session):
            break
        session = get_session(current)
        if session is None or not bool(getattr(session, "is_session", False)):
            break
        actual = getattr(session, "actual_as_of", None)
        if actual != current:
            break
        previous = getattr(session, "previous_as_of", None)
        if previous is None or previous >= current:
            break
        current = previous
    return chain


def _history(store: Any, as_of: date, *, current_payload: dict[str, Any]) -> dict[str, Any]:
    dates = _history_chain(store, as_of)
    points: list[dict[str, Any]] = []
    valid = 0
    for point_date, snapshot in dates:
        payload = dict(snapshot.payload)
        quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
        try:
            payload.update(
                build_limit_promotion(
                    store,
                    point_date,
                    dataset_quality=quality,
                    emit_log=False,
                )
            )
        except Exception:
            payload["promotionRatio"] = None
        manifest = store.get_limit_security_dataset(point_date)
        checksum_bound = bool(
            manifest
            and manifest.get("complete")
            and manifest.get("actual_as_of") == point_date
            and quality.get(LIMIT_DETAIL_CHECKSUM_KEY) == manifest.get("dataset_checksum")
        )
        status = str(quality.get("status") or snapshot.status)
        required_values = tuple(_metric_value(payload, key) for _, key, _ in _LIMIT_RULES)
        usable = bool(
            status == "ok"
            and snapshot.status == "ok"
            and snapshot.refresh_warning is None
            and checksum_bound
            and all(value is not None for value in required_values)
            and isinstance(payload.get("promotionQuality"), dict)
            and payload["promotionQuality"].get("status") == "ok"
        )
        if usable:
            valid += 1
        point_status = "ok" if usable else (
            "degraded" if status in {"fallback", "degraded"} or snapshot.refresh_warning else "insufficient"
        )
        points.append(
            {
                "asOf": point_date.isoformat(),
                "limitUpCount": _metric_value(payload, "limitUpCount"),
                "limitDownCount": _metric_value(payload, "limitDownCount"),
                "failedLimitUpRatio": _metric_value(payload, "failedLimitUpRatio"),
                "promotionRatio": _metric_value(payload, "promotionRatio"),
                "maxStreak": _metric_value(payload, "maxStreak"),
                "quality": _quality(
                    point_status,
                    "complete-exact-date-observation" if usable else "snapshot-not-usable",
                    int(snapshot.observations),
                    point_date,
                    snapshot.source,
                    list(quality.get("warnings") or []),
                ),
            }
        )
    metric_values: dict[str, list[float]] = {key: [] for _, key, _ in _LIMIT_RULES}
    for point in points:
        if point["quality"]["status"] != "ok":
            continue
        for _, key, _ in _LIMIT_RULES:
            value = point.get(key)
            if isinstance(value, (int, float)) and value == value:
                metric_values[key].append(float(value))
    current_values = {
        "limitUpCount": _metric_value(current_payload, "limitUpCount"),
        "limitDownCount": _metric_value(current_payload, "limitDownCount"),
        "failedLimitUpRatio": _metric_value(current_payload, "failedLimitUpRatio"),
        "promotionRatio": _metric_value(current_payload, "promotionRatio"),
        "maxStreak": _metric_value(current_payload, "maxStreak"),
    }
    enough = valid >= _MIN_VALID_OBSERVATIONS and len(points) >= _MIN_VALID_OBSERVATIONS
    history_warnings: list[str] = []
    if valid < _MIN_VALID_OBSERVATIONS:
        history_warnings.append(f"valid observations: {valid}/{_MIN_VALID_OBSERVATIONS}")
    if len(points) < 5:
        history_warnings.append(f"exact-date history points: {len(points)}/5")
    if len(points) < _HISTORY_WINDOW_DAYS:
        history_warnings.append(f"exact-date history chain: {len(points)}/{_HISTORY_WINDOW_DAYS}")
    percentile = {
        key: (_percentile(metric_values[key], current_values[key]) if enough else None)
        for key in current_values
    }
    history_quality = _quality(
        "ok" if enough else "insufficient",
        "at-least-60-valid-observations" if enough else "insufficient-history-or-gaps",
        valid,
        as_of,
        current_payload.get("quality", {}).get("source") if isinstance(current_payload.get("quality"), dict) else None,
        history_warnings,
    )
    return {
        "points": list(reversed(points[:5])),
        "validObservations": valid,
        "requiredObservations": _MIN_VALID_OBSERVATIONS,
        "windowDays": _HISTORY_WINDOW_DAYS,
        "coverage": round(valid / _HISTORY_WINDOW_DAYS, 4),
        "percentile250": percentile,
        "quality": history_quality,
    }


def _fact_dimensions(store: Any, as_of: date, source: str | None, complete: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = store.get_limit_security_facts(as_of)
    limit_up_facts = [fact for fact in facts if fact.pool_type == "limit_up"]
    eligible = [fact for fact in limit_up_facts if fact.eligible and fact.closed_limit_up is True]
    observations = len(limit_up_facts)

    ladder_complete = complete and all(fact.streak_days is not None for fact in eligible)
    ladder_status = "ok" if ladder_complete else "insufficient"
    ladder_reason = "complete-streak-facts" if ladder_complete else "missing-streak-facts"

    tiers = (("first", "首板", 1), ("second", "二板", 2), ("third", "三板", 3), ("four_plus", "四板以上", 4))
    ladder: list[dict[str, Any]] = []
    for tier, label, minimum in tiers:
        known_count = sum(
            1
            for fact in eligible
            if fact.streak_days is not None and (fact.streak_days == minimum if minimum < 4 else fact.streak_days >= minimum)
        )
        ladder.append({
            "tier": tier,
            "label": label,
            "count": known_count if ladder_complete else None,
            "observations": len(eligible),
            "quality": _quality(ladder_status, ladder_reason, len(eligible), as_of, source),
        })

    stratifications: list[dict[str, Any]] = []
    dimension_specs = (
        ("exchange", "exchange", {"SSE": "上交所", "SZSE": "深交所", "BSE": "北交所"}),
        ("regime", "limit_regime", {"main": "主板 10%", "st": "ST 5%", "chi_next": "创业板 20%", "star": "科创板 20%", "pct:30": "30%"}),
        ("board", "board", {"main": "主板", "chi_next": "创业板", "star": "科创板"}),
    )
    for dimension, field_name, labels in dimension_specs:
        field_values = [getattr(fact, field_name) for fact in limit_up_facts]
        dimension_complete = complete and all(value not in (None, "") for value in field_values)
        dimension_status = "ok" if dimension_complete else "insufficient"
        dimension_reason = "complete-stratification-facts" if dimension_complete else f"missing-{field_name}-facts"
        counts = Counter(value for value in field_values if value)
        for key, label in labels.items():
            stratifications.append({
                "dimension": dimension,
                "key": key,
                "label": label,
                "count": int(counts.get(key, 0)) if dimension_complete else None,
                "observations": observations,
                "quality": _quality(dimension_status, dimension_reason, observations, as_of, source),
            })
    all_limit_up = limit_up_facts
    st_complete = complete and all(fact.is_st is not None for fact in all_limit_up)
    ipo_complete = complete and all(fact.listing_days is not None and fact.listing_days >= 0 for fact in all_limit_up)
    for key, label, predicate in (
        ("st", "ST", lambda fact: fact.is_st is True),
        ("ipo", "新股/上市不足窗口", lambda fact: fact.listing_days is not None and fact.listing_days < 5),
    ):
        dimension_complete = st_complete if key == "st" else ipo_complete
        count = sum(1 for fact in all_limit_up if predicate(fact)) if dimension_complete else None
        stratifications.append({
            "dimension": "risk_tier",
            "key": key,
            "label": label,
            "count": count,
            "observations": observations,
            "quality": _quality("ok" if dimension_complete else "insufficient", "complete-risk-classification" if dimension_complete else "missing-risk-classification", observations, as_of, source),
        })
    tier_status = "ok" if ladder_complete else "insufficient"
    tier_reason = "complete-streak-facts" if ladder_complete else "missing-streak-facts"
    for key, label, predicate in (
        ("high", "高位（四板以上）", lambda fact: fact.streak_days is not None and fact.streak_days >= 4),
        ("middle", "中位（二至三板）", lambda fact: fact.streak_days in {2, 3}),
        ("low", "低位（首板）", lambda fact: fact.streak_days == 1),
    ):
        count = sum(1 for fact in eligible if predicate(fact)) if ladder_complete else None
        stratifications.append({
            "dimension": "risk_tier",
            "key": key,
            "label": label,
            "count": count,
            "observations": observations,
            "quality": _quality(tier_status, tier_reason, len(eligible), as_of, source),
        })
    # Sector membership is not present in the current provider contract. Keep
    # the row visible as an auditable gap instead of inferring it by name.
    stratifications.append({
        "dimension": "sector",
        "key": "unknown",
        "label": "板块（来源未提供）",
        "count": None,
        "observations": observations,
        "quality": _quality("insufficient", "provider-missing-sector", observations, as_of, source),
    })
    return ladder, stratifications


def build_limit_ecosystem(store: Any, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge strict limits evidence into the legacy five-field payload."""
    value = dict(payload)
    manifest = store.get_limit_security_dataset(as_of)
    source = value.get("quality", {}).get("source") if isinstance(value.get("quality"), dict) else None
    complete = bool(manifest and manifest.get("complete") and manifest.get("actual_as_of") == as_of)
    if manifest is None:
        ladder: list[dict[str, Any]] = []
        stratifications: list[dict[str, Any]] = []
    else:
        ladder, stratifications = _fact_dimensions(store, as_of, source, complete)
    promotion = build_limit_promotion(store, as_of, dataset_quality=value.get("quality"))
    value.update(promotion)
    value["ladder"] = ladder
    value["stratifications"] = stratifications
    history = _history(store, as_of, current_payload=value)
    value["history"] = history
    valid = int(history["validObservations"])
    value["ruleEvidence"] = []
    history_ready = history["quality"]["status"] == "ok"
    for rule_id, key, weight in _LIMIT_RULES:
        metric_value = _metric_value(value, key)
        percentile_value = history["percentile250"].get(key)
        missing: list[str] = []
        if metric_value is None:
            missing.append(key)
        if not history_ready:
            missing.append("history.validObservations")
        status = "needs-backtest" if not missing and percentile_value is not None else "insufficient"
        inverse = rule_id in {"QTS-01-03-02", "QTS-01-03-03"}
        score = _band_score(percentile_value, inverse=inverse) if status == "needs-backtest" else None
        evidence = []
        if percentile_value is not None:
            evidence.append(f"250日经验分位 {percentile_value:.2%}")
        value["ruleEvidence"].append({
            "ruleId": rule_id,
            "status": status,
            "value": metric_value,
            "score": score,
            "weight": weight,
            "thresholdProvenance": "empirical-initial",
            "missingInputs": missing,
            "vetoes": [],
            "evidence": evidence,
            "calibrationStatus": "needs-backtest",
        })
    risk: list[dict[str, Any]] = []

    def add_risk(
        code: str,
        label: str,
        status: str,
        value_: Any,
        reason: str,
        evidence: list[str],
        *,
        observations: int = 0,
        source_: str | None = source,
        warnings: list[str] | None = None,
    ) -> None:
        risk.append(
            {
                "code": code,
                "label": label,
                "status": status,
                "value": value_,
                "asOf": as_of.isoformat(),
                "quality": _quality(status, reason, observations, as_of, source_, warnings),
                "evidence": evidence,
            }
        )

    previous_as_of = None
    resolution = TradingDayResolver(store).resolve(as_of)
    if resolution.sufficient:
        previous_as_of = resolution.previous_as_of
    previous_snapshot = store.get("limits", previous_as_of) if previous_as_of else None
    previous_manifest = store.get_limit_security_dataset(previous_as_of) if previous_as_of else None
    current_manifest = store.get_limit_security_dataset(as_of)
    current_detail_complete = bool(
        current_manifest and current_manifest.get("complete") and current_manifest.get("actual_as_of") == as_of
    )
    previous_detail_complete = bool(
        previous_manifest
        and previous_manifest.get("complete")
        and previous_manifest.get("actual_as_of") == previous_as_of
    )
    current_down = _metric_value(value, "limitDownCount")
    previous_down = _metric_value(previous_snapshot.payload, "limitDownCount") if previous_snapshot else None
    if current_detail_complete and previous_detail_complete and previous_snapshot is not None and current_down is not None and previous_down is not None:
        add_risk(
            "consecutive-limit-down",
            "连续跌停风险",
            "ok",
            bool(current_down > 0 and previous_down > 0),
            "exact-adjacent-limit-down-observations",
            [f"前一交易日跌停 {previous_down} 家", f"当前交易日跌停 {current_down} 家"],
            observations=2,
        )
    else:
        add_risk("consecutive-limit-down", "连续跌停风险", "insufficient", None, "missing-adjacent-limit-down-snapshots", ["缺少精确相邻交易日跌停快照"])

    current_facts = store.get_limit_security_facts(as_of)
    previous_facts = store.get_limit_security_facts(previous_as_of) if previous_as_of else ()
    failed_ids = {fact.security_id for fact in previous_facts if fact.pool_type == "failed_limit_up" and fact.security_id}
    repaired_ids = {fact.security_id for fact in current_facts if fact.pool_type == "limit_up" and fact.closed_limit_up is True and fact.security_id}
    if failed_ids and previous_manifest and current_manifest and previous_manifest.get("complete") and current_manifest.get("complete"):
        repair_ratio = round(len(failed_ids & repaired_ids) / len(failed_ids), 4)
        add_risk("failure-repair", "炸板修复", "ok", repair_ratio, "complete-failed-pool-and-current-close-set", [f"前一交易日炸板样本 {len(failed_ids)} 个", f"当前交易日修复 {len(failed_ids & repaired_ids)} 个"], observations=len(failed_ids))
    else:
        add_risk("failure-repair", "炸板修复", "insufficient", None, "missing-complete-failed-pool", ["缺少完整前一交易日炸板样本，无法计算修复率"])
    previous_streak = _metric_value(previous_snapshot.payload, "maxStreak") if previous_snapshot else None
    current_streak = _metric_value(value, "maxStreak")
    if current_detail_complete and previous_detail_complete and previous_snapshot is not None and previous_streak is not None and current_streak is not None:
        add_risk("ladder-change", "连板梯队升降", "ok", int(current_streak) - int(previous_streak), "exact-adjacent-max-streak-observations", [f"最高板 {previous_streak} -> {current_streak}"], observations=2)
    else:
        add_risk("ladder-change", "连板梯队升降", "insufficient", None, "missing-adjacent-max-streak", ["缺少精确相邻交易日最高板"])
    eligible_count = sum(1 for fact in current_facts if fact.pool_type == "limit_up" and fact.eligible and fact.closed_limit_up is True)
    board_counts = Counter(fact.board for fact in current_facts if fact.pool_type == "limit_up" and fact.eligible and fact.closed_limit_up is True and fact.board)
    if current_detail_complete and eligible_count and board_counts:
        concentration = round(max(board_counts.values()) / eligible_count, 4)
        add_risk("board-concentration", "市场板块集中度（非行业）", "ok", concentration, "verified-board-concentration", [f"最大市场板块分层 {max(board_counts.values())}/{eligible_count}"], observations=eligible_count)
    else:
        add_risk("board-concentration", "市场板块集中度（非行业）", "insufficient", None, "missing-verified-board-samples", ["缺少可验证市场板块分层样本"])
    add_risk("sector-concentration", "行业板块集中度", "insufficient", None, "provider-missing-sector-membership", ["provider 未提供逐股行业板块归属，禁止按名称推断"])
    promotion_status = promotion.get("promotionQuality", {}).get("status")
    if promotion_status in {"ok", "degraded"} and promotion.get("promotionRatio") is not None:
        add_risk(
            "next-day-feedback",
            "昨日强势股次日涨停反馈",
            promotion_status,
            promotion.get("promotionRatio"),
            "promotion-close-limit-up-feedback",
            [f"昨日合资格样本 {promotion.get('yesterdayLimitUpEligible')} 个", f"今日继续收盘涨停 {promotion.get('todayPromoted')} 个"],
            observations=int(promotion.get("yesterdayLimitUpEligible") or 0),
            warnings=["仅覆盖次日收盘涨停，未覆盖低开、冲高回落与溢价分布"] if promotion_status == "ok" else list(promotion.get("promotionQuality", {}).get("warnings") or []),
        )
    else:
        add_risk("next-day-feedback", "昨日强势股次日反馈", "insufficient", None, "missing-next-day-return-evidence", ["需要后续交易日收盘收益、低开和溢价事实"])
    value["riskEvidence"] = risk
    value["confirmation"] = "历史有效观测达到 60 日且晋级、梯队和风险输入完整后再确认生态状态"
    value["invalidation"] = "日期、身份、制度或收盘状态无法证明时，结论保持数据不足"
    value["ecosystemCoverage"] = round(valid / 60, 4) if valid < 60 else 1.0
    value["confidence"] = "high" if history["quality"]["status"] == "ok" and promotion.get("promotionQuality", {}).get("status") == "ok" else ("medium" if valid >= 5 else "insufficient")
    return value


__all__ = ["build_limit_ecosystem"]
