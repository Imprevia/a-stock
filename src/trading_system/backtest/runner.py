"""Historical replay with coverage, costs, partitions, and confidence intervals."""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from ..data.canonical import load_snapshot, sha256_value
from ..evaluation.engine import evaluate_rule_set
from ..rules.models import RuleSetDefinition, RuleValidationError


def _metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"observations": 0, "mean": None, "standardDeviation": None, "confidenceInterval95": [None, None]}
    mean = statistics.fmean(values)
    standard_deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = 1.96 * standard_deviation / math.sqrt(len(values)) if values else 0.0
    return {
        "observations": len(values),
        "mean": round(mean, 10),
        "standardDeviation": round(standard_deviation, 10),
        "confidenceInterval95": [round(mean - margin, 10), round(mean + margin, 10)],
    }


def run_backtest(
    snapshot_paths: Iterable[Path],
    rule_set: RuleSetDefinition,
    *,
    transaction_cost_bps: float = 10.0,
    in_sample_ratio: float = 0.7,
) -> dict[str, Any]:
    if not 0.5 <= in_sample_ratio < 1.0:
        raise ValueError("in_sample_ratio must be between 0.5 and 1.0")
    if transaction_cost_bps < 0:
        raise ValueError("transaction_cost_bps cannot be negative")
    snapshots = [load_snapshot(path) for path in snapshot_paths]
    snapshots.sort(key=lambda item: item["asOf"])
    if len({item["asOf"] for item in snapshots}) != len(snapshots):
        raise RuleValidationError("backtest snapshots contain duplicate asOf dates")

    runs = []
    net_returns = []
    for snapshot in snapshots:
        result = evaluate_rule_set(rule_set, snapshot)
        forward_return = snapshot["metrics"].get("backtest.forward_return")
        net_return = None
        if isinstance(forward_return, (int, float)):
            net_return = float(forward_return) - transaction_cost_bps / 10000.0
            net_returns.append(net_return)
        runs.append(
            {
                "asOf": snapshot["asOf"],
                "snapshotHash": result["snapshotHash"],
                "resultHash": result["resultHash"],
                "score": result["score"],
                "state": result["state"],
                "netForwardReturn": net_return,
            }
        )

    split_index = int(len(net_returns) * in_sample_ratio)
    in_sample = net_returns[:split_index]
    out_of_sample = net_returns[split_index:]
    available_days = len(snapshots)
    eligible = available_days >= 500 and len(net_returns) >= 500 and bool(in_sample) and bool(out_of_sample)
    summary = {
        "schemaVersion": 1,
        "ruleSet": rule_set.name,
        "ruleSetVersion": rule_set.version,
        "availableTradingDays": available_days,
        "targetTradingDays": 750,
        "minimumTradingDays": 500,
        "coverageGap": max(0, 500 - available_days),
        "transactionCostBps": transaction_cost_bps,
        "inSampleRatio": in_sample_ratio,
        "inSample": _metrics(in_sample),
        "outOfSample": _metrics(out_of_sample),
        "validationEligible": eligible,
        "runs": runs,
    }
    summary["backtestHash"] = sha256_value(summary)
    return summary


def validate_validation_evidence(evidence: dict[str, Any]) -> None:
    required = {
        "availableTradingDays",
        "transactionCostBps",
        "inSample",
        "outOfSample",
        "ruleSetVersion",
        "backtestHash",
        "rollbackCriteria",
    }
    missing = sorted(required - set(evidence))
    if missing:
        raise RuleValidationError(f"validation evidence missing: {', '.join(missing)}")
    if evidence["availableTradingDays"] < 500:
        raise RuleValidationError("validation evidence requires at least 500 trading days")
    if evidence["inSample"].get("observations", 0) == 0 or evidence["outOfSample"].get("observations", 0) == 0:
        raise RuleValidationError("validation evidence requires non-empty in-sample and out-of-sample partitions")
    for partition in ("inSample", "outOfSample"):
        interval = evidence[partition].get("confidenceInterval95")
        if not isinstance(interval, list) or len(interval) != 2 or None in interval:
            raise RuleValidationError(f"validation evidence requires {partition} confidence interval")
