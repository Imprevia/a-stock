"""Deterministic QTS-04-01 sector scoring.

Every function here is side-effect free and operates on normalized values.
Missing inputs stay ``None``; nothing is filled with zero.  All thresholds are
documented defaults whose calibration status remains ``needs-backtest``.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

# Shared model lives in qts04-core; the names stay importable from here.
_CORE = Path(__file__).resolve().parents[2] / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
from qts04.model import Bar, normalize_bars, to_number  # noqa: E402

# (rule id, metric name, weight) in upstream order; never reorder.
RULE_WEIGHTS = (
    ("QTS-04-01-01", "relative_strength_5", 0.25),
    ("QTS-04-01-02", "relative_strength_20", 0.15),
    ("QTS-04-01-03", "turnover_ratio", 0.20),
    ("QTS-04-01-04", "breadth_ratio", 0.20),
    ("QTS-04-01-05", "persistence", 0.20),
)

MIN_OBSERVATIONS = 60
FULL_WINDOW = 250
MIN_BREADTH_COVERAGE = 0.70

# Interpretive defaults for the four-quadrant split; see scoring-rules.md.
STRENGTH_TURNOVER_RATIO = 1.20
BROAD_ADVANCE_RATIO = 0.50

# Pool thresholds; ``pool_state`` is the only place that may apply them.
FOCUS_TOTAL_SCORE = 70
FOCUS_PERSISTENCE_SCORE = 60
WATCH_TOTAL_SCORE = 50

# Effective-metric coverage thresholds for confidence.
CONFIDENCE_HIGH_COVERAGE = 0.90
CONFIDENCE_MEDIUM_COVERAGE = 0.70
CONFIDENCE_LOW_COVERAGE = 0.50

# Rolling windows used by the three percentile rules.
RELATIVE_STRENGTH_5_WINDOW = 5
RELATIVE_STRENGTH_20_WINDOW = 20
TURNOVER_WINDOW = 20

STATUS_OK = "ok"
STATUS_REDUCED = "reduced-confidence"
STATUS_INSUFFICIENT = "insufficient"


def midrank_percentile(value: float | None, sample: Iterable[float | None]) -> float | None:
    """Deterministic [0, 1] midrank percentile; ties share one value."""

    current = to_number(value)
    values = sorted(number for item in sample if (number := to_number(item)) is not None)
    if current is None or not values:
        return None
    less = sum(item < current for item in values)
    equal = sum(item == current for item in values)
    return (less + 0.5 * equal) / len(values)


def rolling_midrank(
    value: float | None,
    history: Sequence[float | None],
    *,
    minimum: int = MIN_OBSERVATIONS,
    window: int = FULL_WINDOW,
) -> tuple[float | None, int, str]:
    """Return ``(percentile, observations, status)`` for a rolling window.

    Fewer than ``minimum`` usable observations yields ``insufficient`` and a
    ``None`` percentile; fewer than ``window`` yields ``reduced-confidence``.
    """

    values = [number for item in history if (number := to_number(item)) is not None]
    if to_number(value) is not None:
        values.append(float(value))  # type: ignore[arg-type]
    observations = len(values)
    if observations < minimum:
        return None, observations, STATUS_INSUFFICIENT
    sample = values[-window:]
    percentile = midrank_percentile(value, sample)
    status = STATUS_OK if observations >= window else STATUS_REDUCED
    return percentile, observations, status


def percentile_score(percentile: float | None) -> int | None:
    """Map a percentile to the documented five tiers."""

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


def ratio_tier_score(ratio: float | None) -> int | None:
    """Map a unit-interval ratio to the same five tiers."""

    return percentile_score(ratio)


def win_days_score(days: int | None) -> int | None:
    """Map a 0-5 winning-session count onto five tiers."""

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


def slice_until(bars: Sequence[Bar], as_of: date) -> list[Bar]:
    """Keep bars up to and including ``as_of``; never borrow another date."""

    return [bar for bar in bars if bar.trading_date <= as_of]


def has_session(bars: Sequence[Bar], as_of: date) -> bool:
    return any(bar.trading_date == as_of for bar in bars)


def period_return(bars: Sequence[Bar], window: int) -> float | None:
    """Simple close-to-close return over ``window`` sessions."""

    if window < 1 or len(bars) < window + 1:
        return None
    start = bars[-(window + 1)].close
    end = bars[-1].close
    if start == 0:
        return None
    return (end - start) / start


def daily_returns(bars: Sequence[Bar]) -> dict[date, float | None]:
    returns: dict[date, float | None] = {}
    for index in range(1, len(bars)):
        previous = bars[index - 1].close
        current = bars[index].close
        returns[bars[index].trading_date] = None if previous == 0 else (current - previous) / previous
    return returns


def excess_returns(
    sector: Sequence[Bar], benchmark: Sequence[Bar]
) -> tuple[dict[date, float | None], list[float | None]]:
    """Return per-session excess series aligned on common trading dates."""

    sector_returns = daily_returns(sector)
    benchmark_returns = daily_returns(benchmark)
    common = sorted(set(sector_returns) & set(benchmark_returns))
    series: list[float | None] = []
    mapping: dict[date, float | None] = {}
    for session in common:
        left = sector_returns[session]
        right = benchmark_returns[session]
        value = None if left is None or right is None else left - right
        mapping[session] = value
        series.append(value)
    return mapping, series


def relative_strength(
    sector: Sequence[Bar], benchmark: Sequence[Bar], window: int
) -> tuple[float | None, list[float | None]]:
    """Excess return accumulated over ``window`` aligned sessions.

    Returns ``(current excess, historical excess series)``.  The history is the
    rolling sum of the same definition, used as the percentile sample.
    """

    mapping, series = excess_returns(sector, benchmark)
    clean = [number for number in series if number is not None]
    if len(clean) < window:
        return None, []
    current = sum(clean[-window:])
    history: list[float | None] = []
    for index in range(window, len(clean) + 1):
        history.append(sum(clean[index - window : index]))
    return current, history


def turnover_ratio(bars: Sequence[Bar], window: int = 20) -> tuple[float | None, list[float | None]]:
    """Today's turnover divided by the trailing mean that excludes today."""

    if len(bars) < window + 1:
        return None, []
    turnovers = [bar.turnover for bar in bars]
    if any(value is None for value in turnovers[-(window + 1) :]):
        return None, []

    def compute(index: int) -> float | None:
        if index < window:
            return None
        trailing = [turnovers[index - offset] for offset in range(1, window + 1)]
        if any(value is None for value in trailing):
            return None
        mean = sum(trailing) / window  # type: ignore[arg-type]
        if mean == 0:
            return None
        current = turnovers[index]
        if current is None:
            return None
        return current / mean

    history: list[float | None] = []
    for index in range(window, len(turnovers)):
        history.append(compute(index))
    current = history[-1] if history else None
    return current, history


