"""Deterministic trade aggregation, holdings replay and closing valuation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from ..models.trading_pnl import Trade, ValuationEvidence


ZERO = Decimal(0)
CENT = Decimal("0.01")
COMMISSION_RULE = "simulated-0.00025-min-5"


def money(value: Decimal) -> str:
    rounded = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return format(rounded if rounded else ZERO, ".2f")


def simulated_commission(amount: Decimal) -> Decimal:
    return max(amount * Decimal("0.00025"), Decimal(5)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Execution:
    security: str
    side: str
    quantity: int
    gross: Decimal
    commission: Decimal
    other_fees: Decimal
    fee_source: str
    fees_pending: bool
    order_id: str | None

    def public(self) -> dict:
        return {
            "security": self.security, "side": self.side, "quantity": self.quantity,
            "gross": money(self.gross), "commission": money(self.commission), "other_fees": money(self.other_fees),
            "fee_source": self.fee_source, "fees_pending": self.fees_pending, "order_id": self.order_id,
        }


def aggregate_executions(trades: list[Trade]) -> tuple[list[Execution], list[str]]:
    groups: dict[tuple[str, str, str | int], list[Trade]] = defaultdict(list)
    identities: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for index, trade in enumerate(trades):
        if trade.order_id:
            identities[trade.order_id].add((trade.security, trade.side))
        groups[trade.security, trade.side, trade.order_id or index].append(trade)
    issues = [f"order-conflict:{order}" for order, grouping in identities.items() if len(grouping) > 1]
    executions = []
    for (security, side, _), group in groups.items():
        if group[0].order_id and len(identities[group[0].order_id]) > 1:
            continue
        actual = [trade for trade in group if trade.filled_quantity and not trade.cumulative]
        snapshots = [trade for trade in group if trade.filled_quantity and trade.cumulative]
        quantity = sum(trade.filled_quantity for trade in actual)
        gross = sum((trade.amount for trade in actual), ZERO)
        latest: list[Trade] = []
        if snapshots:
            maximum = max(trade.filled_quantity for trade in snapshots)
            latest = [trade for trade in snapshots if trade.filled_quantity == maximum]
            amounts = {trade.amount for trade in latest}
            if len(amounts) != 1 or maximum == quantity and gross not in amounts or maximum > quantity and gross > latest[0].amount:
                issues.append(f"order-conflict:{group[0].order_id}")
                continue
            if maximum >= quantity:
                if maximum > quantity:
                    actual = []
                quantity, gross = maximum, latest[0].amount
            else:
                latest = []
        if quantity == 0:
            continue
        ordered = {trade.ordered_quantity for trade in group if trade.ordered_quantity is not None}
        if len(ordered) > 1 or ordered and quantity > min(ordered):
            issues.append(f"order-conflict:{group[0].order_id}")
            continue
        summary_commissions = {trade.commission for trade in latest if trade.commission is not None}
        summary_fees = {trade.other_fees for trade in latest if trade.other_fees is not None}
        commission_known = len(summary_commissions) == 1 or bool(actual and all(trade.commission is not None for trade in actual))
        if len(summary_commissions) == 1:
            commission = next(iter(summary_commissions))
        elif commission_known:
            commission = sum((trade.commission for trade in actual), ZERO)
        else:
            commission = simulated_commission(gross)
        fees_pending = (
            len(summary_commissions) > 1 or len(summary_fees) > 1
            or any(trade.fees_pending for trade in actual + latest)
            or bool(not commission_known and any(trade.commission is not None for trade in actual))
        )
        other_fees = next(iter(summary_fees)) if len(summary_fees) == 1 else sum((trade.other_fees or ZERO for trade in actual), ZERO)
        executions.append(Execution(
            security, side, quantity, gross, commission, other_fees, "confirmed" if commission_known else COMMISSION_RULE,
            fees_pending, group[0].order_id,
        ))
    return executions, issues


def project_holdings(
    previous: dict[str, int], executions: list[Execution], actions: dict[str, ValuationEvidence],
) -> tuple[dict[str, int], Decimal, list[dict], list[str]]:
    positions = previous.copy()
    cash = ZERO
    applied = []
    issues = []
    for security in sorted(previous):
        action = actions.get(security)
        if action is None or not action.actions_confirmed:
            issues.append(f"missing-actions:{security}")
            continue
        positions[security] += action.share_delta
        if positions[security] < 0:
            issues.append(f"negative-position:{security}")
        cash += action.cash_adjustment
        applied.append({
            "security": security, "share_delta": action.share_delta,
            "cash_adjustment": money(action.cash_adjustment), "source": action.action_source or action.source,
        })
    for execution in executions:
        direction = 1 if execution.side == "buy" else -1
        positions[execution.security] = positions.get(execution.security, 0) + direction * execution.quantity
    issues.extend(f"negative-position:{security}" for security, quantity in positions.items() if quantity < 0)
    return {security: quantity for security, quantity in sorted(positions.items()) if quantity > 0}, cash, applied, list(dict.fromkeys(issues))


def value_positions(day: date, positions: dict[str, int], prices: dict) -> tuple[Decimal | None, list[dict], list[str]]:
    value = ZERO
    details = []
    issues = []
    for security, quantity in positions.items():
        estimate = prices.get((day, security))
        if estimate is None:
            issues.append(f"missing-close:{day}:{security}")
            details.append({"security": security, "quantity": quantity, "close": None, "value": None, "source": None})
            continue
        amount = estimate["close"] * quantity
        value += amount
        details.append({
            "security": security, "quantity": quantity, "close": format(estimate["close"], "f"),
            "value": money(amount), "source": estimate["source"], "price_kind": estimate["price_kind"],
        })
    return None if issues else value, details, issues
