"""Session clock for the active-industry scan Skill.

Answers "what state is the market in right now" and "how much of the session
has elapsed".  Pure except for the injectable ``now``.

The state names follow the repository's existing conventions so a plan or
runbook written for one Skill reads correctly for the other:
``MARKET_ENVIRONMENT_OPEN_TIME`` (default 09:30) and
``MARKET_ENVIRONMENT_SETTLEMENT_TIME`` (default 15:10).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

OPEN_ENV = "MARKET_ENVIRONMENT_OPEN_TIME"
SETTLEMENT_ENV = "MARKET_ENVIRONMENT_SETTLEMENT_TIME"
OPEN_DEFAULT = "09:30"
SETTLEMENT_DEFAULT = "15:10"

LUNCH_START = time(11, 30)
LUNCH_END = time(13, 0)
CLOSE = time(15, 0)

STATE_PREOPEN = "preopen"
STATE_INTRADAY = "intraday"
STATE_LUNCH = "lunch"
STATE_SETTLING = "settling"
STATE_CLOSED = "closed"

# States where a full-session distribution comparison is valid.
SETTLED_STATES = frozenset({STATE_CLOSED})

EARLY_SNAPSHOT_BARS = 3


def _parse_hhmm(raw: str, fallback: str) -> time:
    text = (raw or "").strip() or fallback
    try:
        hour, _, minute = text.partition(":")
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        hour, _, minute = fallback.partition(":")
        return time(int(hour), int(minute))


def open_time() -> time:
    return _parse_hhmm(os.getenv(OPEN_ENV, ""), OPEN_DEFAULT)


def settlement_time() -> time:
    return _parse_hhmm(os.getenv(SETTLEMENT_ENV, ""), SETTLEMENT_DEFAULT)


def _as_shanghai(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(tz=SHANGHAI)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def session_state(moment: datetime | None = None) -> str:
    """Classify the market state at ``moment``.

    Order matters: the settlement window sits after the close, so ``close``
    must be checked before ``settling``, and ``preopen`` before everything.
    """

    current = _as_shanghai(moment)
    clock = current.time()
    if clock < open_time():
        return STATE_PREOPEN
    if clock >= settlement_time():
        return STATE_CLOSED
    if clock >= CLOSE:
        return STATE_SETTLING
    if LUNCH_START <= clock < LUNCH_END:
        return STATE_LUNCH
    return STATE_INTRADAY


def is_settled(state: str) -> bool:
    """Whether a full-session percentile may be computed in this state."""

    return state in SETTLED_STATES


def elapsed_bars(moment: datetime | None = None) -> int:
    """Number of completed five-minute bars in the current session.

    Returns ``0`` before the open.  Lunch does not add bars: the count freezes
    at the 24 bars that end by 11:30 and resumes at 13:05.
    """

    current = _as_shanghai(moment)
    clock = current.time()
    opening = open_time()
    if clock < opening:
        return 0

    def minutes_between(start: time, end: time) -> int:
        start_dt = datetime.combine(current.date(), start)
        end_dt = datetime.combine(current.date(), end)
        return max(0, int((end_dt - start_dt).total_seconds() // 60))

    morning_close = min(clock, LUNCH_START)
    morning_minutes = minutes_between(opening, morning_close)
    bars = morning_minutes // 5

    if clock > LUNCH_END:
        afternoon_close = min(clock, CLOSE)
        afternoon_minutes = minutes_between(LUNCH_END, afternoon_close)
        bars += afternoon_minutes // 5
    return bars


def data_cutoff(moment: datetime | None = None) -> str:
    """The end timestamp of the most recent completed bar, or ``""`` preopen."""

    current = _as_shanghai(moment)
    bars = elapsed_bars(current)
    if bars <= 0:
        return ""
    clock = current.time()
    opening = open_time()
    morning_bars = min(bars, 24)

    start = datetime.combine(current.date(), opening, tzinfo=SHANGHAI)
    cutoff = start + timedelta(minutes=5 * morning_bars)
    if bars > 24:
        afternoon_start = datetime.combine(current.date(), LUNCH_END, tzinfo=SHANGHAI)
        cutoff = afternoon_start + timedelta(minutes=5 * (bars - 24))
    if clock >= settlement_time():
        cutoff = datetime.combine(current.date(), CLOSE, tzinfo=SHANGHAI)
    return cutoff.isoformat(timespec="seconds")


@dataclass(frozen=True)
class SessionReport:
    """Everything the result needs to describe its own timestamp."""

    state: str
    elapsed_bars: int
    data_cutoff: str
    early_snapshot: bool
    settled: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "sessionState": self.state,
            "elapsedBars": self.elapsed_bars,
            "dataCutoff": self.data_cutoff,
            "earlySnapshot": self.early_snapshot,
            "settled": self.settled,
        }


def describe(moment: datetime | None = None) -> SessionReport:
    """Assemble the session block for one run."""

    state = session_state(moment)
    bars = elapsed_bars(moment)
    return SessionReport(
        state=state,
        elapsed_bars=bars,
        data_cutoff=data_cutoff(moment),
        early_snapshot=0 < bars <= EARLY_SNAPSHOT_BARS,
        settled=is_settled(state),
    )


def early_snapshot_warning() -> str:
    """Text attached when the ranking comes from the first few bars."""

    return (
        "开盘早期快照：首根 5 分钟 bar 含集合竞价，占全天成交量中位约 15.9%、"
        "最高可达 47.3%，此时榜单波动剧烈，排名仅供参考。"
    )