def winning_days(
    sector: Sequence[Bar], benchmark: Sequence[Bar], window: int = 5
) -> tuple[int | None, list[int | None]]:
    """Count aligned sessions in the last ``window`` where sector beat benchmark."""

    mapping, _ = excess_returns(sector, benchmark)
    sessions = sorted(mapping)
    if len(sessions) < window:
        return None, []
    history: list[int | None] = []
    for end in range(window, len(sessions) + 1):
        chunk = sessions[end - window : end]
        values = [mapping[session] for session in chunk]
        if any(value is None for value in values):
            history.append(None)
        else:
            history.append(sum(1 for value in values if value > 0))
    return history[-1] if history else None, history


def drawdown_recovery(bars: Sequence[Bar], window: int = 20) -> float | None:
    """Recovery fraction from the window trough back toward the window peak."""

    if len(bars) < 2:
        return None
    closes = [bar.close for bar in bars[-window:]]
    if not closes or any(value is None for value in closes):
        return None
    peak = max(closes)
    trough_index = closes.index(min(closes))
    trough = closes[trough_index]
    peak_index = closes.index(peak)
    # Only a drawdown that happened before the trough is recoverable.
    if peak_index > trough_index:
        peak = max(closes[: trough_index + 1]) if trough_index >= 0 else peak
    if peak <= trough:
        return 1.0
    return (closes[-1] - trough) / (peak - trough)


def persistence_metric(
    sector: Sequence[Bar], benchmark: Sequence[Bar]
) -> tuple[float | None, int, str, dict[str, Any]]:
    """QTS-04-01-05: mean of winning-days score and drawdown-recovery score."""

    days, _ = winning_days(sector, benchmark, 5)
    recovery = drawdown_recovery(sector, 20)
    observations = min(len(daily_returns(sector)), len(daily_returns(benchmark)), len(sector))
    raw: dict[str, Any] = {
        "winningDays": days,
        "recoveryRate": recovery,
    }
    if days is None or recovery is None:
        return None, observations, STATUS_INSUFFICIENT, raw
    day_score = win_days_score(days)
    recovery_score = ratio_tier_score(recovery)
    if day_score is None or recovery_score is None:
        return None, observations, STATUS_INSUFFICIENT, raw
    value = (day_score + recovery_score) / 2
    if observations < MIN_OBSERVATIONS:
        status = STATUS_INSUFFICIENT
    elif observations < FULL_WINDOW:
        status = STATUS_REDUCED
    else:
        status = STATUS_OK
    raw["winningDaysScore"] = day_score
    raw["recoveryScore"] = recovery_score
    return value, observations, status, raw


