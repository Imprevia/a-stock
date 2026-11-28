"""Rebuild dated holdings after explicit ledger changes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ...domain.analysis.trading_pnl import ZERO, aggregate_executions, money, project_holdings
from ...domain.models.trading_pnl import Trade
from ..ports.trading_pnl import TradingPnlRepository
from ..queries.trading_pnl import LocalSessions


def rebuild(repo: TradingPnlRepository, dirty: date, revision: int) -> None:
    state = repo.state()
    opening_date = state["opening_date"]
    if opening_date is None:
        return
    start = max(dirty, opening_date + timedelta(days=1))
    end = repo.last_covered_date()
    seed = repo.latest_day(start)
    previous_day = seed["as_of"] if seed else opening_date
    # A previously unprojected session between the seed and the new write
    # still has to be checked for coverage before carrying holdings forward.
    start = previous_day + timedelta(days=1)
    repo.reset_days(start)
    if end is None or end < start:
        return
    positions = seed["data"]["closing"] if seed else {key: qty for key, qty in state["opening_positions"].items() if qty}
    calendar = LocalSessions(repo.sessions(min(previous_day, start), end))
    coverage = repo.coverage(start, end)
    actions = repo.valuations(start, end)
    trades = defaultdict(list)
    for row in repo.trades(start, end):
        trade = Trade.model_validate(row["data"])
        trades[trade.date].append(trade)
    days = {day for day, session in calendar.sessions.items() if day >= start and session.is_session} | set(trades)
    for day in sorted(days):
        resolved = calendar.resolution(day)
        issues = []
        if not resolved.sufficient or resolved.previous_as_of != previous_day:
            issues.append("calendar-missing")
        if day not in coverage:
            issues.append("coverage-unconfirmed")
        if positions is None:
            issues.append("prior-holdings-unconfirmed")
        executions, order_issues = aggregate_executions(trades.get(day, []))
        issues.extend(order_issues)
        before = positions if resolved.previous_as_of == previous_day else None
        closing = None
        adjustment = ZERO
        applied = []
        if not issues and before is not None:
            relevant_actions = {security: actions[day, security] for security in before if (day, security) in actions}
            projected, adjustment, applied, action_issues = project_holdings(before, executions, relevant_actions)
            issues.extend(action_issues)
            if not action_issues:
                closing = projected
        if any(item.fees_pending for item in executions):
            issues.append("fees-unconfirmed")
        buy_cost = sum((item.gross + item.commission + item.other_fees for item in executions if item.side == "buy"), ZERO)
        sell_proceeds = sum((item.gross - item.commission - item.other_fees for item in executions if item.side == "sell"), ZERO)
        repo.put_day(day, revision, {
            "previous_date": resolved.previous_as_of.isoformat() if resolved.previous_as_of is not None else None,
            "opening": before, "closing": closing, "issues": issues,
            "executions": [item.public() for item in executions], "actions": applied,
            "cash_adjustment": money(adjustment), "buy_cost": money(buy_cost), "sell_proceeds": money(sell_proceeds),
            "commission": money(sum((item.commission for item in executions), ZERO)),
            "other_fees": money(sum((item.other_fees for item in executions), ZERO)),
        })
        previous_day, positions = day, closing
