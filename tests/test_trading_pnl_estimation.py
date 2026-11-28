from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from src.market_environment.application.commands.trading_pnl_projection import (
    missing_actions,
    project_days,
    rebuild,
    replay_start,
)
from src.market_environment.application.queries.trading_pnl import TradingPnlQueries
from src.market_environment.domain.models.trading_pnl import Trade, ValuationEvidence


OPENING, BUY, HOLD, SELL, LATER, OUTSIDE = (date(2026, 1, day) for day in (20, 21, 22, 23, 26, 27))
SECURITY = "603019.SH"


def ranged(rows, start, end):
    return {day: row for day, row in rows.items() if start <= day <= end}


def fill(day, side, shares, price):
    return Trade(date=day, security=SECURITY, side=side, status="filled", filled_quantity=shares,
                 price=price, amount=shares * price)


class Ledger:
    def __init__(self):
        self.estimate_start = None
        self.horizon = None
        self.rows = {}
        self.covers = {SELL: "complete", OUTSIDE: "no-trades"}
        self.fills = {BUY: fill(BUY, "buy", 100, 10)}
        self.valuations_by_key = {}
        self.closes = {}
        self.action_reasons = {}
        self.calendar = {
            day: SimpleNamespace(as_of=day, actual_as_of=day, previous_as_of=previous, is_session=True)
            for day, previous in zip((BUY, HOLD, SELL, LATER, OUTSIDE), (OPENING, BUY, HOLD, SELL, LATER), strict=True)
        }
        self.calendar[OPENING] = SimpleNamespace(as_of=OPENING, actual_as_of=OPENING, previous_as_of=None, is_session=True)

    @contextmanager
    def read(self):
        yield self

    def state(self):
        return {"opening_date": OPENING, "opening_positions": {}, "revision": 1}

    def calculation_start(self):
        return self.estimate_start

    def calculation_horizon(self):
        return self.horizon

    def action_issue(self, day, security):
        return self.action_reasons.get((day, security))

    def confirm_action(self, day):
        self.valuations_by_key[day, SECURITY] = ValuationEvidence(
            date=day, actual_date=day, security=SECURITY, actions_confirmed=True, source="confirmed evidence",
        )

    def latest_day(self, before):
        day = max((day for day in self.rows if day < before), default=None)
        return {"as_of": day, "data": self.rows[day]} if day else None

    def first_coverage_gap(self, before):
        return min((day for day, row in self.rows.items() if day < before and "coverage-unconfirmed" in row["issues"]),
                   default=None)

    def reset_days(self, start):
        self.rows = {day: row for day, row in self.rows.items() if day < start}

    def put_day(self, day, revision, data):
        self.rows[day] = data

    def last_covered_date(self):
        return max(self.covers.keys() | self.fills.keys())

    def days(self, start, end):
        return [{"as_of": day, "data": row} for day, row in ranged(self.rows, start, end).items()]

    def sessions(self, start, end):
        return ranged(self.calendar, start, end)

    def coverage(self, start, end):
        return ranged(self.covers, start, end)

    def valuations(self, start, end):
        return {key: value for key, value in self.valuations_by_key.items() if start <= key[0] <= end}

    def original_closes(self, start, end, securities):
        if SECURITY not in securities:
            return []
        return [{"as_of": day, "security_id": SECURITY, "original_close": close, "source": "fixture", "source_revision": 1}
                for day, close in ranged(self.closes, start, end).items()]

    def trades(self, start, end, limit=None, after=0):
        return [{"id": 1, "revision": 1, "digest": "image", "row_number": 0, "data": trade.model_dump(mode="json")}
                for trade in ranged(self.fills, start, end).values() if after == 0][:limit]


