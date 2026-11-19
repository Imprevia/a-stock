"""Turnover percentile helpers for the active-industry scan Skill.

Pure functions only: no I/O, no clock, no network.

The percentile answers "is this stock's turnover unusual *for this stock*".
Two口径 notes matter here:

1.  A percentile of turnover equals a percentile of volume whenever the float
    share count is constant across the window, because
    ``turnover = volume / float_shares`` is a monotone linear map.  The window
    is therefore evaluated on raw volumes, which keeps the calculation valid
    even though only the *current* float share count is known.

2.  A partial session is not comparable to a full-session distribution.  At
    10:30 the cumulative volume is roughly 38%–64% of a full day, varying by
    stock, so dividing by a historical full-day average and re-ranking would
    manufacture a number that looks like a percentile but is not one.  Callers
    must not request a percentile before settlement; this module reports
    ``insufficient`` rather than scaling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient"

DEFAULT_MIN_BARS = 60
DEFAULT_AVG_WINDOW = 20


@dataclass(frozen=True)
class PercentileResult:
    """One stock's relative-turnover evidence."""

    status: str
    window_bars: int
    average_turnover: float | None
    amplification: float | None
    percentile: float | None

    @property
    def usable(self) -> bool:
        return self.status == STATUS_OK


def _is_usable(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def average(series: Sequence[float], window: int) -> float | None:
    """Mean of the trailing ``window`` observations, excluding the latest one.

    The latest observation is the value under test, so including it would let
    a single spike inflate its own baseline.
    """

    if window < 1:
        raise ValueError("window must be at least 1")
    usable = [float(v) for v in series if _is_usable(v)]
    if len(usable) < 2:
        return None
    history = usable[-(window + 1) : -1]
    if not history:
        return None
    return sum(history) / len(history)


def percentile_rank(series: Sequence[float], value: float | None = None) -> float | None:
    """Fraction of the window at or below ``value``, inclusive.

    Uses the empirical CDF so a value equal to the window maximum scores 1.0.
    Returns ``None`` when the window is empty or ``value`` is unusable.
    """

    usable = [float(v) for v in series if _is_usable(v)]
    if not usable:
        return None
    target = usable[-1] if value is None else value
    if not _is_usable(target):
        return None
    at_or_below = sum(1 for v in usable if v <= float(target))
    return at_or_below / len(usable)


def evaluate(
    series: Sequence[float],
    *,
    min_bars: int = DEFAULT_MIN_BARS,
    avg_window: int = DEFAULT_AVG_WINDOW,
) -> PercentileResult:
    """Compute the relative-turnover block for one stock.

    ``series`` is the chronological window of turnover values (or volumes — see
    the module docstring for why either works).  The final element is today's
    value under test.

    ``average_turnover`` is expressed in the **same unit as the input series**.
    Callers that pass volumes receive a share count, not a percentage, and must
    label it accordingly; ``amplification`` is a ratio and stays unit-free.

    Bars below ``min_bars`` yield ``insufficient`` with ``None`` fields; they
    are never filled with a short-window percentile, because a three-bar
    "history" would report every new listing as an all-time extreme.
    """

    usable = [float(v) for v in series if _is_usable(v)]
    bar_count = len(usable)
    if bar_count < min_bars or bar_count < 2:
        return PercentileResult(
            status=STATUS_INSUFFICIENT,
            window_bars=bar_count,
            average_turnover=None,
            amplification=None,
            percentile=None,
        )

    baseline = average(usable, avg_window)
    current = usable[-1]
    amplification = current / baseline if baseline else None
    return PercentileResult(
        status=STATUS_OK,
        window_bars=bar_count,
        average_turnover=baseline,
        amplification=amplification,
        percentile=percentile_rank(usable, current),
    )


def deferred(reason: str, available_after: str) -> dict[str, str]:
    """Describe a percentile that is deliberately withheld.

    Callers use this while the session is open.  Having a named helper keeps
    the "we chose not to compute this" case distinct from "the computation
    failed", and makes it harder to slip a scaled estimate in later.
    """

    return {
        "status": "deferred",
        "reason": reason,
        "availableAfter": available_after,
    }