def member_ma20(
    member_bars: Mapping[str, Sequence[Bar]], as_of: date, window: int = 20
) -> tuple[float | None, float, int, int]:
    """Return ``(breadth ratio, coverage, valid count, total count)``.

    Coverage is ``valid / total``; a zero denominator yields ``None`` rather
    than a fabricated ratio.
    """

    total = len(member_bars)
    if total == 0:
        return None, 0.0, 0, 0
    valid = 0
    above = 0
    for bars in member_bars.values():
        selected = slice_until(bars, as_of)
        if len(selected) < window or not has_session(selected, as_of):
            continue
        closes = [bar.close for bar in selected[-window:]]
        mean = sum(closes) / window
        valid += 1
        if selected[-1].close > mean:
            above += 1
    coverage = valid / total
    if valid == 0:
        return None, coverage, 0, total
    return above / valid, coverage, valid, total


def advance_ratio(member_bars: Mapping[str, Sequence[Bar]], as_of: date) -> float | None:
    """Share of members whose latest close is above the previous close."""

    valid = 0
    advancing = 0
    for bars in member_bars.values():
        selected = slice_until(bars, as_of)
        if len(selected) < 2 or not has_session(selected, as_of):
            continue
        valid += 1
        if selected[-1].close > selected[-2].close:
            advancing += 1
    if valid == 0:
        return None
    return advancing / valid


def breadth_history(
    member_bars: Mapping[str, Sequence[Bar]],
    sessions: Iterable[date],
    *,
    window: int = 20,
) -> list[float | None]:
    """Recompute the breadth ratio for each historical session.

    The constituent bars fetched for today already cover the rolling window, so
    the percentile sample costs no extra requests.  Sessions whose coverage is
    below the gate contribute ``None`` instead of a misleading ratio.
    """

    history: list[float | None] = []
    for session in sessions:
        ratio, coverage, _, _ = member_ma20(member_bars, session, window)
        history.append(ratio if coverage >= MIN_BREADTH_COVERAGE else None)
    return history


@dataclass
class Metric:
    rule_id: str
    name: str
    value: float | None
    percentile: float | None
    score: int | None
    status: str
    weight: float
    normalized_weight: float | None = None
    observations: int = 0
    missing_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "name": self.name,
            "value": None if self.value is None else round(self.value, 6),
            "percentile": None if self.percentile is None else round(self.percentile, 6),
            "score": self.score,
            "status": self.status,
            "weight": self.weight,
            "normalizedWeight": None if self.normalized_weight is None else round(self.normalized_weight, 6),
            "observations": self.observations,
            "missingReason": self.missing_reason,
            "raw": self.raw,
            "calibration": "needs-backtest",
        }


def build_metrics(
    *,
    sector: Sequence[Bar],
    benchmark: Sequence[Bar],
    member_bars: Mapping[str, Sequence[Bar]] | None,
    as_of: date,
) -> list[Metric]:
    """Compute all five rules for one industry on one exact date."""

    metrics: list[Metric] = []

    for rule_id, name, window in (
        ("QTS-04-01-01", "relative_strength_5", RELATIVE_STRENGTH_5_WINDOW),
        ("QTS-04-01-02", "relative_strength_20", RELATIVE_STRENGTH_20_WINDOW),
    ):
        current, history = relative_strength(sector, benchmark, window)
        percentile, observations, status = rolling_midrank(current, history)
        weight = dict((rule, item) for rule, _, item in RULE_WEIGHTS)[rule_id]
        metrics.append(
            Metric(
                rule_id=rule_id,
                name=name,
                value=current,
                percentile=percentile,
                score=percentile_score(percentile),
                status=STATUS_INSUFFICIENT if current is None else status,
                weight=weight,
                observations=observations,
                missing_reason=None if current is not None else "excess-return-window-incomplete",
                raw={"window": window, "excessReturn": current},
            )
        )

    current, history = turnover_ratio(sector, TURNOVER_WINDOW)
    percentile, observations, status = rolling_midrank(current, history)
    metrics.append(
        Metric(
            rule_id="QTS-04-01-03",
            name="turnover_ratio",
            value=current,
            percentile=percentile,
            score=percentile_score(percentile),
            status=STATUS_INSUFFICIENT if current is None else status,
            weight=0.20,
            observations=observations,
            missing_reason=None if current is not None else "turnover-window-incomplete-or-zero-mean",
            raw={"window": 20},
        )
    )

    if member_bars is None:
        metrics.append(
            Metric(
                rule_id="QTS-04-01-04",
                name="breadth_ratio",
                value=None,
                percentile=None,
                score=None,
                status=STATUS_INSUFFICIENT,
                weight=0.20,
                observations=0,
                missing_reason="breadth-universe-excluded",
                raw={},
            )
        )
    else:
        breadth, coverage, valid, total = member_ma20(member_bars, as_of)
        prior_sessions = [
            bar.trading_date for bar in sector if bar.trading_date < as_of
        ][-FULL_WINDOW:]
        history = breadth_history(member_bars, prior_sessions)
        percentile, observations, status = rolling_midrank(breadth, history)
        blocked = coverage < MIN_BREADTH_COVERAGE
        metrics.append(
            Metric(
                rule_id="QTS-04-01-04",
                name="breadth_ratio",
                value=breadth,
                percentile=percentile,
                score=None if blocked else percentile_score(percentile),
                status=STATUS_INSUFFICIENT if blocked or breadth is None else status,
                weight=0.20,
                observations=observations,
                missing_reason=(
                    "constituent-coverage-below-70%" if blocked else None if breadth is not None else "breadth-window-incomplete"
                ),
                raw={
                    "coverage": round(coverage, 6),
                    "validMembers": valid,
                    "totalMembers": total,
                    "minCoverage": MIN_BREADTH_COVERAGE,
                },
            )
        )

    value, observations, status, raw = persistence_metric(sector, benchmark)
    metrics.append(
        Metric(
            rule_id="QTS-04-01-05",
            name="persistence",
            value=value,
            percentile=None,
            score=None if status == STATUS_INSUFFICIENT else int(round(value)) if value is not None else None,
            status=status,
            weight=0.20,
            observations=observations,
            missing_reason=None if value is not None else "persistence-window-incomplete",
            raw=raw,
        )
    )
    return metrics