def test_estimation_is_bounded_and_updates_after_coverage_or_price_change():
    repo = Ledger()
    repo.closes = {BUY: 11, HOLD: 12, SELL: 13, LATER: 14, OUTSIDE: 15}
    for day in (HOLD, SELL, LATER, OUTSIDE):
        repo.confirm_action(day)
    queries = TradingPnlQueries(repo.read, lambda: OUTSIDE)

    rebuild(repo, BUY, 1)
    for row in repo.rows.values():
        for key in ("coverage_gap_date", "blocking_holdings_date", "blocking_holdings_issues"):
            del row[key]
    assert queries.day(HOLD)["status"] == "insufficient"
    assert queries.day(SELL)["blocking_coverage_date"] == BUY
    assert repo.rows[HOLD]["closing"] is None
    assert replay_start(repo, SELL) == BUY
    provisional = project_days(repo, HOLD, LATER)
    assert provisional[HOLD]["opening"] == {SECURITY: 100}
    assert provisional[HOLD]["closing"] == {SECURITY: 100}
    assert queries.range_summary(repo, repo.state(), HOLD, LATER, projections=provisional)[0]["estimated_pnl"] == "100.00"
    assert repo.rows[HOLD]["closing"] is None

    repo.estimate_start, repo.horizon = HOLD, HOLD
    rebuild(repo, HOLD, 2)
    assert queries.day(HOLD)["estimated_pnl"] == "100.00"
    assert queries.day(SELL)["estimated_pnl"] is None
    repo.horizon = LATER
    rebuild(repo, SELL, 3)
    day = queries.day(SELL)
    month_day = next(row for row in queries.month(2026, 1)["days"] if row["date"] == SELL)
    assert day["coverage"] == "complete"
    assert day["status"] == month_day["status"] == "estimated"
    assert day["estimated_pnl"] == month_day["estimated_pnl"] == "100.00"
    assert day["pnl"] is None and day["blocking_coverage_date"] == BUY
    assert queries.day(BUY)["estimated_pnl"] is None
    assert queries.day(OUTSIDE)["estimated_pnl"] is None
    assert queries.day(OUTSIDE)["closing"] == []

    del repo.closes[HOLD]
    assert queries.day(HOLD)["estimated_pnl"] is None
    assert queries.day(SELL)["estimated_pnl"] is None
    assert queries.day(LATER)["estimated_pnl"] == "100.00"
    repo.closes[HOLD] = 12
    repo.covers.update({BUY: "complete", HOLD: "no-trades"})
    rebuild(repo, BUY, 3)
    assert queries.day(SELL)["pnl"] == "100.00"
    assert queries.day(SELL)["estimated_pnl"] is None
    assert queries.day(SELL)["blocking_coverage_date"] is None
    repo.covers[LATER] = "no-trades"
    rebuild(repo, LATER, 5)
    assert queries.day(OUTSIDE)["pnl"] == "100.00"
    intraday = TradingPnlQueries(repo.read, lambda: OUTSIDE, lambda: LATER)
    assert intraday.day(OUTSIDE)["status"] == "future"


def test_action_and_sell_conflicts_block_later_estimates_without_losing_the_cause():
    repo = Ledger()
    repo.estimate_start, repo.horizon = BUY, LATER
    repo.action_reasons[HOLD, SECURITY] = "fuyao-action-entitlement-unverified"
    repo.confirm_action(SELL)
    repo.fills[SELL] = fill(SELL, "sell", 150, 13)
    queries = TradingPnlQueries(repo.read, lambda: OUTSIDE)

    assert missing_actions(repo, BUY, LATER) == {(HOLD, SECURITY), (LATER, SECURITY)}
    rebuild(repo, BUY, 1)
    blocked = queries.day(LATER)
    assert blocked["blocking_holdings_date"] == HOLD
    assert blocked["blocking_holdings_issues"] == [f"missing-actions:{SECURITY}", f"fuyao-action-entitlement-unverified:{SECURITY}"]
    assert blocked["estimated_pnl"] is None
    assert queries.missing_prices(repo, HOLD, LATER, include_unverified=False) == {(BUY, SECURITY)}
    assert (HOLD, SECURITY) in queries.missing_prices(repo, HOLD, LATER)

    repo.confirm_action(HOLD)
    rebuild(repo, HOLD, 2)
    blocked = queries.day(LATER)
    assert blocked["blocking_holdings_date"] == SELL
    assert blocked["blocking_holdings_issues"] == [f"negative-position:{SECURITY}"]
    assert blocked["pnl"] is None and blocked["estimated_pnl"] is None

    repo.fills[SELL] = fill(SELL, "sell", 100, 13)
    rebuild(repo, SELL, 3)
    assert queries.day(LATER)["estimated_pnl"] == "0.00"
    assert not missing_actions(repo, BUY, LATER)
    projected = project_days(repo, SELL, LATER)
    assert queries.missing_prices(repo, SELL, LATER, projections=projected) == {(HOLD, SECURITY)}
