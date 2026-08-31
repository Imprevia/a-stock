"""Deterministic rule-set execution with trace, confidence, and veto precedence."""

from __future__ import annotations

from typing import Any

from ..data.canonical import sha256_value, validate_snapshot
from ..rules.models import RuleDefinition, RuleSetDefinition, RuleValidationError
from .evaluators import resolve_evaluator


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    operations = {
        "eq": lambda: actual == expected,
        "ne": lambda: actual != expected,
        "gt": lambda: actual > expected,
        "gte": lambda: actual >= expected,
        "lt": lambda: actual < expected,
        "lte": lambda: actual <= expected,
        "truthy": lambda: bool(actual),
        "falsy": lambda: not bool(actual),
    }
    return bool(operations[operator]())


def _evaluate_one(rule: RuleDefinition, snapshot: dict[str, Any], traces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing_inputs = [name for name in rule.inputs if snapshot["metrics"].get(name) is None]
    result = resolve_evaluator(rule.evaluator)(rule, snapshot, traces)
    vetoes = []
    for veto in rule.vetoes:
        actual = snapshot["metrics"].get(veto["input"])
        if actual is not None and _compare(actual, veto["operator"], veto["value"]):
            vetoes.append(veto["reason"])

    status = "ok"
    if result.score is None:
        status = "insufficient" if rule.missing_data == "insufficient" else "missing"
    if vetoes:
        status = "vetoed"
    return {
        "ruleId": rule.rule_id,
        "version": rule.version,
        "title": rule.title,
        "status": status,
        "value": result.value,
        "score": result.score,
        "weight": rule.scoring["weight"],
        "thresholdProvenance": rule.thresholds["provenance"],
        "missingInputs": missing_inputs,
        "vetoes": vetoes,
        "details": result.details,
    }


def _confidence(coverage: float, snapshot_status: str, warnings: list[str]) -> str:
    if coverage < 0.5:
        return "insufficient"
    if coverage < 0.7 or snapshot_status == "insufficient":
        return "low"
    if coverage < 0.9 or snapshot_status == "degraded" or warnings:
        return "medium"
    return "high"


def _state(score: float | None, vetoes: list[str], confidence: str) -> str:
    if score is None or confidence == "insufficient":
        return "insufficient"
    if vetoes:
        return "retreat"
    if score >= 70:
        return "trend"
    if score >= 40:
        return "rotation"
    return "retreat"


def evaluate_rule_set(rule_set: RuleSetDefinition, snapshot: dict[str, Any]) -> dict[str, Any]:
    validate_snapshot(snapshot)
    traces: dict[str, dict[str, Any]] = {}
    pending: dict[str, RuleDefinition] = {rule.rule_id: rule for rule in rule_set.rules}

    # Base rules have no rule dependencies. Aggregate rules wait until all declared
    # members are available, which keeps execution independent from YAML ordering.
    while pending:
        progressed = False
        for rule_id in sorted(tuple(pending)):
            rule = pending[rule_id]
            members = tuple(rule.parameters.get("members", []))
            if members and not all(member in traces for member in members):
                continue
            traces[rule_id] = _evaluate_one(rule, snapshot, traces)
            del pending[rule_id]
            progressed = True
        if not progressed:
            unresolved = {rule_id: pending[rule_id].parameters.get("members", []) for rule_id in sorted(pending)}
            raise RuleValidationError(f"unresolved or cyclic rule dependencies: {unresolved}")

    ordered_traces = [traces[rule.rule_id] for rule in sorted(rule_set.rules, key=lambda item: item.rule_id)]
    scored = [trace for trace in ordered_traces if trace["score"] is not None]
    coverage = len(scored) / len(ordered_traces) if ordered_traces else 0.0
    vetoes = [f"{trace['ruleId']}: {reason}" for trace in ordered_traces for reason in trace["vetoes"]]
    final_trace = traces.get("QTS-01-08-01")
    if final_trace and final_trace["score"] is not None:
        score = float(final_trace["score"])
    else:
        weighted = [(trace["score"], trace["weight"]) for trace in scored if trace["weight"] > 0]
        score = sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted) if weighted else None
    confidence = _confidence(coverage, snapshot["status"], snapshot["warnings"])
    result = {
        "asOf": snapshot["asOf"],
        "ruleSet": rule_set.name,
        "ruleSetVersion": rule_set.version,
        "snapshotHash": sha256_value(snapshot),
        "score": round(score, 8) if score is not None else None,
        "state": _state(score, vetoes, confidence),
        "confidence": confidence,
        "coverage": round(coverage, 8),
        "vetoes": vetoes,
        "missingInputs": sorted({name for trace in ordered_traces for name in trace["missingInputs"]}),
        "traces": ordered_traces,
    }
    result["resultHash"] = sha256_value(result)
    return result
