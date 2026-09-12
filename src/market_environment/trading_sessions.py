"""Evidence-backed trading-session resolution for cross-day calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol


ResolutionStatus = Literal["ok", "insufficient"]


@dataclass(frozen=True)
class DateEvidenceValidation:
    requested_as_of: date
    actual_as_of: date | None
    valid: bool
    reason: str | None = None

    @property
    def status(self) -> ResolutionStatus:
        return "ok" if self.valid else "insufficient"


@dataclass(frozen=True)
class TradingDayResolution:
    requested_as_of: date
    actual_as_of: date | None
    previous_as_of: date | None
    status: ResolutionStatus
    reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def sufficient(self) -> bool:
        return self.status == "ok"


class SessionStore(Protocol):
    def get_trading_session(self, as_of: date) -> Any | None: ...


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.isoformat() == str(value) else None


def validate_actual_session_date(
    requested_as_of: date,
    actual_as_of: date | str | None,
) -> DateEvidenceValidation:
    """Validate an explicit provider/session date without guessing a date."""

    actual = _coerce_date(actual_as_of)
    if actual is None:
        return DateEvidenceValidation(requested_as_of, None, False, "missing-or-invalid-actual-session-date")
    if actual != requested_as_of:
        return DateEvidenceValidation(requested_as_of, actual, False, "provider-date-mismatch")
    return DateEvidenceValidation(requested_as_of, actual, True)


validate_requested_actual_date = validate_actual_session_date


class TradingDayResolver:
    """Resolve only the exact previous session recorded by session evidence.

    The resolver never subtracts a calendar day and never searches older rows.
    A missing/invalid pointer is therefore an explicit ``insufficient`` result.
    """

    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def resolve(
        self,
        requested_as_of: date,
        *,
        actual_as_of: date | str | None = None,
        require_previous: bool = True,
    ) -> TradingDayResolution:
        if requested_as_of.weekday() >= 5:
            return TradingDayResolution(
                requested_as_of,
                None,
                None,
                "insufficient",
                "requested-date-is-weekend",
            )

        supplied_validation = None
        if actual_as_of is not None:
            supplied_validation = validate_actual_session_date(requested_as_of, actual_as_of)
            if not supplied_validation.valid:
                return TradingDayResolution(
                    requested_as_of,
                    supplied_validation.actual_as_of,
                    None,
                    "insufficient",
                    supplied_validation.reason,
                )

        current = self.store.get_trading_session(requested_as_of)
        if current is None:
            return TradingDayResolution(
                requested_as_of,
                supplied_validation.actual_as_of if supplied_validation else None,
                None,
                "insufficient",
                "missing-session-evidence",
            )
        if not bool(getattr(current, "is_session", False)):
            return TradingDayResolution(
                requested_as_of,
                _coerce_date(getattr(current, "actual_as_of", None)),
                None,
                "insufficient",
                "requested-date-is-not-trading-session",
            )

        recorded_actual = _coerce_date(getattr(current, "actual_as_of", None))
        validation = validate_actual_session_date(requested_as_of, recorded_actual)
        if not validation.valid:
            return TradingDayResolution(
                requested_as_of,
                validation.actual_as_of,
                None,
                "insufficient",
                validation.reason,
            )
        if not require_previous:
            return TradingDayResolution(requested_as_of, recorded_actual, None, "ok")

        previous_as_of = _coerce_date(getattr(current, "previous_as_of", None))
        if previous_as_of is None:
            return TradingDayResolution(
                requested_as_of,
                recorded_actual,
                None,
                "insufficient",
                "missing-previous-session",
            )
        if previous_as_of >= requested_as_of:
            return TradingDayResolution(
                requested_as_of,
                recorded_actual,
                previous_as_of,
                "insufficient",
                "invalid-previous-session-order",
            )
        previous = self.store.get_trading_session(previous_as_of)
        if previous is None or not bool(getattr(previous, "is_session", False)):
            return TradingDayResolution(
                requested_as_of,
                recorded_actual,
                previous_as_of,
                "insufficient",
                "previous-session-unavailable",
            )
        previous_actual = _coerce_date(getattr(previous, "actual_as_of", None))
        previous_validation = validate_actual_session_date(previous_as_of, previous_actual)
        if not previous_validation.valid:
            return TradingDayResolution(
                requested_as_of,
                recorded_actual,
                previous_as_of,
                "insufficient",
                "previous-session-date-mismatch",
            )
        return TradingDayResolution(requested_as_of, recorded_actual, previous_as_of, "ok")


def resolve_previous_trading_day(store: SessionStore, requested_as_of: date) -> TradingDayResolution:
    return TradingDayResolver(store).resolve(requested_as_of)


__all__ = [
    "DateEvidenceValidation",
    "TradingDayResolution",
    "TradingDayResolver",
    "validate_actual_session_date",
    "validate_requested_actual_date",
    "resolve_previous_trading_day",
]