def normalize_weights(metrics: Sequence[Metric]) -> list[Metric]:
    """Re-normalize weights over scored metrics in place and return them."""

    scored = [metric for metric in metrics if metric.score is not None]
    total = sum(metric.weight for metric in scored)
    for metric in metrics:
        if metric.score is None or total <= 0:
            metric.normalized_weight = None
        else:
            metric.normalized_weight = metric.weight / total
    return list(metrics)


def total_score(metrics: Sequence[Metric]) -> float | None:
    """Weighted total over scored metrics; ``None`` when nothing is scored."""

    scored = [metric for metric in metrics if metric.score is not None and metric.normalized_weight is not None]
    if not scored:
        return None
    return sum(metric.score * metric.normalized_weight for metric in scored)  # type: ignore[operator]


def quadrant(
    *,
    turnover_ratio_value: float | None,
    relative_strength_5: float | None,
    advance: float | None,
) -> dict[str, Any]:
    """Four-quadrant split from raw values only.

    The split never depends on percentile availability, so a cold cache still
    yields a classification.
    """

    if advance is None or turnover_ratio_value is None or relative_strength_5 is None:
        return {"label": None, "reason": "raw-inputs-incomplete"}
    strong = turnover_ratio_value >= STRENGTH_TURNOVER_RATIO and relative_strength_5 > 0
    broad = advance >= BROAD_ADVANCE_RATIO
    if strong and broad:
        label = "真实流入"
    elif strong and not broad:
        label = "短线脉冲"
    elif not strong and broad:
        label = "权重拉升"
    else:
        label = "资金撤退"
    return {
        "label": label,
        "strengthHigh": strong,
        "breadthWide": broad,
        "turnoverRatio": round(turnover_ratio_value, 6),
        "relativeStrength5": round(relative_strength_5, 6),
        "advanceRatio": round(advance, 6),
    }


def pool_state(total: float | None, persistence_score: int | None) -> str:
    """Map the weighted total plus persistence onto the documented pools."""

    if total is None:
        return "insufficient"
    if total >= FOCUS_TOTAL_SCORE and (persistence_score or 0) >= FOCUS_PERSISTENCE_SCORE:
        return "focus"
    if total >= WATCH_TOTAL_SCORE:
        return "watch"
    return "excluded"


def confidence_from_metrics(metrics: Sequence[Metric]) -> str:
    """Derive ``high``/``medium``/``low``/``insufficient`` from metric coverage.

    Upstream rule: effective metric coverage of at least 90% allows high
    confidence, 70-89% caps at medium, 50-69% caps at low, below 50% is
    insufficient.  Reduced observation windows additionally cap the result at
    medium so a short history never claims high confidence.
    """

    total = len(metrics)
    if total == 0:
        return STATUS_INSUFFICIENT
    scored = sum(1 for metric in metrics if metric.score is not None)
    coverage = scored / total
    if coverage >= CONFIDENCE_HIGH_COVERAGE:
        level = "high"
    elif coverage >= CONFIDENCE_MEDIUM_COVERAGE:
        level = "medium"
    elif coverage >= CONFIDENCE_LOW_COVERAGE:
        level = "low"
    else:
        return STATUS_INSUFFICIENT
    if level == "high" and any(metric.status == STATUS_REDUCED for metric in metrics):
        level = "medium"
    return level