"""Structured confirmation / invalidation predicates for QTS-04 STEP 1.

The prose in ``text`` is rendered from the very same numbers that go into the
``all`` clause list, so the two can never drift apart.  ``evaluate`` is a pure
three-valued function over later sessions: ``met`` / ``unmet`` / ``unknown``.

Conventions
-----------
``horizonDays`` counts trading sessions *after* the reference date.  Callers
pass only the sessions that follow the report date, ascending; ``horizonDays``
selects which of them is evaluated (1 = the next session).

Fields are limited to ``close`` / ``turnover`` / ``pctChange``; operators to
``>=`` / ``>`` / ``<=`` / ``<``.  A flat "all" list is enough because every
current condition is a conjunction; disjunction or grouping would require a
new schema version.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

CONFIRMATION_HORIZON_DAYS = 1
INVALIDATION_HORIZON_DAYS = 1

CONFIRMATION_CLOSE_MULTIPLIER = 1.005
CONFIRMATION_TURNOVER_MULTIPLIER = 1.0
INVALIDATION_CLOSE_MULTIPLIER = 0.97
INVALIDATION_TURNOVER_MULTIPLIER = 0.8

OPS = (">=", ">", "<=", "<")
FIELDS = ("close", "turnover", "pctChange")

RESULT_MET = "met"
RESULT_UNMET = "unmet"
RESULT_UNKNOWN = "unknown"


def _to_float(value: Any) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _close_threshold(reference_close: float, multiplier: float) -> float:
    """Round to the two decimals the prose renders, so text and value match."""

    return round(float(reference_close) * multiplier + 1e-12, 2)


def _turnover_threshold(turnover_mean: float, multiplier: float) -> float:
    """Round to the whole unit the prose renders."""

    return float(round(float(turnover_mean) * multiplier))


def _pct_basis(multiplier: float) -> str:
    """Render the multiplier delta the way the prose reads (``+0.5%``, ``-3%``)."""

    change = round((float(multiplier) - 1.0) * 100.0, 6)
    text = f"{change:+.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def build_confirmation(close: Any, turnover_mean: Any = None) -> dict[str, Any] | None:
    """Build the next-session confirmation predicate, or ``None`` without close."""

    reference = _to_float(close)
    if reference is None:
        return None
    close_level = _close_threshold(reference, CONFIRMATION_CLOSE_MULTIPLIER)
    clauses: list[dict[str, Any]] = [
        {
            "field": "close",
            "op": ">=",
            "value": close_level,
            "basis": f"referenceClose*{CONFIRMATION_CLOSE_MULTIPLIER}",
        }
    ]
    text = f"次日收盘不低于 {close_level:.2f}（当日收盘 {reference:.2f} 的 {_pct_basis(CONFIRMATION_CLOSE_MULTIPLIER)}）"
    mean = _to_float(turnover_mean)
    if mean is not None and mean > 0:
        turnover_level = _turnover_threshold(mean, CONFIRMATION_TURNOVER_MULTIPLIER)
        clauses.append(
            {
                "field": "turnover",
                "op": ">=",
                "value": turnover_level,
                "basis": f"mean(turnover,20)*{CONFIRMATION_TURNOVER_MULTIPLIER}",
            }
        )
        text += f" 且成交额不低于 {turnover_level:.0f}（20 日均额）"
    return {"text": text, "horizonDays": CONFIRMATION_HORIZON_DAYS, "all": clauses}


def build_invalidation(close: Any, turnover_mean: Any = None) -> dict[str, Any] | None:
    """Build the next-session invalidation predicate, or ``None`` without close."""

    reference = _to_float(close)
    if reference is None:
        return None
    close_level = _close_threshold(reference, INVALIDATION_CLOSE_MULTIPLIER)
    clauses: list[dict[str, Any]] = [
        {
            "field": "close",
            "op": "<",
            "value": close_level,
            "basis": f"referenceClose*{INVALIDATION_CLOSE_MULTIPLIER}",
        }
    ]
    text = f"次日收盘低于 {close_level:.2f}（当日收盘的 {_pct_basis(INVALIDATION_CLOSE_MULTIPLIER)}）"
    mean = _to_float(turnover_mean)
    if mean is not None and mean > 0:
        turnover_level = _turnover_threshold(mean, INVALIDATION_TURNOVER_MULTIPLIER)
        clauses.append(
            {
                "field": "turnover",
                "op": "<",
                "value": turnover_level,
                "basis": f"mean(turnover,20)*{INVALIDATION_TURNOVER_MULTIPLIER}",
            }
        )
        text += f" 或成交额低于 {turnover_level:.0f}（20 日均额×{INVALIDATION_TURNOVER_MULTIPLIER}）"
    return {"text": text, "horizonDays": INVALIDATION_HORIZON_DAYS, "all": clauses}


def _row_of(item: Any) -> tuple[date | None, float | None, float | None]:
    if isinstance(item, Mapping):
        trading_date = item.get("trading_date") or item.get("date") or item.get("asOf")
        close = item.get("close", item.get("close_price"))
        turnover = item.get("turnover")
    else:
        trading_date = getattr(item, "trading_date", None)
        close = getattr(item, "close", None)
        turnover = getattr(item, "turnover", None)
    return _to_date(trading_date), _to_float(close), _to_float(turnover)


def normalize_bars(bars: Iterable[Any] | None) -> list[tuple[date | None, float | None, float | None]]:
    """Coerce dataclasses or mappings into ``(date, close, turnover)`` rows."""

    rows = [_row_of(item) for item in bars or ()]
    dated = [row for row in rows if row[0] is not None]
    undated = [row for row in rows if row[0] is None]
    dated.sort(key=lambda row: row[0])  # type: ignore[arg-type,return-value]
    return dated + undated


def _compare(actual: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return actual >= threshold
    if op == ">":
        return actual > threshold
    if op == "<=":
        return actual <= threshold
    if op == "<":
        return actual < threshold
    raise ValueError(f"unsupported operator: {op}")


def _value_of(
    field: str,
    target: tuple[date | None, float | None, float | None],
    previous: tuple[date | None, float | None, float | None] | None,
) -> float | None:
    _date_value, close, turnover = target
    if field == "close":
        return close
    if field == "turnover":
        return turnover
    if field == "pctChange":
        if close is None or previous is None or previous[1] in (None, 0):
            return None
        return close / previous[1] - 1.0  # type: ignore[operator]
    return None


def evaluate(predicate: Mapping[str, Any] | None, bars: Sequence[Any] | None) -> str:
    """Return ``met`` / ``unmet`` / ``unknown`` for one predicate.

    Missing sessions or missing fields yield ``unknown``; this function never
    raises on absent data and never guesses.
    """

    if not isinstance(predicate, Mapping):
        return RESULT_UNKNOWN
    clauses = [clause for clause in predicate.get("all") or [] if isinstance(clause, Mapping)]
    if not clauses:
        return RESULT_UNKNOWN
    horizon_raw = _to_float(predicate.get("horizonDays"))
    horizon = int(horizon_raw) if horizon_raw is not None else 1
    if horizon < 1:
        return RESULT_UNKNOWN
    rows = normalize_bars(bars)
    if len(rows) < horizon:
        return RESULT_UNKNOWN
    target = rows[horizon - 1]
    previous = rows[horizon - 2] if horizon >= 2 else None

    states: list[str] = []
    for clause in clauses:
        field = str(clause.get("field") or "")
        op = str(clause.get("op") or "")
        threshold = _to_float(clause.get("value"))
        if field not in FIELDS or op not in OPS or threshold is None:
            states.append(RESULT_UNKNOWN)
            continue
        actual = _value_of(field, target, previous)
        if actual is None:
            states.append(RESULT_UNKNOWN)
            continue
        states.append(RESULT_MET if _compare(actual, op, threshold) else RESULT_UNMET)

    # Three-valued AND: a definite failure dominates an unknown clause.
    if RESULT_UNMET in states:
        return RESULT_UNMET
    if RESULT_UNKNOWN in states:
        return RESULT_UNKNOWN
    return RESULT_MET