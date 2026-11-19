"""Industry quadrant classification for the active-industry scan Skill.

Pure functions only: no I/O, no clock, no network.  The quadrant answers
"what kind of money is this industry receiving" using nothing but the two
cross-sectional ranking counts, so it stays valid at any intraday instant.

Quartiles are driven by absolute counts, never by lift.  Lift divides by the
industry member count, so a 30-member industry with 3 hits scores the same
lift as a 255-member industry with 25 hits; ranking on it would systematically
promote small industries to the top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

QUADRANT_ACTIVE = "真实活跃"
QUADRANT_WEIGHT = "权重拉升"
QUADRANT_RETAIL = "小盘情绪"
QUADRANT_COLD = "冷门"

ALL_QUADRANTS = (
    QUADRANT_ACTIVE,
    QUADRANT_WEIGHT,
    QUADRANT_RETAIL,
    QUADRANT_COLD,
)

DEFAULT_AMOUNT_THRESHOLD = 2
DEFAULT_TURNOVER_THRESHOLD = 2


@dataclass(frozen=True)
class QuadrantThresholds:
    """Minimum hit counts that count as "present" on each ranking."""

    amount: int = DEFAULT_AMOUNT_THRESHOLD
    turnover: int = DEFAULT_TURNOVER_THRESHOLD

    def __post_init__(self) -> None:
        if self.amount < 1:
            raise ValueError("amount threshold must be at least 1")
        if self.turnover < 1:
            raise ValueError("turnover threshold must be at least 1")


@dataclass(frozen=True)
class QuadrantInput:
    """One industry's cross-sectional evidence."""

    amount_top_count: int
    turnover_top_count: int


def hit_rate(count: int, member_count: int | None) -> float | None:
    """Return ``count / member_count`` or ``None`` when the denominator is unusable.

    A zero or missing member count means the industry has no known membership,
    which is not the same as "0% of its members appeared".  Returning ``None``
    keeps the distinction visible downstream.
    """

    if member_count is None or member_count <= 0:
        return None
    return count / member_count


def classify(evidence: QuadrantInput, thresholds: QuadrantThresholds) -> str:
    """Return the quadrant label for one industry.

    Only the two counts participate.  Neither ``member_count`` nor any
    historical window is consulted, which is what keeps the classification
    valid ahead of settlement.
    """

    amount_hot = evidence.amount_top_count >= thresholds.amount
    turnover_hot = evidence.turnover_top_count >= thresholds.turnover
    if amount_hot and turnover_hot:
        return QUADRANT_ACTIVE
    if amount_hot:
        return QUADRANT_WEIGHT
    if turnover_hot:
        return QUADRANT_RETAIL
    return QUADRANT_COLD


def summarize(
    amount_counts: Mapping[str, int],
    turnover_counts: Mapping[str, int],
    thresholds: QuadrantThresholds,
) -> dict[str, str]:
    """Classify every industry mentioned by either ranking.

    The output covers the union of both mappings so an industry that appears
    only on one ranking is still classified rather than silently dropped.
    """

    codes = set(amount_counts) | set(turnover_counts)
    return {
        code: classify(
            QuadrantInput(
                amount_top_count=amount_counts.get(code, 0),
                turnover_top_count=turnover_counts.get(code, 0),
            ),
            thresholds,
        )
        for code in codes
    }


def rank_key(
    amount_count: int,
    turnover_count: int,
    thresholds: QuadrantThresholds | None = None,
) -> tuple[int, int, int, int]:
    """Sort key that prefers industries present on both rankings.

    The first component is a boolean-ish flag: industries hitting both
    thresholds sort ahead of every one-sided industry, no matter how many raw
    hits the one-sided industry has.  Only then are total presence, amount
    count and turnover count consulted.

    Deliberately not by hit rate: a three-member industry showing one hit
    would otherwise outrank a large industry showing ten.
    """

    limits = thresholds or QuadrantThresholds()
    both = int(
        amount_count >= limits.amount and turnover_count >= limits.turnover
    )
    return (-both, -(amount_count + turnover_count), -amount_count, -turnover_count)