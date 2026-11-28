"""Provider-free month and date queries for the personal ledger."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Mapping

from ...domain.analysis.trading_pnl import ZERO, money, value_positions
from ...trading_sessions import TradingDayResolver, validate_actual_session_date
from ..ports.trading_pnl import TradingPnlRepository, TradingPnlStore


class LocalSessions:
    def __init__(self, sessions: Mapping) -> None:
        self.sessions = sessions

    def get_trading_session(self, as_of: date):
        return self.sessions.get(as_of)

    def resolution(self, as_of: date):
        return TradingDayResolver(self).resolve(as_of)

    def closed(self, as_of: date) -> bool:
        if as_of.weekday() >= 5:
            return True
        known = self.sessions.get(as_of)
        if known is not None:
            return not known.is_session and validate_actual_session_date(as_of, known.actual_as_of).valid
        return any(
            session.previous_as_of is not None and session.previous_as_of < as_of < day
            and self.resolution(day).sufficient
            for day, session in self.sessions.items()
        )


def day_range(start: date, end: date):
    for step in range((end - start).days + 1):
        yield start + timedelta(days=step)


class TradingPnlQueries:
    def __init__(self, store: TradingPnlStore, today: Callable[[], date]) -> None:
        self.store = store
        self.today = today

    def month(self, year: int, month: int) -> dict:
        start = date(year, month, 1)
        end = start.replace(day=monthrange(year, month)[1])
        with self.store() as repo:
            state = repo.state()
            calendar = LocalSessions(repo.sessions(start - timedelta(days=32), end + timedelta(days=32)))
            rows = {row["as_of"]: row["data"] for row in repo.days(start, end)}
            prices = self._prices(repo, rows, start, end)
            days = []
            for day in day_range(start, end):
                result = self._value(day, state, calendar, rows.get(day), prices)
                days.append({key: result[key] for key in ("date", "status", "pnl", "issues")})
            return {"month": start.strftime("%Y-%m"), "days": days, "revision": state["revision"],
                    "opening_date": state["opening_date"], "opening_positions": state["opening_positions"]}

    def day(self, day: date, after: int = 0, limit: int = 50) -> dict:
        with self.store() as repo:
            state = repo.state()
            calendar = LocalSessions(repo.sessions(day - timedelta(days=32), day + timedelta(days=32)))
            rows = {row["as_of"]: row["data"] for row in repo.days(day, day)}
            prices = self._prices(repo, rows, day, day)
            result = self._value(day, state, calendar, rows.get(day), prices)
            records = repo.trades(day, day, limit=limit + 1, after=after)
            result["trades"] = [
                {**row["data"], "id": row["id"], "revision": row["revision"],
                 "source": {"image_hash": row["digest"], "row_number": row["row_number"]}}
                for row in records[:limit]
            ]
            result["next_after"] = records[limit - 1]["id"] if len(records) > limit else None
            return {**result, "revision": state["revision"], "coverage": repo.coverage(day, day).get(day)}

    def _value(self, day, state, calendar, row, prices) -> dict:
        result = {"date": day, "status": "insufficient", "pnl": None, "issues": [], "opening": [], "closing": [], "available_closes": [],
                  "previous_date": None, "components": None, "executions": [], "actions": []}
        opening_date = state["opening_date"]
        if calendar.closed(day):
            return {**result, "status": "closed"}
        if day > self.today():
            return {**result, "status": "future"}
        if not opening_date:
            return {**result, "status": "setup", "issues": ["opening-required"]}
        if day <= opening_date:
            return {**result, "status": "before-start"}
        resolved = calendar.resolution(day)
        if row is None:
            issue = "coverage-unconfirmed" if resolved.sufficient else "calendar-missing"
            return {**result, "issues": [issue]}
        issues = list(row["issues"])
        previous_date = date.fromisoformat(row["previous_date"]) if row["previous_date"] else None
        if (not resolved.sufficient or previous_date != resolved.previous_as_of) and "calendar-missing" not in issues:
            issues.append("calendar-missing")
        before = None
        after = None
        if row["opening"] is not None and previous_date is not None:
            before, result["opening"], problems = value_positions(previous_date, row["opening"], prices)
            issues.extend(problems)
        if row["closing"] is not None:
            after, result["closing"], problems = value_positions(day, row["closing"], prices)
            issues.extend(problems)
        else:
            result["available_closes"] = [
                {"security": security, "close": format(prices[day, security]["close"], "f"), "source": prices[day, security]["source"]}
                for security in sorted(self._valuation_securities(row)) if (day, security) in prices
            ]
        result.update(previous_date=previous_date, executions=row["executions"], actions=row["actions"], issues=issues)
        result["components"] = {
            "opening_value": money(before) if before is not None else None,
            "closing_value": money(after) if after is not None else None,
            "buy_cost": row["buy_cost"], "sell_proceeds": row["sell_proceeds"],
            "commission": row["commission"], "other_fees": row["other_fees"], "cash_adjustment": row["cash_adjustment"],
        }
        if not issues and before is not None and after is not None:
            pnl = after - before + Decimal(row["sell_proceeds"]) - Decimal(row["buy_cost"]) + Decimal(row["cash_adjustment"])
            result.update(status="ok", pnl=money(pnl))
        return result

    @staticmethod
    def _valuation_securities(projection: dict) -> set[str]:
        return set(projection["opening"] or {}) | {item["security"] for item in projection.get("executions", [])}

    @staticmethod
    def _prices(repo: TradingPnlRepository, rows: dict, start: date, end: date) -> dict:
        keys = set()
        for day, projection in rows.items():
            securities = projection["closing"]
            keys.update((day, security) for security in (securities if securities is not None else TradingPnlQueries._valuation_securities(projection)))
            if previous_date := projection["previous_date"]:
                keys.update((date.fromisoformat(previous_date), security) for security in projection["opening"] or {})
        if not keys:
            return {}
        start = min(start, min(day for day, _ in keys))
        securities = sorted({security for _, security in keys})
        prices = {}
        for row in repo.original_closes(start, end, securities):
            key = (row["as_of"], row["security_id"])
            price = Decimal(str(row["original_close"]))
            if key in keys and price.is_finite() and price > ZERO:
                prices.setdefault(key, {"close": price, "source": f'{row["source"]} · {row["source_revision"]}',
                                        "price_kind": "original-close"})
        for key, row in repo.valuations(start, end).items():
            if row.close is not None and key in keys:
                candidate = {"close": row.close, "source": row.price_source or row.source, "price_kind": row.price_kind}
                if row.price_kind == "suspended-valuation":
                    prices[key] = candidate
                else:
                    prices.setdefault(key, candidate)
        return prices
