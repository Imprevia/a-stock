"""Shared data model for the QTS-04 skills.

``Bar`` is the single normalized daily bar used by every step.  Keeping it in
the shared core means the cache, the client and each step's scoring accept the
same object instead of three structurally identical copies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def to_number(value: Any) -> float | None:
    """Return a finite float or ``None``; never coerce blanks to zero."""

    if value is None or value == "" or value == "-":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class Bar:
    trading_date: date
    close: float
    turnover: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Bar | None":
        raw_date = payload.get("date_ms")
        close = to_number(payload.get("close_price"))
        if raw_date is None or close is None:
            return None
        try:
            millis = int(float(raw_date))
        except (TypeError, ValueError):
            return None
        trading_date = datetime.fromtimestamp(millis / 1000, tz=SHANGHAI).date()
        return cls(
            trading_date=trading_date,
            close=close,
            turnover=to_number(payload.get("turnover")),
            open=to_number(payload.get("open_price")),
            high=to_number(payload.get("high_price")),
            low=to_number(payload.get("low_price")),
        )


def normalize_bars(rows: Iterable[Mapping[str, Any]]) -> list[Bar]:
    """Normalize raw fuyao bar rows into sorted, de-duplicated bars."""

    by_date: dict[date, Bar] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        bar = Bar.from_payload(row)
        if bar is not None:
            by_date[bar.trading_date] = bar
    return [by_date[key] for key in sorted(by_date)]


def slice_until(bars: Iterable[Bar], as_of: date) -> list[Bar]:
    """Keep bars up to and including ``as_of``; never borrow another date."""

    return [bar for bar in bars if bar.trading_date <= as_of]


def has_session(bars: Iterable[Bar], as_of: date) -> bool:
    return any(bar.trading_date == as_of for bar in bars)
