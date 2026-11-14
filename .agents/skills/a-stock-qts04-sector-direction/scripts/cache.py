"""Rebuildable local bar cache for the QTS-04 sector pipeline.

The cache is a plain JSON directory.  It is never written to PostgreSQL and
never committed: deleting it only costs refetch time, never correctness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from scoring import Bar

SHANGHAI = ZoneInfo("Asia/Shanghai")

KIND_INDUSTRY = "industry"
KIND_STOCK = "stock"

CACHE_STATE_COLD = "cold"
CACHE_STATE_PARTIAL = "partial"
CACHE_STATE_WARM = "warm"


def default_cache_dir() -> Path:
    return Path(__file__).resolve().parent.parent / ".cache" / "qts04"


def _bar_to_payload(bar: Bar) -> dict[str, Any]:
    return {
        "date": bar.trading_date.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "turnover": bar.turnover,
    }


def _bar_from_payload(payload: dict[str, Any]) -> Bar | None:
    raw_date = payload.get("date")
    close = payload.get("close")
    if not isinstance(raw_date, str) or close is None:
        return None
    try:
        trading_date = date.fromisoformat(raw_date)
        close_value = float(close)
    except (TypeError, ValueError):
        return None
    def as_float(key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return Bar(
        trading_date=trading_date,
        close=close_value,
        turnover=as_float("turnover"),
        open=as_float("open"),
        high=as_float("high"),
        low=as_float("low"),
    )


@dataclass
class BarCache:
    """JSON-backed bar store keyed by ``kind`` and ``thscode``."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def _path(self, kind: str, thscode: str) -> Path:
        safe = thscode.replace("/", "_").replace("\\", "_")
        return self.root / kind / f"{safe}.json"

    def load(self, kind: str, thscode: str) -> list[Bar]:
        path = self._path(kind, thscode)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        bars = [bar for row in rows if isinstance(row, dict) and (bar := _bar_from_payload(row)) is not None]
        bars.sort(key=lambda item: item.trading_date)
        return bars

    def save(self, kind: str, thscode: str, bars: Sequence[Bar], *, fetched_at: datetime | None = None) -> Path:
        path = self._path(kind, thscode)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged: dict[date, Bar] = {bar.trading_date: bar for bar in self.load(kind, thscode)}
        for bar in bars:
            merged[bar.trading_date] = bar
        payload = {
            "thscode": thscode,
            "kind": kind,
            "fetchedAt": (fetched_at or datetime.now(SHANGHAI)).isoformat(),
            "bars": [_bar_to_payload(merged[key]) for key in sorted(merged)],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def covers(self, kind: str, thscode: str, as_of: date) -> bool:
        return any(bar.trading_date == as_of for bar in self.load(kind, thscode))

    def cache_state(self, kind: str, codes: Iterable[str], as_of: date) -> str:
        codes = list(codes)
        if not codes:
            return CACHE_STATE_COLD
        hits = sum(1 for code in codes if self.covers(kind, code, as_of))
        if hits == 0:
            return CACHE_STATE_COLD
        if hits == len(codes):
            return CACHE_STATE_WARM
        return CACHE_STATE_PARTIAL

    def missing_window(
        self, kind: str, thscode: str, start: date, end: date
    ) -> tuple[date, date] | None:
        """Return the uncovered ``(start, end)`` slice, or ``None`` if covered.

        The cache stores a contiguous daily series, so an existing row on
        ``start`` and ``end`` with no interior gap counts as covered.
        """

        bars = [bar for bar in self.load(kind, thscode) if start <= bar.trading_date <= end]
        if not bars:
            return (start, end)
        first = bars[0].trading_date
        last = bars[-1].trading_date
        if first <= start and last >= end:
            return None
        new_start = start if first > start else last
        new_end = end if last < end else first
        if new_start > new_end:
            return None
        return (new_start, new_end)

    def coverage_window(self, kind: str, thscode: str) -> tuple[date, date] | None:
        bars = self.load(kind, thscode)
        if not bars:
            return None
        return (bars[0].trading_date, bars[-1].trading_date)


def is_ignored_by_git(path: Path, cwd: Path | None = None) -> bool:
    """Best-effort check used by tests to prove the cache stays untracked."""

    import subprocess

    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(cwd or path.parent),
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0