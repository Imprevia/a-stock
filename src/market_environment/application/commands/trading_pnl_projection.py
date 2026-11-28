"""Rebuild dated holdings after explicit ledger changes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta

from ...domain.analysis.trading_pnl import ZERO, aggregate_executions, money, project_holdings
from ...domain.models.trading_pnl import Trade
from ..ports.trading_pnl import Row, TradingPnlRepository
from ..queries.trading_pnl import LocalSessions


ONE_DAY = timedelta(days=1)


def _restore_seed(repo: TradingPnlRepository, start: date) -> Row | None:
    seed = repo.latest_day(start)
    if seed is None or seed["data"]["closing"] is not None:
        return seed
    # A projection blocked by an earlier gap cannot seed a fresh estimate.
    blockers = [date.fromisoformat(seed["data"][key]) for key in ("coverage_gap_date", "blocking_holdings_date")
                if seed["data"].get(key)]
    if not blockers:
        return None
    earlier = repo.latest_day(min(blockers))
    return earlier if earlier is not None and earlier["data"]["closing"] is not None else None


def replay_start(repo: TradingPnlRepository, result_start: date) -> date | None:
    """Return the first calendar date to verify after the closest usable holdings seed."""
    opening = repo.state()["opening_date"]
    if opening is None:
        return None
    seed = _restore_seed(repo, result_start)
    return (seed["as_of"] if seed else opening) + ONE_DAY


def project_days(repo: TradingPnlRepository, start: date, end: date) -> dict[date, dict]:
    """Replay using local evidence, allowing incomplete trade coverage up through end."""
    state = repo.state()
    if state["opening_date"] is None:
        return {}
    seed = _restore_seed(repo, start)
    return {day: row for day, row in _replay(repo, state, seed, end, end) if day >= start}


def missing_actions(repo: TradingPnlRepository, start: date, end: date) -> set[tuple[date, str]]:
    """Find held or potentially held securities with unverified actions on replay days."""
    state = repo.state()
    if state["opening_date"] is None:
        return set()
    seed = _restore_seed(repo, start)
    candidates: set[tuple[date, str]] = set()
    for _ in _replay(repo, state, seed, end, end, action_candidates=candidates):
        pass
    return candidates


def rebuild(repo: TradingPnlRepository, dirty: date, revision: int) -> None:
    state = repo.state()
    opening_date = state["opening_date"]
    if opening_date is None:
        return
    start = max(dirty, opening_date + ONE_DAY)
    horizon = repo.calculation_horizon()
    end = repo.last_covered_date()
    if horizon is not None:
        end = max(horizon, end or horizon)
    seed = _restore_seed(repo, start) if horizon is not None else repo.latest_day(start)
    # Check any unprojected sessions between the seed and the earliest changed date.
    repo.reset_days((seed["as_of"] if seed else opening_date) + ONE_DAY)
    if end is not None:
        for day, row in _replay(repo, state, seed, end, horizon):
            repo.put_day(day, revision, row)


def _replay(
    repo: TradingPnlRepository, state: Row, seed: Row | None, end: date, horizon: date | None,
    *, action_candidates: set[tuple[date, str]] | None = None,
) -> Iterator[tuple[date, dict]]:
    previous_day = seed["as_of"] if seed else state["opening_date"]
    start = previous_day + ONE_DAY
    if end < start:
        return
    prior = seed["data"] if seed else {}
    positions = prior["closing"] if seed else {key: qty for key, qty in state["opening_positions"].items() if qty}
    coverage_gap = date.fromisoformat(prior["coverage_gap_date"]) if prior.get("coverage_gap_date") else None
    blocking_day = prior.get("blocking_holdings_date")
    blocking_issues = prior.get("blocking_holdings_issues", [])
    potential_holdings = set(positions or {})
    calendar = LocalSessions(repo.sessions(previous_day, end))
    coverage = repo.coverage(start, end)
    actions = repo.valuations(start, end)
    trades = defaultdict(list)
    for row in repo.trades(start, end):
        trade = Trade.model_validate(row["data"])
        trades[trade.date].append(trade)
    days = {day for day, session in calendar.sessions.items() if day >= start and session.is_session} | set(trades)
    for day in sorted(days):
        resolved = calendar.resolution(day)
        allow_estimate = horizon is not None and day <= horizon
        uncovered = day not in coverage
        prior_gap = coverage_gap is not None and not allow_estimate
        if uncovered and coverage_gap is None:
            coverage_gap = day
        issues = []
        holdings_issues = []
        if not resolved.sufficient or resolved.previous_as_of != previous_day:
            holdings_issues.append("calendar-missing")
        issues.extend(holdings_issues)
        if uncovered:
            issues.append("coverage-unconfirmed")
        if positions is None or prior_gap:
            issues.append("prior-holdings-unconfirmed")
        executions, order_issues = aggregate_executions(trades.get(day, []))
        issues.extend(order_issues)
        holdings_issues.extend(order_issues)
        before = positions if resolved.previous_as_of == previous_day and not prior_gap else None
        relevant_actions = {security: actions[day, security] for security in before or {} if (day, security) in actions}
        if action_candidates is not None and resolved.sufficient:
            for security in before if before is not None else potential_holdings:
                if (action := actions.get((day, security))) is None or not action.actions_confirmed:
                    action_candidates.add((day, security))
        closing = None
        adjustment = ZERO
        applied = []
        if not holdings_issues and before is not None and (allow_estimate or coverage_gap is None):
            projected, adjustment, applied, action_issues = project_holdings(before, executions, relevant_actions)
            issues.extend(action_issues)
            holdings_issues.extend(action_issues)
            if not action_issues:
                closing = projected
        if holdings_issues and blocking_day is None:
            blocking_day = day.isoformat()
            blocking_issues = holdings_issues
        if any(item.fees_pending for item in executions):
            issues.append("fees-unconfirmed")
        buy_cost = sum((item.gross + item.commission + item.other_fees for item in executions if item.side == "buy"), ZERO)
        sell_proceeds = sum((item.gross - item.commission - item.other_fees for item in executions if item.side == "sell"), ZERO)
        yield day, {
            "previous_date": resolved.previous_as_of.isoformat() if resolved.previous_as_of is not None else None,
            "opening": before, "closing": closing, "issues": issues,
            "coverage_gap_date": coverage_gap.isoformat() if coverage_gap is not None else None,
            "blocking_holdings_date": blocking_day,
            "blocking_holdings_issues": blocking_issues,
            "executions": [item.public() for item in executions], "actions": applied,
            "cash_adjustment": money(adjustment), "buy_cost": money(buy_cost), "sell_proceeds": money(sell_proceeds),
            "commission": money(sum((item.commission for item in executions), ZERO)),
            "other_fees": money(sum((item.other_fees for item in executions), ZERO)),
        }
        if action_candidates is not None:
            if closing is not None:
                potential_holdings = set(closing)
            else:
                potential_holdings.update(trade.security for trade in trades.get(day, []) if trade.filled_quantity)
        previous_day, positions = day, closing
