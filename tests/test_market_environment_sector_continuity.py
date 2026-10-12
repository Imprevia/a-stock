from datetime import date, timedelta

import pytest

from src.market_environment.domain.analysis.sector_continuity import (
    aggregate_industry_daily,
    analyze_candidates,
    associate_provider_observation,
    build_continuity_result,
    concentration_trace,
    disagreement_recovery_ratio,
    midrank_percentile,
    normalize_metric_weights,
    relative_strength_trace,
    turnover_persistence_trace,
)
from src.market_environment.domain.models.sector_continuity import (
    InternalStructure,
    Lineage,
    MetricTrace,
)


AS_OF = date(2026, 10, 9)


def lineage() -> Lineage:
    return Lineage(
        requested_as_of=AS_OF,
        actual_as_of=AS_OF,
        source="fixture",
        source_revision="fixture-v1",
        schema_version=1,
        checksum="a" * 64,
    )


def test_midrank_ties_and_top_twenty_percent_are_deterministic():
    assert midrank_percentile(2, [1, 2, 2, 3]) == 0.5
    dates = [AS_OF - timedelta(days=offset) for offset in range(5)]
    rows = {day: {"A": 100, "B": 100, "C": 80, "D": 70, "E": 60, "F": 50} for day in dates}
    trace = turnover_persistence_trace(rows, "B", AS_OF)
    assert trace.value == 5  # ceil(.2 * 6) == 2, stable ID tie-break keeps A/B


def test_concentration_uses_min_five_and_stable_ties():
    trace = concentration_trace(
        {"b": 20, "a": 20, "c": 10, "d": 5, "e": 4, "f": 3},
        100,
        [0.5] * 60,
        as_of=AS_OF,
    )
    assert trace.raw["topIndustries"] == ["a", "b", "c", "d", "e"]
    assert trace.value == pytest.approx(0.59)


def test_relative_strength_requires_both_windows_and_nulls_missing_window():
    dates = [AS_OF - timedelta(days=offset) for offset in range(20)]
    returns = {day: 0.01 for day in dates}
    benchmark = {day: 0.0 for day in dates}
    complete = relative_strength_trace(returns, benchmark, AS_OF, history_5=[0.01] * 60, history_20=[0.02] * 60)
    assert complete.percentile is not None
    short_only = relative_strength_trace(returns, benchmark, AS_OF, history_5=[0.01] * 60, history_20=[])
    assert short_only.percentile is None
    assert short_only.status == "insufficient"


def test_disagreement_exact_half_recovery_is_success_and_unmatured_is_null():
    ratio, mature, _, _ = disagreement_recovery_ratio(
        [0.0, -0.10, 0.05, 0.05],
        [100.0, 90.0, 95.0, 95.0],
    )
    assert ratio == 1.0 and mature == 1
    ratio, mature, _, detail = disagreement_recovery_ratio([0.0, -0.1], [100.0, 90.0])
    assert ratio is None and mature == 0 and detail[-1]["mature"] is False


def test_aggregate_keeps_nulls_and_does_not_use_zero_denominator():
    aggregate = aggregate_industry_daily(
        industry_id="I1",
        as_of=AS_OF,
        member_facts=[
            {"securityId": "600001.SH", "eligible": True, "changePct": 0.1, "amount": 10, "adjustedClose": 11, "ma20": 10},
            {"securityId": "920001.BJ", "eligible": True, "changePct": None, "amount": None, "adjustedClose": None, "ma20": None},
        ],
        lineage=lineage(),
    )
    assert aggregate.industry_return == pytest.approx(0.1)
    assert aggregate.original_amount == pytest.approx(10)
    assert aggregate.breadth_ratio == 1.0
    assert aggregate.eligible_return_count == 1


def _trace(rule_id: str, score: int, percentile: float) -> MetricTrace:
    return MetricTrace(
        rule_id=rule_id,
        value=percentile,
        percentile=percentile,
        score=score,
        status="ok",
        weight=0.2,
        original_weight=0.2,
        normalized_weight=None,
        observations=250,
    )


def test_candidate_crowding_has_precedence_and_only_one_validation():
    traces = tuple(_trace(rule, 80, 0.85) for rule in ("QTS-01-05-01", "QTS-01-05-02")) + (_trace("QTS-01-05-03", 25, 0.35),)
    concentration = _trace("QTS-01-05-05", 100, 0.9)
    candidates, validation = analyze_candidates(
        {"I1": ("行业一", traces, InternalStructure(2, 1, 1, 0, 0, 0))},
        concentration=concentration,
    )
    assert candidates[0].stage == "high-level-crowding"
    assert validation.candidate_industry == "I1"
    assert "P40" in validation.target


def test_pending_disagreement_validation_has_recovery_priority():
    traces = tuple(_trace(rule, 80, 0.85) for rule in ("QTS-01-05-01", "QTS-01-05-02", "QTS-01-05-03"))
    candidates, validation = analyze_candidates(
        {"I1": ("行业一", traces, None)},
        pending_disagreement_by_industry={"I1": True},
    )
    assert candidates[0].stage == "mainline-candidate"
    assert "50%" in validation.target


def test_weight_normalization_and_replay_are_stable():
    traces = (_trace("a", 100, 0.9), MetricTrace("b", None, None, None, "insufficient", 1, 1, None, 10))
    normalized = normalize_metric_weights(traces)
    assert normalized[0].normalized_weight == 1.0
    assert normalized[1].normalized_weight is None
    result1 = build_continuity_result(
        as_of=AS_OF,
        traces=normalized,
        candidates=(),
        validation=analyze_candidates({})[1],
        lineage=lineage(),
    )
    result2 = build_continuity_result(
        as_of=AS_OF,
        traces=normalized,
        candidates=(),
        validation=analyze_candidates({})[1],
        lineage=lineage(),
    )
    assert result1 == result2


def test_observation_identity_mapping_never_guesses_by_name_or_uses_expired_mapping():
    mapping = {
        "providerId": "BK001",
        "shenwanIndustryId": "801080",
        "shenwanIndustryName": "电子",
        "mappingRevision": "map-v1",
        "validFrom": "2026-01-01",
        "validTo": None,
    }
    linked = associate_provider_observation({"code": "BK001", "name": "电子板块"}, [mapping], as_of=AS_OF)
    assert linked["shenwanIndustryId"] == "801080"
    assert associate_provider_observation({"code": "OTHER", "name": "电子"}, [mapping], as_of=AS_OF) is None
    ambiguous = [mapping, {**mapping, "shenwanIndustryId": "801081"}]
    assert associate_provider_observation({"code": "BK001"}, ambiguous, as_of=AS_OF) is None
