"""Pure breadth history, percentile, momentum and consistency analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .calculations import breadth_index_consistency, breadth_momentum, breadth_width_label


@dataclass(frozen=True, slots=True)
class BreadthAnalysisResult:
    payload: dict[str, Any]
    history_points: tuple[dict[str, Any], ...]
    history_observations: int
    history_coverage: float
    history_quality_status: str


def percentile_value(samples: list[float | None]) -> float | None:
    valid = [float(value) for value in samples if value is not None]
    if len(valid) < 60:
        return None
    current = valid[-1]
    return round(sum(value <= current for value in valid) / len(valid), 4)


def analyze_breadth(
    breadth: dict[str, Any],
    as_of: date,
    analyses: list[dict[str, Any]],
    *,
    recent_history: list[dict[str, Any]],
    percentile_history: list[dict[str, Any]],
) -> BreadthAnalysisResult:
    del as_of
    advance_count = breadth.get("advanceCount")
    decline_count = breadth.get("declineCount")
    valid_count = breadth.get("validCount")
    advance_ratio = breadth.get("advanceRatio")
    median_return = breadth.get("medianReturn")
    if decline_count is not None and valid_count:
        breadth["declineRatio"] = round(decline_count / valid_count, 4)
    else:
        breadth.setdefault("declineRatio", None)
    if advance_count is not None and decline_count is not None and valid_count:
        breadth["advanceDeclineSpread"] = round((advance_count - decline_count) / valid_count, 4)
    else:
        breadth.setdefault("advanceDeclineSpread", None)
    index_changes = [item.get("changePct") for item in analyses if isinstance(item, dict)]
    previous_ratio = recent_history[-1].get("advanceRatio") if recent_history else None
    previous_median = recent_history[-1].get("medianReturn") if recent_history else None
    breadth["indexConsistent"] = breadth_index_consistency(index_changes, median_return)
    breadth["widthLabel"], breadth["widthLabelReason"] = breadth_width_label(
        advance_ratio,
        median_return,
        index_changes,
        previous_ratio,
        previous_median,
    )
    recent_ratios: list[float | None] = []
    if previous_ratio is not None:
        recent_ratios.append(previous_ratio)
    for record in reversed(recent_history[:-1]):
        recent_ratios.insert(0, record.get("advanceRatio"))
    if advance_ratio is not None:
        recent_ratios.append(advance_ratio)
    breadth["momentum"] = breadth_momentum(recent_ratios[-6:])
    ratios = [item.get("advanceRatio") for item in percentile_history]
    medians = [item.get("medianReturn") for item in percentile_history]
    spreads = [item.get("advanceDeclineSpread") for item in percentile_history]
    momentums = [
        breadth_momentum([item.get("advanceRatio") for item in percentile_history[max(0, index - 5) : index + 1]])
        for index in range(len(percentile_history))
    ]
    breadth["advanceRatioPercentile"] = percentile_value(ratios)
    breadth["medianReturnPercentile"] = percentile_value(medians)
    breadth["spreadPercentile"] = percentile_value(spreads)
    breadth["momentumPercentile"] = percentile_value([value for value in momentums if value is not None])
    coverage = round(len(percentile_history) / 250.0, 4) if percentile_history else 0.0
    observations = len(percentile_history) + (1 if advance_ratio is not None else 0)
    return BreadthAnalysisResult(
        payload=breadth,
        history_points=tuple(recent_history[-5:]),
        history_observations=observations,
        history_coverage=coverage if recent_history else 0.0,
        history_quality_status="insufficient" if observations < 60 else "ok",
    )


__all__ = ["BreadthAnalysisResult", "analyze_breadth", "percentile_value"]
