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


_POOL_GROUPS = {
    "limit_up": "limitUp",
    "limit_down": "limitDown",
    "failed_limit_up": "failedLimitUp",
}


def _normalized_quality(
    value: Any,
    *,
    default_status: str,
    default_reason: str,
    observations: int,
    as_of: date,
    source: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    status = str(raw.get("status") or default_status)
    if status in {"fallback", "partial", "missing"}:
        status = "degraded" if observations else "insufficient"
    if status not in {"ok", "insufficient", "degraded", "failed"}:
        status = default_status
    raw_warnings = raw.get("warnings")
    combined_warnings = [
        *(warnings or []),
        *(
            [str(raw_warnings)]
            if isinstance(raw_warnings, str)
            else [str(item) for item in raw_warnings or []]
        ),
    ]
    return _quality(
        status,
        str(raw.get("reason") or default_reason),
        int(raw.get("observations", observations) or 0),
        as_of,
        str(raw.get("source") or source) if raw.get("source") or source else None,
        list(dict.fromkeys(combined_warnings)),
    )


def _manifest_qualities(
    manifest: dict[str, Any] | None,
    facts: tuple[Any, ...],
    as_of: date,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    if manifest is None:
        empty = _empty_quality(as_of)
        return empty, _empty_quality(as_of, "missing-streak-evidence"), {
            group: _empty_quality(as_of, f"missing-{pool_type}-pool")
            for pool_type, group in _POOL_GROUPS.items()
        }
    source = str(manifest.get("source") or "unknown")
    warnings = [str(item) for item in manifest.get("warnings", ())]
    raw_pool_quality = manifest.get("pool_quality") or {}
    pool_quality: dict[str, dict[str, Any]] = {}
    for pool_type, group in _POOL_GROUPS.items():
        rows = [fact for fact in facts if fact.pool_type == pool_type and fact.membership_valid]
        raw = raw_pool_quality.get(pool_type, raw_pool_quality.get(group))
        complete = manifest.get("membership_complete") is True
        pool_quality[group] = _normalized_quality(
            raw,
            default_status="ok" if complete else "insufficient",
            default_reason="complete-pool-membership" if complete else "incomplete-pool-membership",
            observations=len(rows),
            as_of=as_of,
            source=source,
            warnings=warnings if not complete else None,
        )
    pool_degraded = any(
        quality["status"] in {"degraded", "failed"} for quality in pool_quality.values()
    )
    membership_complete = manifest.get("membership_complete") is True
    membership_status = (
        "degraded" if membership_complete and pool_degraded else "ok" if membership_complete else "insufficient"
    )
    membership_quality = _quality(
        membership_status,
        (
            "complete-degraded-pool-membership"
            if membership_status == "degraded"
            else "complete-pool-membership"
            if membership_status == "ok"
            else "incomplete-pool-membership"
        ),
        sum(1 for fact in facts if fact.membership_valid),
        as_of,
        source,
        warnings,
    )
    streak_complete = manifest.get("streak_complete") is True
    streak_status = (
        membership_status if streak_complete and membership_status in {"ok", "degraded"} else "insufficient"
    )
    streak_quality = _quality(
        streak_status,
        "complete-streak-facts" if streak_complete else "missing-streak-facts",
        sum(1 for fact in facts if fact.pool_type == "limit_up" and fact.membership_valid),
        as_of,
        source,
        warnings if streak_status != "ok" else None,
    )
    return membership_quality, streak_quality, pool_quality


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
            and manifest.get("membership_complete") is True
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
            and manifest is not None
            and manifest.get("streak_complete") is True
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


def _fact_dimensions(
    facts: tuple[Any, ...],
    manifest: dict[str, Any],
    as_of: date,
    source: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    limit_up_facts = [
        fact
        for fact in facts
        if fact.pool_type == "limit_up" and fact.membership_valid and fact.closed_limit_up is True
    ]
    observations = len(limit_up_facts)
    membership_complete = manifest.get("membership_complete") is True
    ladder_complete = (
        membership_complete
        and manifest.get("streak_complete") is True
        and all(fact.streak_days is not None and fact.streak_days >= 1 for fact in limit_up_facts)
    )
    ladder_status = "ok" if ladder_complete else "insufficient"
    ladder_reason = "complete-streak-facts" if ladder_complete else "missing-streak-facts"

    tiers = (
        ("first", "首板", 1),
        ("second", "二板", 2),
        ("third", "三板", 3),
        ("four_plus", "四板以上", 4),
    )
    ladder: list[dict[str, Any]] = []
    for tier, label, minimum in tiers:
        known_count = sum(
            1
            for fact in limit_up_facts
            if fact.streak_days is not None
            and (fact.streak_days == minimum if minimum < 4 else fact.streak_days >= minimum)
        )
        ladder.append(
            {
                "tier": tier,
                "label": label,
                "count": known_count if ladder_complete else None,
                "observations": observations,
                "quality": _quality(
                    ladder_status, ladder_reason, observations, as_of, source
                ),
            }
        )

    stratifications: list[dict[str, Any]] = []
    dimension_specs = (
        ("exchange", "exchange", {"SSE": "上交所", "SZSE": "深交所", "BSE": "北交所"}),
        (
            "regime",
            "limit_regime",
            {
                "main": "主板 10%",
                "st": "ST 5%",
                "chi_next": "创业板 20%",
                "star": "科创板 20%",
                "pct:30": "30%",
            },
        ),
        ("board", "board", {"main": "主板", "chi_next": "创业板", "star": "科创板"}),
    )
    for dimension, field_name, labels in dimension_specs:
        field_values = [getattr(fact, field_name) for fact in limit_up_facts]
        dimension_complete = membership_complete and all(
            value not in (None, "") for value in field_values
        )
        dimension_status = "ok" if dimension_complete else "insufficient"
        dimension_reason = (
            "complete-stratification-facts"
            if dimension_complete
            else f"missing-{field_name}-facts"
        )
        counts = Counter(value for value in field_values if value)
        for key, label in labels.items():
            stratifications.append(
                {
                    "dimension": dimension,
                    "key": key,
                    "label": label,
                    "count": int(counts.get(key, 0)) if dimension_complete else None,
                    "observations": observations,
                    "quality": _quality(
                        dimension_status,
                        dimension_reason,
                        observations,
                        as_of,
                        source,
                    ),
                }
            )

    st_complete = membership_complete and all(fact.is_st is not None for fact in limit_up_facts)
    new_complete = membership_complete and all(
        fact.is_new is not None
        or (fact.listing_days is not None and fact.listing_days >= 0)
        for fact in limit_up_facts
    )
    risk_specs = (
        ("st", "ST", st_complete, lambda fact: fact.is_st is True),
        (
            "ipo",
            "新股/上市不足窗口",
            new_complete,
            lambda fact: fact.is_new is True
            or (fact.is_new is None and fact.listing_days is not None and fact.listing_days < 5),
        ),
    )
    for key, label, dimension_complete, predicate in risk_specs:
        stratifications.append(
            {
                "dimension": "risk_tier",
                "key": key,
                "label": label,
                "count": (
                    sum(1 for fact in limit_up_facts if predicate(fact))
                    if dimension_complete
                    else None
                ),
                "observations": observations,
                "quality": _quality(
                    "ok" if dimension_complete else "insufficient",
                    (
                        "complete-risk-classification"
                        if dimension_complete
                        else "missing-risk-classification"
                    ),
                    observations,
                    as_of,
                    source,
                ),
            }
        )

    for key, label, predicate in (
        ("high", "高位（四板以上）", lambda fact: fact.streak_days is not None and fact.streak_days >= 4),
        ("middle", "中位（二至三板）", lambda fact: fact.streak_days in {2, 3}),
        ("low", "低位（首板）", lambda fact: fact.streak_days == 1),
    ):
        stratifications.append(
            {
                "dimension": "risk_tier",
                "key": key,
                "label": label,
                "count": (
                    sum(1 for fact in limit_up_facts if predicate(fact))
                    if ladder_complete
                    else None
                ),
                "observations": observations,
                "quality": _quality(
                    ladder_status, ladder_reason, observations, as_of, source
                ),
            }
        )
    stratifications.append(
        {
            "dimension": "sector",
            "key": "unknown",
            "label": "板块（来源未提供）",
            "count": None,
            "observations": observations,
            "quality": _quality(
                "insufficient", "provider-missing-sector", observations, as_of, source
            ),
        }
    )
    return ladder, stratifications


def _thscode(exchange: str, code: str) -> str | None:
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange)
    return f"{code}.{suffix}" if suffix and code else None


def _detail_row(fact: Any) -> dict[str, Any]:
    warnings = [str(item) for item in fact.row_warnings]
    if fact.invalid_reason and fact.invalid_reason not in warnings:
        warnings.append(str(fact.invalid_reason))
    return {
        "securityId": fact.security_id,
        "thscode": _thscode(fact.exchange, fact.code),
        "code": fact.code,
        "exchange": fact.exchange,
        "name": fact.name,
        "poolType": fact.pool_type,
        "isSt": fact.is_st,
        "isNew": fact.is_new,
        "listingDate": fact.listing_date.isoformat() if fact.listing_date else None,
        "closePrice": fact.close_price,
        "changePct": fact.change_pct,
        "streakDays": fact.streak_days,
        "limitUpTime": fact.limit_up_time,
        "limitUpReason": fact.limit_up_reason,
        "sealMoney": fact.seal_money,
        "maxSealMoney": fact.max_seal_money,
        "firstLimitTime": fact.first_limit_time,
        "lastLimitTime": fact.last_limit_time,
        "openTimes": fact.open_times,
        "turnoverRatioPct": fact.turnover_ratio_pct,
        "turnover": fact.turnover,
        "source": fact.source,
        "rowQuality": fact.row_quality or ("ok" if fact.eligible else "insufficient"),
        "warnings": warnings,
    }


def _security_details(
    store: Any,
    as_of: date,
    facts: tuple[Any, ...],
    manifest: dict[str, Any] | None,
    pool_quality: dict[str, dict[str, Any]],
    promotion: dict[str, Any],
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for pool_type, group in _POOL_GROUPS.items():
        rows = sorted(
            (
                fact
                for fact in facts
                if fact.pool_type == pool_type and fact.membership_valid
            ),
            key=lambda fact: (fact.exchange, fact.code, fact.security_id),
        )
        details[group] = {
            "total": len(rows) if manifest is not None else None,
            "rows": [_detail_row(fact) for fact in rows],
            "quality": pool_quality[group],
        }

    promotion_quality = promotion.get("promotionQuality")
    promoted_rows: list[Any] = []
    promoted_total: int | None = None
    previous_as_of = None
    try:
        resolution = TradingDayResolver(store).resolve(as_of)
        previous_as_of = resolution.previous_as_of if resolution.sufficient else None
        previous_manifest = (
            store.get_limit_security_dataset(previous_as_of) if previous_as_of else None
        )
        if (
            manifest
            and previous_manifest
            and manifest.get("membership_complete") is True
            and previous_manifest.get("membership_complete") is True
            and isinstance(promotion_quality, dict)
            and (
                promotion_quality.get("status") in {"ok", "degraded"}
                or promotion_quality.get("reason") == "zero-denominator"
            )
        ):
            previous_ids = {
                fact.security_id
                for fact in store.get_limit_security_facts(previous_as_of)
                if fact.pool_type == "limit_up"
                and fact.membership_valid
                and fact.closed_limit_up is True
            }
            promoted_rows = sorted(
                (
                    fact
                    for fact in facts
                    if fact.pool_type == "limit_up"
                    and fact.membership_valid
                    and fact.closed_limit_up is True
                    and fact.security_id in previous_ids
                ),
                key=lambda fact: (fact.exchange, fact.code, fact.security_id),
            )
            promoted_total = len(promoted_rows)
    except Exception:
        promoted_rows = []
        promoted_total = None
    details["promoted"] = {
        "total": promoted_total,
        "rows": [_detail_row(fact) for fact in promoted_rows],
        "quality": (
            promotion_quality
            if isinstance(promotion_quality, dict)
            else _empty_quality(as_of, "missing-promotion-evidence")
        ),
    }
    return details


def build_limit_ecosystem(store: Any, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge membership and field-specific limits evidence into the legacy payload."""
    value = dict(payload)
    manifest = store.get_limit_security_dataset(as_of)
    source = (
        str(manifest.get("source"))
        if manifest and manifest.get("source")
        else value.get("quality", {}).get("source")
        if isinstance(value.get("quality"), dict)
        else None
    )
    facts = store.get_limit_security_facts(as_of) if manifest is not None else ()
    membership_quality, streak_quality, pool_quality = _manifest_qualities(
        manifest, facts, as_of
    )
    if manifest is None:
        ladder: list[dict[str, Any]] = []
        stratifications: list[dict[str, Any]] = []
    else:
        ladder, stratifications = _fact_dimensions(facts, manifest, as_of, source)
    promotion = build_limit_promotion(store, as_of, dataset_quality=value.get("quality"))
    value.update(promotion)
    value["membershipQuality"] = membership_quality
    value["streakQuality"] = streak_quality
    value["poolQuality"] = pool_quality
    value["ladder"] = ladder
    value["stratifications"] = stratifications
    value["securityDetails"] = _security_details(
        store, as_of, facts, manifest, pool_quality, promotion
    )
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
        current_manifest
        and current_manifest.get("membership_complete") is True
        and current_manifest.get("actual_as_of") == as_of
    )
    previous_detail_complete = bool(
        previous_manifest
        and previous_manifest.get("membership_complete") is True
        and previous_manifest.get("actual_as_of") == previous_as_of
    )
    current_streak_complete = bool(
        current_detail_complete and current_manifest.get("streak_complete") is True
    )
    previous_streak_complete = bool(
        previous_detail_complete and previous_manifest.get("streak_complete") is True
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

    current_facts = facts
    previous_facts = store.get_limit_security_facts(previous_as_of) if previous_as_of else ()
    failed_ids = {
        fact.security_id
        for fact in previous_facts
        if fact.pool_type == "failed_limit_up" and fact.membership_valid
    }
    repaired_ids = {
        fact.security_id
        for fact in current_facts
        if fact.pool_type == "limit_up"
        and fact.membership_valid
        and fact.closed_limit_up is True
    }
    if failed_ids and previous_detail_complete and current_detail_complete:
        repair_ratio = round(len(failed_ids & repaired_ids) / len(failed_ids), 4)
        add_risk("failure-repair", "炸板修复", "ok", repair_ratio, "complete-failed-pool-and-current-close-set", [f"前一交易日炸板样本 {len(failed_ids)} 个", f"当前交易日修复 {len(failed_ids & repaired_ids)} 个"], observations=len(failed_ids))
    else:
        add_risk("failure-repair", "炸板修复", "insufficient", None, "missing-complete-failed-pool", ["缺少完整前一交易日炸板样本，无法计算修复率"])
    previous_streak = _metric_value(previous_snapshot.payload, "maxStreak") if previous_snapshot else None
    current_streak = _metric_value(value, "maxStreak")
    if current_streak_complete and previous_streak_complete and previous_snapshot is not None and previous_streak is not None and current_streak is not None:
        add_risk("ladder-change", "连板梯队升降", "ok", int(current_streak) - int(previous_streak), "exact-adjacent-max-streak-observations", [f"最高板 {previous_streak} -> {current_streak}"], observations=2)
    else:
        add_risk("ladder-change", "连板梯队升降", "insufficient", None, "missing-adjacent-max-streak", ["缺少精确相邻交易日最高板"])
    limit_up_members = [
        fact
        for fact in current_facts
        if fact.pool_type == "limit_up"
        and fact.membership_valid
        and fact.closed_limit_up is True
    ]
    board_counts = Counter(fact.board for fact in limit_up_members if fact.board)
    board_complete = current_detail_complete and all(fact.board for fact in limit_up_members)
    if board_complete and limit_up_members and board_counts:
        concentration = round(max(board_counts.values()) / len(limit_up_members), 4)
        add_risk(
            "board-concentration",
            "市场板块集中度（非行业）",
            "ok",
            concentration,
            "verified-board-concentration",
            [f"最大市场板块分层 {max(board_counts.values())}/{len(limit_up_members)}"],
            observations=len(limit_up_members),
        )
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
    value["invalidation"] = "交易日、分页或规范身份无法证明时，基础集合与晋级保持数据不足"
    value["ecosystemCoverage"] = round(valid / 60, 4) if valid < 60 else 1.0
    value["confidence"] = "high" if history["quality"]["status"] == "ok" and promotion.get("promotionQuality", {}).get("status") == "ok" else ("medium" if valid >= 5 else "insufficient")
    return value


__all__ = ["build_limit_ecosystem"]
