"""Deterministic Chapter 05 calculations.

All functions operate on normalized values and are intentionally side-effect
free.  Dates are never calendar-filled; callers pass only proven trading
sessions.  Percentiles use the same midrank convention for ties and include
the current observation in the rolling sample.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from ..models.sector_continuity import (
    CandidateIndustry,
    CandidateStage,
    IndustryAggregate,
    InternalStructure,
    Lineage,
    MetricTrace,
    SectorContinuityResult,
    UniqueValidation,
)


CORE_RULES = (
    ("QTS-01-05-01", "sector.relative_strength_percentile", 0.25),
    ("QTS-01-05-02", "sector.top_turnover_days", 0.20),
    ("QTS-01-05-03", "sector.above_ma20_ratio_percentile", 0.20),
    ("QTS-01-05-04", "sector.disagreement_recovery_percentile", 0.20),
    ("QTS-01-05-05", "sector.top5_turnover_concentration_percentile", 0.15),
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def midrank_percentile(value: float | None, sample: Iterable[float | None]) -> float | None:
    """Return a deterministic [0, 1] midrank percentile.

    ``(less + .5 * equal) / n`` is deliberately used instead of a library
    percentile so equal observations always receive the same value.
    """

    current = _number(value)
    values = sorted(number for item in sample if (number := _number(item)) is not None)
    if current is None or not values:
        return None
    less = sum(item < current for item in values)
    equal = sum(item == current for item in values)
    return (less + 0.5 * equal) / len(values)


def rolling_midrank(value: float | None, history: Sequence[float | None], *, minimum: int = 60, window: int = 250) -> tuple[float | None, int, str]:
    values = [number for item in history if (number := _number(item)) is not None]
    if value is not None:
        values.append(float(value))
    if len(values) < minimum:
        return None, len(values), "insufficient"
    sample = values[-window:]
    return midrank_percentile(value, sample), len(values), "ok" if len(values) >= window else "reduced-confidence"


def percentile_score(percentile: float | None) -> int | None:
    if percentile is None:
        return None
    if percentile <= 0.20:
        return 0
    if percentile <= 0.40:
        return 25
    if percentile <= 0.60:
        return 50
    if percentile <= 0.80:
        return 75
    return 100


def turnover_days_score(days: int | None) -> int | None:
    if days is None:
        return None
    if days <= 0:
        return 0
    if days == 1:
        return 25
    if days == 2:
        return 50
    if days == 3:
        return 75
    return 100


def _trace(
    rule_id: str,
    value: float | int | None,
    percentile: float | None,
    *,
    status: str,
    observations: int,
    weight: float,
    raw: Mapping[str, Any] | None = None,
    reason: str | None = None,
    sample_dates: Sequence[date] = (),
    score: int | None = None,
) -> MetricTrace:
    return MetricTrace(
        rule_id=rule_id,
        value=value,
        percentile=percentile,
        score=score if score is not None else percentile_score(percentile),
        status=status,  # type: ignore[arg-type]
        weight=weight,
        original_weight=weight,
        normalized_weight=weight if score is not None or percentile is not None else None,
        observations=observations,
        missing_reason=reason,
        sample_dates=tuple(sample_dates),
        raw=dict(raw or {}),
    )


def relative_strength_trace(
    industry_returns: Mapping[date, float | None],
    benchmark_returns: Mapping[date, float | None],
    as_of: date,
    *,
    history_5: Sequence[float | None] = (),
    history_20: Sequence[float | None] = (),
) -> MetricTrace:
    def cumulative(window: int) -> float | None:
        sessions = sorted(set(industry_returns) & set(benchmark_returns))
        sessions = [item for item in sessions if item <= as_of][-window:]
        if len(sessions) < window:
            return None
        excess = []
        for session in sessions:
            industry = _number(industry_returns.get(session))
            benchmark = _number(benchmark_returns.get(session))
            if industry is None or benchmark is None:
                return None
            excess.append(industry - benchmark)
        return sum(excess)

    short = cumulative(5)
    medium = cumulative(20)
    short_pct, short_obs, short_status = rolling_midrank(short, history_5)
    medium_pct, medium_obs, medium_status = rolling_midrank(medium, history_20)
    valid = short_pct is not None and medium_pct is not None
    percentile = min(short_pct, medium_pct) if valid else None
    status = "ok" if valid and short_status == medium_status == "ok" else ("reduced-confidence" if valid else "insufficient")
    reason = None if valid else "relative-strength-window-incomplete"
    return _trace(
        "QTS-01-05-01",
        percentile,
        percentile,
        status=status,
        observations=min(short_obs, medium_obs),
        weight=0.25,
        reason=reason,
        raw={"excessReturn5": short, "excessReturn20": medium, "percentile5": short_pct, "percentile20": medium_pct},
    )


def turnover_persistence_trace(
    turnover_by_date: Mapping[date, Mapping[str, float | None]],
    industry_id: str,
    as_of: date,
) -> MetricTrace:
    sessions = sorted(item for item in turnover_by_date if item <= as_of)[-5:]
    count = 0
    selected: list[date] = []
    cross_section_count = 0
    for session in sessions:
        values = [(key, _number(value)) for key, value in turnover_by_date[session].items()]
        values = [(key, value) for key, value in values if value is not None]
        if not values or industry_id not in dict(values):
            continue
        values.sort(key=lambda item: (-item[1], item[0]))
        n = max(1, math.ceil(0.20 * len(values)))
        if industry_id in {key for key, _ in values[:n]}:
            count += 1
            selected.append(session)
        cross_section_count = max(cross_section_count, len(values))
    status = "ok" if len(sessions) == 5 and cross_section_count else "insufficient"
    return _trace(
        "QTS-01-05-02",
        count if status != "insufficient" else None,
        None,
        status=status,
        observations=len(sessions),
        weight=0.20,
        score=turnover_days_score(count) if status != "insufficient" else None,
        reason=None if status == "ok" else "cross-section-history-incomplete",
        sample_dates=selected,
        raw={"selectedSessions": selected, "crossSectionCount": cross_section_count},
    )


def breadth_trace(
    breadth_ratio: float | None,
    history: Sequence[float | None],
    *,
    as_of: date,
) -> MetricTrace:
    percentile, observations, status = rolling_midrank(breadth_ratio, history)
    return _trace(
        "QTS-01-05-03",
        breadth_ratio,
        percentile,
        status=status,
        observations=observations,
        weight=0.20,
        reason=None if breadth_ratio is not None else "zero-denominator",
        sample_dates=(as_of,),
        raw={"breadthRatio": breadth_ratio},
    )


def equal_weight_return(values: Sequence[float | None]) -> tuple[float | None, int, int]:
    """Return an equal-weight mean and eligible/excluded counts.

    The function deliberately excludes missing/non-finite values and never
    turns an empty denominator into zero.
    """

    valid = [number for item in values if (number := _number(item)) is not None]
    return (sum(valid) / len(valid) if valid else None, len(valid), len(values) - len(valid))


def aggregate_industry_daily(
    *,
    industry_id: str,
    as_of: date,
    member_facts: Sequence[Mapping[str, Any]],
    lineage: Lineage,
    ma20_by_security: Mapping[str, float | None] | None = None,
) -> IndustryAggregate:
    """Aggregate one exact-date Shenwan industry without provider semantics."""

    ma20_by_security = ma20_by_security or {}
    returns: list[float | None] = []
    amounts: list[float | None] = []
    eligible_ma = 0
    above_ma = 0
    advance = decline = flat = 0
    limit_up = limit_down = 0
    excluded: dict[str, int] = defaultdict(int)
    for fact in member_facts:
        if not fact.get("eligible", True):
            excluded[str(fact.get("exclusionReason") or "ineligible")] += 1
            continue
        change = _number(fact.get("changePct"))
        returns.append(change)
        amount = _number(fact.get("amount"))
        amounts.append(amount)
        if amount is None:
            excluded["amount-missing"] += 1
        if change is None:
            excluded["return-missing"] += 1
        elif change > 0:
            advance += 1
        elif change < 0:
            decline += 1
        else:
            flat += 1
        if fact.get("limitUp") is True:
            limit_up += 1
        if fact.get("limitDown") is True:
            limit_down += 1
        security_id = str(fact.get("securityId") or "")
        ma20 = _number(ma20_by_security.get(security_id, fact.get("ma20")))
        close = _number(fact.get("adjustedClose"))
        if ma20 is not None and close is not None:
            eligible_ma += 1
            if close > ma20:
                above_ma += 1
        else:
            excluded["ma20-missing"] += 1
    industry_return, eligible_return, return_excluded = equal_weight_return(returns)
    original_amount = sum(value for value in amounts if value is not None) if any(value is not None for value in amounts) else None
    eligible_amount = sum(value is not None for value in amounts)
    breadth_ratio = above_ma / eligible_ma if eligible_ma else None
    return IndustryAggregate(
        industry_id=industry_id,
        as_of=as_of,
        member_count=len(member_facts),
        eligible_return_count=eligible_return,
        eligible_amount_count=eligible_amount,
        eligible_ma20_count=eligible_ma,
        industry_return=industry_return,
        original_amount=original_amount,
        breadth_ratio=breadth_ratio,
        advance_count=advance,
        decline_count=decline,
        flat_count=flat,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        excluded_reasons=dict(excluded),
        lineage=lineage,
    )


def disagreement_recovery_ratio(
    returns: Sequence[float | None],
    closes: Sequence[float | None],
    *,
    mature_window: int = 20,
) -> tuple[float | None, int, int, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    start = max(1, len(returns) - mature_window)
    for index in range(start, len(returns)):
        change = _number(returns[index])
        if change is None or change >= 0:
            continue
        if index + 2 >= len(closes):
            events.append({"index": index, "mature": False, "recovered": None})
            continue
        pre = _number(closes[index - 1]) if index > 0 else None
        event_close = _number(closes[index])
        follow = [_number(closes[index + offset]) for offset in (1, 2)]
        if pre is None or event_close is None or any(item is None for item in follow):
            events.append({"index": index, "mature": False, "recovered": None})
            continue
        decline = pre - event_close
        recovered = decline <= 0 or any(item >= event_close + decline * 0.5 for item in follow)
        events.append({"index": index, "mature": True, "recovered": recovered})
    mature = [item for item in events if item["mature"]]
    if not mature:
        return None, 0, len(events), events
    recovered = sum(bool(item["recovered"]) for item in mature)
    return recovered / len(mature), len(mature), len(events), events


def disagreement_trace(
    returns: Sequence[float | None],
    closes: Sequence[float | None],
    history: Sequence[float | None],
    *,
    as_of: date,
) -> MetricTrace:
    ratio, mature, events, detail = disagreement_recovery_ratio(returns, closes)
    percentile, observations, status = rolling_midrank(ratio, history)
    if ratio is None:
        status = "insufficient"
    return _trace(
        "QTS-01-05-04",
        ratio,
        percentile,
        status=status,
        observations=observations,
        weight=0.20,
        reason="event-not-matured" if mature == 0 else None,
        sample_dates=(as_of,),
        raw={"matureEvents": mature, "events": events, "eventTrace": detail},
    )


def concentration_trace(
    amount_by_industry: Mapping[str, float | None],
    market_amount: float | None,
    history: Sequence[float | None],
    *,
    as_of: date,
) -> MetricTrace:
    amounts = [(key, _number(value)) for key, value in amount_by_industry.items()]
    amounts = [(key, value) for key, value in amounts if value is not None]
    denominator = _number(market_amount)
    if denominator is None or denominator <= 0 or not amounts:
        return _trace("QTS-01-05-05", None, None, status="insufficient", observations=0, weight=0.15, reason="incompatible-market-denominator")
    amounts.sort(key=lambda item: (-item[1], item[0]))
    top = amounts[: min(5, len(amounts))]
    concentration = sum(value for _, value in top) / denominator
    percentile, observations, status = rolling_midrank(concentration, history)
    return _trace(
        "QTS-01-05-05",
        concentration,
        percentile,
        status=status,
        observations=observations,
        weight=0.15,
        reason=None if status != "insufficient" else "insufficient-concentration-history",
        sample_dates=(as_of,),
        raw={"topIndustries": [key for key, _ in top], "marketAmount": denominator},
    )


def _candidate_sort_key(candidate: CandidateIndustry) -> tuple[float, float, float, str]:
    core = candidate.core_scores
    return (
        -(candidate.total_score if candidate.total_score is not None else -1),
        -(float(core.get("QTS-01-05-01") or -1)),
        -(float(core.get("QTS-01-05-02") or -1)),
        candidate.industry_id,
    )


def _validation_for(
    candidate: CandidateIndustry | None,
    concentration: MetricTrace | None,
    *,
    pending_disagreement: bool = False,
) -> UniqueValidation:
    if candidate is None:
        return UniqueValidation(
            candidate_industry=None,
            candidate_name=None,
            stage="insufficient",
            persistence_evidence="关键申万身份、历史或行业事实尚未恢复",
            breadth_evidence="宽度证据不可用",
            turnover_evidence="成交证据不可用",
            internal_structure="无可验证的内部结构事实",
            target="恢复精确日期申万成员、前复权价格或原始成交额历史",
            confirmation_condition="所需事实恢复且五项指标按同日版本重算",
            invalidation_condition="身份或关键日期继续缺失，保持 insufficient",
        )
    missing = [trace.rule_id for trace in candidate.rule_traces if trace.percentile is None or trace.score is None]
    if missing:
        return UniqueValidation(
            candidate_industry=candidate.industry_id,
            candidate_name=candidate.display_name,
            stage="insufficient",
            persistence_evidence="持续性历史不足或分位不可用",
            breadth_evidence="宽度历史不足或分母无效",
            turnover_evidence="成交持续性历史不足或横截面不完整",
            internal_structure="仅展示已证明的内部结构事实，不推断角色",
            target=f"恢复缺失指标：{', '.join(missing)}",
            confirmation_condition="缺失指标恢复且核心三项分数各至少 60",
            invalidation_condition="关键指标继续缺失，保持 insufficient",
        )
    crowding = bool(candidate.crowding_risk)
    if crowding:
        target = "分歧后板块宽度能否恢复至 P40（40%）"
        confirm = "宽度分位达到或超过 P40（40%）且核心三项分数各至少 60"
    elif pending_disagreement:
        target = "分歧后能否在两个完整交易日内收复至少 50% 的跌幅"
        confirm = "后续两个完整交易日内收复下跌幅度至少 50%，且核心三项分数各至少 60"
    elif candidate.stage == "mainline-confirmed":
        target = "下一次分歧后板块能否承接"
        confirm = "两日内收复下跌幅度至少 50%，核心三项分数各至少 60"
    else:
        target = "分歧后板块能否承接"
        confirm = "核心三项分数在下一次分歧后仍各至少 60"
    return UniqueValidation(
        candidate_industry=candidate.industry_id,
        candidate_name=candidate.display_name,
        stage=candidate.stage,
        persistence_evidence=f"持续性分数 {candidate.core_scores.get('QTS-01-05-01') or '--'}",
        breadth_evidence=f"宽度分数 {candidate.core_scores.get('QTS-01-05-03') or '--'}",
        turnover_evidence=f"成交持续性分数 {candidate.core_scores.get('QTS-01-05-02') or '--'}",
        internal_structure="仅展示成交排名、涨跌家数、单股贡献和扩散比例，不推断角色",
        target=target,
        confirmation_condition=confirm,
        invalidation_condition="核心三项任一低于 60，或两日内未收复至少 50%",
    )


def analyze_candidates(
    traces_by_industry: Mapping[str, tuple[str, Sequence[MetricTrace], InternalStructure | None]],
    *,
    concentration: MetricTrace | None = None,
    confirmation_streak_by_industry: Mapping[str, int] | None = None,
    mature_recovery_by_industry: Mapping[str, bool | None] | None = None,
    one_day_excess_by_industry: Mapping[str, float | None] | None = None,
    pending_disagreement_by_industry: Mapping[str, bool] | None = None,
) -> tuple[tuple[CandidateIndustry, ...], UniqueValidation]:
    confirmation_streak_by_industry = confirmation_streak_by_industry or {}
    mature_recovery_by_industry = mature_recovery_by_industry or {}
    one_day_excess_by_industry = one_day_excess_by_industry or {}
    pending_disagreement_by_industry = pending_disagreement_by_industry or {}
    ranked_one_day = [key for key, value in one_day_excess_by_industry.items() if _number(value) is not None]
    ranked_one_day.sort(key=lambda key: (-float(one_day_excess_by_industry[key]), key))
    top_quintile_ids = set(ranked_one_day[: max(1, math.ceil(len(ranked_one_day) * 0.2))]) if ranked_one_day else set()
    candidates: list[CandidateIndustry] = []
    for industry_id, (display_name, traces, structure) in traces_by_industry.items():
        trace_map = {item.rule_id: item for item in traces}
        core_scores = {rule_id: trace_map.get(rule_id).score if trace_map.get(rule_id) else None for rule_id, _, _ in CORE_RULES[:3]}
        valid_core = all(score is not None and score >= 60 for score in core_scores.values())
        available_scores = [item.score for item in traces if item.score is not None]
        total_score = sum(float(item.score) * item.weight for item in traces if item.score is not None) / sum(item.weight for item in traces if item.score is not None) if available_scores else None
        breadth_trace_item = trace_map.get("QTS-01-05-03")
        crowding = (
            concentration is not None and concentration.percentile is not None and concentration.percentile > 0.80
            and breadth_trace_item is not None and breadth_trace_item.percentile is not None
            and breadth_trace_item.percentile < 0.40
        )
        streak = int(confirmation_streak_by_industry.get(industry_id, 0) or 0)
        recovery = mature_recovery_by_industry.get(industry_id)
        if not traces:
            stage: CandidateStage = "insufficient"
        elif crowding:
            stage = "high-level-crowding"
        elif total_score is not None and total_score >= 70 and streak >= 3 and recovery is not False:
            stage = "mainline-confirmed"
        elif valid_core:
            stage = "mainline-candidate"
        elif industry_id in top_quintile_ids:
            stage = "one-day-pulse"
        else:
            stage = "insufficient" if any(item.percentile is None for item in traces) else "rotation-or-ebb"
        candidates.append(CandidateIndustry(
            industry_id=industry_id,
            display_name=display_name,
            stage=stage,
            total_score=total_score,
            core_scores=core_scores,
            rule_traces=tuple(traces),
            crowding_risk=crowding,
            vetoes=("sector_crowding_without_breadth",) if crowding else (),
            internal_structure=structure,
            confirmation_streak=streak,
        ))
    candidates.sort(key=_candidate_sort_key)
    selected = tuple(candidates[:3])
    first = selected[0] if selected else None
    return selected, _validation_for(
        first,
        concentration,
        pending_disagreement=bool(first and pending_disagreement_by_industry.get(first.industry_id)),
    )


def render_unique_validation(validation: UniqueValidation) -> str:
    return validation.render()


def normalize_metric_weights(traces: Sequence[MetricTrace]) -> tuple[MetricTrace, ...]:
    """Preserve original weights while normalizing only available metrics."""

    available = [trace for trace in traces if trace.percentile is not None and trace.score is not None]
    denominator = sum(trace.original_weight for trace in available)
    result: list[MetricTrace] = []
    for trace in traces:
        normalized = trace.original_weight / denominator if denominator and trace in available else None
        result.append(replace(trace, normalized_weight=normalized))
    return tuple(result)


def confidence_for_traces(traces: Sequence[MetricTrace]) -> tuple[str, float | None]:
    """Return coverage/confidence using the documented 90/70/50 bands."""

    if not traces:
        return "insufficient", 0.0
    valid = sum(trace.percentile is not None and trace.score is not None for trace in traces)
    coverage = valid / len(traces)
    if coverage < 0.5:
        return "insufficient", coverage
    if coverage < 0.7:
        return "low", coverage
    if coverage < 0.9:
        return "medium", coverage
    return "high", coverage


def build_continuity_result(
    *,
    as_of: date,
    traces: Sequence[MetricTrace],
    candidates: Sequence[CandidateIndustry],
    validation: UniqueValidation,
    lineage: Lineage,
    missing_inputs: Sequence[str] = (),
    warnings: Sequence[str] = (),
) -> SectorContinuityResult:
    normalized = normalize_metric_weights(traces)
    confidence, coverage = confidence_for_traces(normalized)
    status = "ok" if confidence == "high" else ("partial" if confidence in {"medium", "low"} else "insufficient")
    if any(trace.status in {"failed", "missing"} for trace in normalized):
        status = "failed"
    return SectorContinuityResult(
        as_of=as_of,
        status=status,
        confidence=confidence,  # type: ignore[arg-type]
        coverage=coverage,
        metrics=normalized,
        candidates=tuple(candidates[:3]),
        validation=validation,
        lineage=lineage,
        missing_inputs=tuple(missing_inputs),
        warnings=tuple(warnings),
    )


def associate_provider_observation(
    observation: Mapping[str, Any],
    mappings: Sequence[Mapping[str, Any]],
    *,
    as_of: date,
) -> dict[str, Any] | None:
    """Associate only one explicit provider-ID mapping effective on ``as_of``.

    Display names are never used as an identity key. Ambiguous, expired or
    incomplete mappings deliberately remain unlinked.
    """

    provider_id = observation.get("code") or observation.get("providerId")
    if not provider_id:
        return None
    eligible: list[Mapping[str, Any]] = []
    for mapping in mappings:
        if mapping.get("providerId") != provider_id:
            continue
        try:
            valid_from = date.fromisoformat(str(mapping.get("validFrom")))
            valid_to = date.fromisoformat(str(mapping["validTo"])) if mapping.get("validTo") else None
        except (TypeError, ValueError):
            continue
        if valid_from <= as_of and (valid_to is None or as_of < valid_to):
            eligible.append(mapping)
    identities = {str(item.get("shenwanIndustryId") or "") for item in eligible}
    if len(eligible) != 1 or len(identities) != 1 or "" in identities:
        return None
    mapping = eligible[0]
    required = ("shenwanIndustryName", "mappingRevision", "validFrom")
    if any(not str(mapping.get(key) or "").strip() for key in required):
        return None
    return {
        "providerId": str(provider_id),
        "providerName": observation.get("name"),
        "shenwanIndustryId": str(mapping["shenwanIndustryId"]),
        "shenwanIndustryName": str(mapping["shenwanIndustryName"]),
        "mappingRevision": str(mapping["mappingRevision"]),
        "validFrom": str(mapping["validFrom"]),
        "validTo": str(mapping["validTo"]) if mapping.get("validTo") else None,
    }


__all__ = [
    "CORE_RULES", "aggregate_industry_daily", "analyze_candidates", "associate_provider_observation", "breadth_trace", "build_continuity_result", "confidence_for_traces", "concentration_trace",
    "disagreement_recovery_ratio", "disagreement_trace", "midrank_percentile",
    "percentile_score", "relative_strength_trace", "render_unique_validation",
    "rolling_midrank", "turnover_days_score", "turnover_persistence_trace", "equal_weight_return", "normalize_metric_weights",
]
