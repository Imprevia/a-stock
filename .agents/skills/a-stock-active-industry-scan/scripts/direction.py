"""Direction layer for the active-industry scan Skill.

Pure functions only: no I/O, no clock, no network.  The direction layer is
deliberately orthogonal to the quadrant layer in ``quadrant.py``: a quadrant
answers "how active is this industry", a direction answers "is it going up or
down".  Neither can be derived from the other.

Why the split matters: on 2026-11-20 the semiconductor board fell 6.85% while
the bank board rose 0.22%, and both lands in "真实活跃" because both were
heavily traded.  Activity without direction invites reading a sell-off as
money flowing in.

Two bases are reported, and both are needed:

* absolute — change against the previous close.
* relative — the same change minus the whole-market median, in percentage
  points.  The market median must be an equal-weight per-stock median: the
  benchmark index is capitalisation weighted, and on 2026-11-20 the Shanghai
  Composite fell 1.23% while the median stock fell 5.08%, so an index-based
  benchmark would label 86 of 90 industries as underperforming.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_FLAT = "flat"
DIRECTION_SUSPENDED = "suspended"

ALL_DIRECTIONS = (DIRECTION_UP, DIRECTION_DOWN, DIRECTION_FLAT, DIRECTION_SUSPENDED)

DIRECTION_LABELS = {
    DIRECTION_UP: "上涨",
    DIRECTION_DOWN: "下跌",
    DIRECTION_FLAT: "平盘",
    DIRECTION_SUSPENDED: "停牌",
}

#: A move this small is indistinguishable from flat at two decimal places.
#: Kept as a module constant so the value is visible to callers and docs.
FLAT_EPSILON = 0.005

#: Below this share of members with usable data, breadth is not reported.
MIN_BREADTH_COVERAGE = 0.70

BREADTH_OK = "ok"
BREADTH_INSUFFICIENT = "insufficient"


def classify_direction(
    change_pct: float | None,
    *,
    volume: float | None = None,
) -> str:
    """Classify one stock or board move.

    ``change_pct`` is the percentage move against the previous close.  A
    missing value means the previous close is unknown, which is not the same
    as "unchanged": those rows are ``suspended``, never ``flat``.

    ``volume`` disambiguates a suspended stock that still carries a stale
    ``change_pct`` of 0.0 from a genuinely flat stock, so it is consulted when
    supplied.  A ``None`` change always wins over the volume hint because there
    is no measurement to report either way.
    """

    if change_pct is None:
        return DIRECTION_SUSPENDED
    if volume is not None and volume <= 0:
        return DIRECTION_SUSPENDED
    if change_pct > FLAT_EPSILON:
        return DIRECTION_UP
    if change_pct < -FLAT_EPSILON:
        return DIRECTION_DOWN
    return DIRECTION_FLAT


def direction_label(direction: str) -> str:
    """Chinese label for one direction, for rendering only."""

    return DIRECTION_LABELS.get(direction, DIRECTION_LABELS[DIRECTION_FLAT])


def is_directional(direction: str) -> bool:
    """Whether a direction can take part in up/down grouping.

    Flat and suspended rows are excluded: they carry no direction to group on,
    and padding a group with them would misstate the split.
    """

    return direction in (DIRECTION_UP, DIRECTION_DOWN)


def market_median(changes: Iterable[float | None]) -> float | None:
    """Equal-weight median of per-stock changes.

    ``None`` entries are dropped rather than coerced to 0: a stock with no
    previous close has no change to contribute.  Returns ``None`` when nothing
    usable remains, so callers cannot mistake "no benchmark" for "benchmark of
    zero".
    """

    usable = [float(value) for value in changes if value is not None]
    if not usable:
        return None
    return statistics.median(usable)


def relative_to_market(value: float | None, median: float | None) -> float | None:
    """Excess move over the market median, in percentage points.

    Both inputs are the same unit (percent), so the subtraction is meaningful.
    Either side missing yields ``None``: substituting 0 would silently claim
    "in line with the market".
    """

    if value is None or median is None:
        return None
    return value - median


@dataclass(frozen=True)
class Breadth:
    """Member-level direction counts for one industry or the whole market."""

    up_count: int
    down_count: int
    flat_count: int
    suspended_count: int
    member_count: int
    median_change_pct: float | None
    status: str
    #: Members with no row in the change map at all.  Kept apart from
    #: ``suspended_count``: "we have no measurement for this stock" is a
    #: different statement from "this stock did not trade today".
    unknown_count: int = 0

    @property
    def valid_count(self) -> int:
        """Members with a usable direction (up + down + flat)."""

        return self.up_count + self.down_count + self.flat_count

    @property
    def coverage(self) -> float | None:
        """Usable members over total members, or ``None`` when unknown."""

        if self.member_count <= 0:
            return None
        return self.valid_count / self.member_count

    def as_dict(self) -> dict[str, Any]:
        return {
            "up": self.up_count,
            "down": self.down_count,
            "flat": self.flat_count,
            "suspended": self.suspended_count,
            "unknown": self.unknown_count,
            "memberCount": self.member_count,
            "validCount": self.valid_count,
            "coverage": _round(self.coverage),
            "medianChangePct": _round(self.median_change_pct),
            "status": self.status,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def breadth_status(coverage: float | None) -> str:
    """Whether a coverage ratio is enough to report breadth.

    Uses ``>=`` so exactly 70% still counts as usable; the threshold matches
    QTS-04-01-04 so the two Skills agree on what "enough members" means.
    """

    if coverage is None:
        return BREADTH_INSUFFICIENT
    return BREADTH_OK if coverage >= MIN_BREADTH_COVERAGE else BREADTH_INSUFFICIENT


def aggregate_breadth(
    members: Sequence[str],
    changes: Mapping[str, float | None],
    *,
    volumes: Mapping[str, float | None] | None = None,
    declared_count: int | None = None,
) -> Breadth:
    """Count member directions and compute the median change.

    The denominator is the *declared* member list, not the rows we happen to
    have: a board whose members could not be fetched must show reduced
    coverage, not a falsely complete width.  ``volumes`` lets a suspended
    member be recognised even when its change is a stale zero.

    ``declared_count`` overrides the denominator when the true universe is
    known independently of the rows fetched (the whole-market case, where a
    partially successful pagination must not look complete).
    """

    up = down = flat = suspended = unknown = 0
    usable: list[float] = []
    for code in members:
        if code not in changes:
            unknown += 1
            continue
        change = changes.get(code)
        volume = (volumes or {}).get(code) if volumes else None
        verdict = classify_direction(change, volume=volume)
        if verdict == DIRECTION_UP:
            up += 1
        elif verdict == DIRECTION_DOWN:
            down += 1
        elif verdict == DIRECTION_FLAT:
            flat += 1
        else:
            suspended += 1
            continue
        usable.append(float(change))

    total = declared_count if declared_count is not None else len(members)
    median = statistics.median(usable) if usable else None
    status = breadth_status((len(usable) / total) if total else None)
    if status == BREADTH_INSUFFICIENT:
        # Never publish a width computed from too few members.
        median = None
    return Breadth(
        up_count=up,
        down_count=down,
        flat_count=flat,
        suspended_count=suspended,
        member_count=total,
        median_change_pct=median,
        status=status,
        unknown_count=unknown,
    )


def count_directions(
    codes: Iterable[str],
    changes: Mapping[str, float | None],
    *,
    volumes: Mapping[str, float | None] | None = None,
) -> dict[str, int]:
    """Direction counts over an explicit code list.

    Used for the ranking-hit evidence, where the denominator is the hit set
    rather than a board's membership.  Codes are taken as given; the caller is
    responsible for de-duplicating when a stock appears on both rankings.
    """

    counts = {
        DIRECTION_UP: 0,
        DIRECTION_DOWN: 0,
        DIRECTION_FLAT: 0,
        DIRECTION_SUSPENDED: 0,
    }
    unknown = 0
    total = 0
    for code in codes:
        total += 1
        if code not in changes:
            unknown += 1
            continue
        change = changes.get(code)
        volume = (volumes or {}).get(code) if volumes else None
        counts[classify_direction(change, volume=volume)] += 1
    return {
        "up": counts[DIRECTION_UP],
        "down": counts[DIRECTION_DOWN],
        "flat": counts[DIRECTION_FLAT],
        "suspended": counts[DIRECTION_SUSPENDED],
        "unknown": unknown,
        "total": total,
    }


def majority_direction(counts: Mapping[str, int]) -> str | None:
    """Direction implied by an up/down count, or ``None`` when undecidable.

    A tie is undecidable and yields ``None`` rather than an arbitrary winner:
    picking one would assert a direction the evidence does not support.
    """

    up = int(counts.get("up") or 0)
    down = int(counts.get("down") or 0)
    if up == down:
        return None
    return DIRECTION_UP if up > down else DIRECTION_DOWN


def composite_tag(quadrant_label: str, direction: str | None) -> str:
    """Combine the activity quadrant with the direction.

    The quadrant name is preserved verbatim and the direction is appended, so
    existing readers keep matching on the quadrant substring while new readers
    can tell "真实活跃·上涨" from "真实活跃·下跌".  An unknown direction leaves
    the quadrant alone rather than inventing a suffix.
    """

    if direction in (DIRECTION_UP, DIRECTION_DOWN):
        return f"{quadrant_label}·{DIRECTION_LABELS[direction]}"
    return quadrant_label


def summarize_direction(
    rows: Sequence[Mapping[str, Any]],
    *,
    direction_key: str = "direction",
    amount_key: str = "amountYi",
) -> dict[str, Any]:
    """Up/down/flat counts and the up-side amount share for one ranking.

    ``upAmountShare`` answers "was the big money buying strength or selling
    weakness" without inventing a score: it is the share of the ranking's
    turnover that sits in rising stocks.  It is ``None`` when the ranking has
    no turnover to divide by.
    """

    up = down = flat = suspended = 0
    total_amount = 0.0
    up_amount = 0.0
    for row in rows:
        verdict = row.get(direction_key)
        if verdict == DIRECTION_UP:
            up += 1
        elif verdict == DIRECTION_DOWN:
            down += 1
        elif verdict == DIRECTION_FLAT:
            flat += 1
        else:
            suspended += 1
        amount = row.get(amount_key)
        if isinstance(amount, (int, float)):
            total_amount += float(amount)
            if verdict == DIRECTION_UP:
                up_amount += float(amount)

    return {
        "up": up,
        "down": down,
        "flat": flat,
        "suspended": suspended,
        "total": len(rows),
        "upAmountShare": _round(up_amount / total_amount) if total_amount else None,
    }


def group_by_direction(
    items: Sequence[Mapping[str, Any]],
    *,
    direction_key: str = "direction",
    limit: int | None = None,
    order_by_relative: bool = False,
) -> dict[str, list[Mapping[str, Any]]]:
    """Split items into rising and falling groups.

    Only up and down participate; flat and suspended items have no direction to
    group on.  ``limit`` caps each group without relaxing any threshold, so an
    empty group stays empty rather than being padded.

    With ``order_by_relative`` each group is sorted by relative excess
    descending, with unmeasurable entries last — a group listed strongest-first
    is what a reader expects, and pushing ``None`` to the end keeps an unknown
    value from sorting as if it were the largest.
    """

    groups: dict[str, list[Mapping[str, Any]]] = {DIRECTION_UP: [], DIRECTION_DOWN: []}
    for item in items:
        verdict = item.get(direction_key)
        if verdict in groups:
            groups[verdict].append(item)

    if order_by_relative:
        def key(entry: Mapping[str, Any]) -> tuple[int, float]:
            value = entry.get("relativeToMarketPct")
            if value is None:
                return (1, 0.0)
            return (0, -float(value))

        groups = {name: sorted(members, key=key) for name, members in groups.items()}

    if limit is not None:
        return {key_name: value[:limit] for key_name, value in groups.items()}
    return groups
