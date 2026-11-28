"""Normalize Fuyao trading dates and unadjusted daily stock closes."""

from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

from ....application.ports.trading_pnl import PnlMarketEvidenceError
from ....domain.models.trading_pnl import ValuationEvidence
from .limits_client import MARKET_TIME_ZONE, FuyaoClient, FuyaoContractError, FuyaoError
from .market import FuyaoMarketClient, FuyaoMarketContractError, FuyaoMarketError


HISTORY_PATH = "/api/a-share/prices/historical"


def _midnight_ms(day: date) -> int:
    return int(datetime.combine(day, time.min, MARKET_TIME_ZONE).timestamp()) * 1000


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

    def closes(self, security: str, start: date, end: date) -> list[ValuationEvidence]:
        try:
            data = self.market.request(HISTORY_PATH, params={
                "thscode": security, "start": _midnight_ms(start),
                "end": _midnight_ms(end + timedelta(days=1)) - 1, "adjust": "none",
            }, requested_date=end).data
        except FuyaoMarketContractError as exc:
            raise PnlMarketEvidenceError("fuyao-invalid-history") from exc
        except FuyaoMarketError as exc:
            raise PnlMarketEvidenceError("fuyao-history-unavailable") from exc
        items = data.get("item")
        if (data.get("thscode"), data.get("interval"), data.get("adjust")) != (security, "1d", "none") or not isinstance(items, list):
            raise PnlMarketEvidenceError("fuyao-invalid-history")
        counts: Counter[date] = Counter()
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
                if row.get("thscode", security) != security or row.get("close_price") is None:
                    continue
                values.append(ValuationEvidence(
                    date=day, actual_date=day, security=security, close=row["close_price"],
                    price_kind="original-close", source="Fuyao · 个股不复权日线",
                ))
            except (KeyError, ValueError, OverflowError, OSError):
                continue
        return [value for value in values if counts[value.date] == 1]
