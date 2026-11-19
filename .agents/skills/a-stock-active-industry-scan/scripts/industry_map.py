"""Industry aggregation for the active-industry scan Skill.

Maps the two rankings' stocks onto THS industry boards and counts hits per
board.  Membership comes from ``hithink-finance index constituents`` and is
cached per day because the board taxonomy changes rarely but the call costs
0.13 s per board.

Two口径 rules drive the shape of this module:

* Hit **count** decides the quadrant; hit **rate** is informational only.
  A 30-member board with 3 hits scores 10% while a 255-member board with 5
  hits scores 2.0%, so ranking on rate would systematically promote small
  boards.
* A missing denominator yields ``None``, never ``0``.  An empty member list
  means "membership unknown", which is not the same as "nobody showed up".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import quadrant

LEVEL_ONE_PREFIX = "881"
LEVEL_TWO_PREFIX = "884"

CACHE_SUBDIR = Path("industry")


@dataclass
class IndustryBoard:
    """One industry board with its member list."""

    thscode: str
    name: str
    level: int
    members: tuple[str, ...] = ()

    @property
    def member_count(self) -> int:
        return len(self.members)


@dataclass
class IndustryHit:
    """Aggregated ranking evidence for one board."""

    thscode: str
    name: str
    level: int
    amount_top_count: int
    turnover_top_count: int
    member_count: int
    quadrant: str
    hit_rate_amount: float | None
    hit_rate_turnover: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.thscode,
            "name": self.name,
            "level": self.level,
            "amountTopCount": self.amount_top_count,
            "turnoverTopCount": self.turnover_top_count,
            "memberCount": self.member_count,
            "hitRateAmount": self.hit_rate_amount,
            "hitRateTurnover": self.hit_rate_turnover,
            "quadrant": self.quadrant,
        }


def build_member_index(
    boards: Iterable[IndustryBoard],
) -> dict[str, list[str]]:
    """Invert membership into ``thscode -> [board codes]``."""

    index: dict[str, list[str]] = {}
    for board in boards:
        for member in board.members:
            index.setdefault(member, []).append(board.thscode)
    return index


def count_hits(
    rows: Sequence[Any],
    member_index: Mapping[str, Sequence[str]],
) -> dict[str, int]:
    """Count how many of ``rows`` belong to each board.

    A stock belongs to exactly one board per level, but a mixed-level board
    list can map one stock to several codes, so every membership is counted.
    """

    counts: dict[str, int] = {}
    for row in rows:
        for code in member_index.get(row.thscode, ()):
            counts[code] = counts.get(code, 0) + 1
    return counts


def aggregate(
    boards: Sequence[IndustryBoard],
    amount_rows: Sequence[Any],
    turnover_rows: Sequence[Any],
    *,
    level: int,
    thresholds: quadrant.QuadrantThresholds | None = None,
) -> list[IndustryHit]:
    """Build per-board hit records for one level.

    Boards with no hits on either ranking are omitted: the output answers
    "which industries are active", not "list every industry".
    """

    limits = thresholds or quadrant.QuadrantThresholds()
    selected = [b for b in boards if b.level == level]
    index = build_member_index(selected)
    amount_counts = count_hits(amount_rows, index)
    turnover_counts = count_hits(turnover_rows, index)

    hits: list[IndustryHit] = []
    for board in selected:
        amount_count = amount_counts.get(board.thscode, 0)
        turnover_count = turnover_counts.get(board.thscode, 0)
        if amount_count == 0 and turnover_count == 0:
            continue
        hits.append(
            IndustryHit(
                thscode=board.thscode,
                name=board.name,
                level=level,
                amount_top_count=amount_count,
                turnover_top_count=turnover_count,
                member_count=board.member_count,
                quadrant=quadrant.classify(
                    quadrant.QuadrantInput(
                        amount_top_count=amount_count,
                        turnover_top_count=turnover_count,
                    ),
                    limits,
                ),
                hit_rate_amount=quadrant.hit_rate(amount_count, board.member_count),
                hit_rate_turnover=quadrant.hit_rate(turnover_count, board.member_count),
            )
        )
    hits.sort(
        key=lambda h: quadrant.rank_key(
            h.amount_top_count, h.turnover_top_count, limits
        )
    )
    return hits


def board_level(thscode: str) -> int:
    """Infer the taxonomy level from a THS board code prefix."""

    if thscode.startswith(LEVEL_TWO_PREFIX):
        return 2
    if thscode.startswith(LEVEL_ONE_PREFIX):
        return 1
    return 1


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def cache_path(root: Path, as_of: date, level: int) -> Path:
    return root / CACHE_SUBDIR / f"level{level}-{as_of.isoformat()}.json"


def save_boards(
    root: Path,
    as_of: date,
    level: int,
    boards: Sequence[IndustryBoard],
) -> Path:
    """Persist one level's membership for one day."""

    target = cache_path(root, as_of, level)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asOf": as_of.isoformat(),
        "level": level,
        "boards": [
            {
                "thscode": b.thscode,
                "name": b.name,
                "level": b.level,
                "members": list(b.members),
            }
            for b in boards
        ],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return target


def load_boards(
    root: Path,
    as_of: date,
    level: int,
) -> tuple[list[IndustryBoard], date] | None:
    """Load cached membership for ``as_of``, else the newest older file.

    Returns ``(boards, effective_date)`` so the caller can report how stale
    the membership is.  ``None`` when no cache exists at all.
    """

    directory = root / CACHE_SUBDIR
    exact = cache_path(root, as_of, level)
    candidates: list[Path] = []
    if exact.is_file():
        candidates = [exact]
    elif directory.is_dir():
        prefix = f"level{level}-"
        older = [
            p
            for p in directory.glob(f"{prefix}*.json")
            if p.name[len(prefix) : -len(".json")] <= as_of.isoformat()
        ]
        candidates = sorted(older, reverse=True)[:1]
    if not candidates:
        return None
    path = candidates[0]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_date = payload.get("asOf")
    try:
        effective = date.fromisoformat(str(raw_date))
    except (TypeError, ValueError):
        effective = as_of
    boards: list[IndustryBoard] = []
    for row in payload.get("boards") or []:
        if not isinstance(row, Mapping):
            continue
        thscode = str(row.get("thscode") or "").strip()
        if not thscode:
            continue
        members = row.get("members")
        boards.append(
            IndustryBoard(
                thscode=thscode,
                name=str(row.get("name") or "").strip(),
                level=int(row.get("level") or level),
                members=tuple(str(m) for m in members) if isinstance(members, list) else (),
            )
        )
    return (boards, effective) if boards else None