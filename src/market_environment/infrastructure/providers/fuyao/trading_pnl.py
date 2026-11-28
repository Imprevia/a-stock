"""Normalize Fuyao trading dates, unadjusted closes and corporate actions."""

import logging
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from ....application.ports.trading_pnl import (
    PnlCorporateAction,
    PnlCorporateActions,
    PnlHistory,
    PnlMarketEvidenceError,
)
from ....domain.models.trading_pnl import ValuationEvidence
from .limits_client import MARKET_TIME_ZONE, FuyaoClient, FuyaoContractError, FuyaoError
from .market import (
    FuyaoMarketClient,
    FuyaoMarketConfigurationError,
    FuyaoMarketContractError,
    FuyaoMarketDiagnostic,
    FuyaoMarketError,
    FuyaoMarketPermissionError,
    FuyaoMarketRateLimitError,
    FuyaoMarketTransportError,
)


HISTORY_PATH = "/api/a-share/prices/historical"
logger = logging.getLogger(__name__)


def _midnight_ms(day: date) -> int:
    return int(datetime.combine(day, time.min, MARKET_TIME_ZONE).timestamp()) * 1000


def _echo_conflicts(data: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
    return any(key in data and data[key] != value for key, value in expected.items())


def _history_failure(exc: FuyaoMarketError) -> str:
    diagnostic = exc.diagnostic or FuyaoMarketDiagnostic()
    if isinstance(exc, FuyaoMarketContractError):
        return "fuyao-invalid-history"
    if (isinstance(exc, (FuyaoMarketConfigurationError, FuyaoMarketPermissionError))
            or diagnostic.business_code in {2001, 2003}):
        return "fuyao-history-permission"
    if (isinstance(exc, FuyaoMarketRateLimitError) or diagnostic.business_code == 4001
            or diagnostic.http_status == 429):
        return "fuyao-history-rate-limited"
    if isinstance(exc, FuyaoMarketTransportError):
        status = diagnostic.http_status
        if status is None or status == 408 or not 400 <= status < 500:
            return "fuyao-history-unavailable"
    return "fuyao-history-rejected"


def _log_history_failure(
    security: str, start: date, end: date, reason: str, diagnostic: FuyaoMarketDiagnostic | None
) -> None:
    diagnostic = diagnostic or FuyaoMarketDiagnostic()
    logger.warning(
        "Fuyao ledger history failed security=%s start=%s end=%s reason=%s "
        "http_status=%s business_code=%s request_id_digest=%s",
        security, start, end, reason, diagnostic.http_status, diagnostic.business_code, diagnostic.request_id_digest,
    )


class FuyaoPnlMarketEvidence:
    def __init__(self, calendar: FuyaoClient, market: FuyaoMarketClient) -> None:
        self.calendar = calendar
        self.market = market

    def trading_days(self) -> tuple[date, ...]:
        try:
            days = self.calendar.fetch_trading_days()
            if any(day.weekday() >= 5 for day in days):
                raise FuyaoContractError("calendar contains a weekend trading session")
            return days
        except FuyaoContractError as exc:
            raise PnlMarketEvidenceError("fuyao-invalid-calendar") from exc
        except FuyaoError as exc:
            raise PnlMarketEvidenceError("fuyao-calendar-unavailable") from exc

    def closes(self, security: str, start: date, end: date) -> PnlHistory:
        expected = {"thscode": security, "interval": "1d", "adjust": "none"}
        try:
            response = self.market.request(HISTORY_PATH, params={
                **expected, "start": _midnight_ms(start),
                "end": _midnight_ms(end + timedelta(days=1)) - 1,
            }, requested_date=end)
        except FuyaoMarketError as exc:
            reason = _history_failure(exc)
            _log_history_failure(security, start, end, reason, exc.diagnostic)
            raise PnlMarketEvidenceError(reason) from exc
        data = response.data
        items = data.get("item")
        if not isinstance(items, list) or _echo_conflicts(data, expected):
            _log_history_failure(security, start, end, "fuyao-invalid-history", response.diagnostic)
            raise PnlMarketEvidenceError("fuyao-invalid-history")
        counts: Counter[date] = Counter()
        invalid_dates: set[date] = set()
        values = []
        for row in items:
            if not isinstance(row, Mapping):
                continue
            try:
                timestamp = row["date_ms"]
                if isinstance(timestamp, bool) or not str(timestamp).isdigit():
                    continue
                day = datetime.fromtimestamp(int(timestamp) / 1000, MARKET_TIME_ZONE).date()
                if not start <= day <= end:
                    continue
                counts[day] += 1
                if _echo_conflicts(row, expected):
                    invalid_dates.add(day)
                    continue
                if row.get("close_price") is None:
                    continue
                values.append(ValuationEvidence(
                    date=day, actual_date=day, security=security, close=row["close_price"],
                    price_kind="original-close", source="Fuyao · 个股不复权日线",
                ))
            except (KeyError, ValueError, OverflowError, OSError):
                continue
        if invalid_dates:
            _log_history_failure(security, start, end, "fuyao-invalid-history", response.diagnostic)
        return PnlHistory(tuple(value for value in values if counts[value.date] == 1), frozenset(invalid_dates))

    def corporate_actions(self, security: str, start: date, end: date) -> PnlCorporateActions:
        path = "/api/a-share/corporate-actions/adjustment-factors"
        try:
            response = self.market.request(path, params={
                "thscode": security, "from": start.isoformat(), "to": end.isoformat(),
            }, requested_date=end)
        except FuyaoMarketError as exc:
            reason = _history_failure(exc).replace("history", "actions")
            raise PnlMarketEvidenceError(reason) from exc

        data = response.data
        ticker = security.partition(".")[0]
        items = data.get("item")
        if data.get("thscode") != security or data.get("ticker") != ticker or not isinstance(items, list):
            raise PnlMarketEvidenceError("fuyao-invalid-actions")

        events: dict[date, PnlCorporateAction] = {}
        conflicts: set[date] = set()
        for row in items:
            try:
                event = _corporate_action(row, ticker, start, end)
            except (KeyError, ValueError, OverflowError, OSError, InvalidOperation) as exc:
                raise PnlMarketEvidenceError("fuyao-invalid-actions") from exc
            existing = events.setdefault(event.date, event)
            if existing != event:
                conflicts.add(event.date)
        return PnlCorporateActions(
            security, start, end, "Fuyao · 个股除复权事件",
            tuple(events[day] for day in sorted(events.keys() - conflicts)), frozenset(conflicts),
        )


def _corporate_action(row: Any, ticker: str, start: date, end: date) -> PnlCorporateAction:
    if not isinstance(row, Mapping) or row.get("ticker") != ticker:
        raise ValueError("invalid corporate action identity")
    timestamp = row["ex_date_ms"]
    if type(timestamp) is not int:
        raise ValueError("invalid corporate action timestamp")
    day = datetime.fromtimestamp(timestamp / 1000, MARKET_TIME_ZONE).date()
    if timestamp != _midnight_ms(day) or not start <= day <= end:
        raise ValueError("invalid corporate action date")
    dividend = _per_share_number(row["dividend_per_share"])
    bonus = _per_share_number(row["per_share_bonus"])
    return PnlCorporateAction(day, dividend, bonus)


def _per_share_number(value: Any) -> Decimal:
    if type(value) not in {int, float, Decimal}:
        raise ValueError("invalid corporate action amount")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("invalid corporate action amount")
    return result
