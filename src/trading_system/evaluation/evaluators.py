"""Small, typed evaluator primitives referenced by stable YAML names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..rules.models import RuleDefinition


@dataclass(frozen=True)
class EvaluatorResult:
    value: float | bool | str | None
    score: int | None
    details: dict[str, Any]


Evaluator = Callable[[RuleDefinition, Mapping[str, Any], Mapping[str, dict[str, Any]]], EvaluatorResult]
_EVALUATORS: dict[str, Evaluator] = {}


def register(name: str) -> Callable[[Evaluator], Evaluator]:
    def decorator(function: Evaluator) -> Evaluator:
        if name in _EVALUATORS:
            raise RuntimeError(f"duplicate evaluator registration: {name}")
        _EVALUATORS[name] = function
        return function

    return decorator


def evaluator_names() -> frozenset[str]:
    return frozenset(_EVALUATORS)


def resolve_evaluator(name: str) -> Evaluator:
    try:
        return _EVALUATORS[name]
    except KeyError as exc:
        raise ValueError(f"unknown evaluator: {name}") from exc


def _matches(value: Any, band: Mapping[str, Any]) -> bool:
    if "equals" in band and value != band["equals"]:
        return False
    if "lte" in band and not value <= band["lte"]:
        return False
    if "lt" in band and not value < band["lt"]:
        return False
    if "gte" in band and not value >= band["gte"]:
        return False
    if "gt" in band and not value > band["gt"]:
        return False
    return True


def apply_bands(value: Any, bands: list[dict[str, Any]]) -> int:
    for band in bands:
        if _matches(value, band):
            return int(band["score"])
    raise ValueError(f"value {value!r} did not match any threshold band")


@register("metric.band")
def metric_band(rule: RuleDefinition, snapshot: Mapping[str, Any], traces: Mapping[str, dict[str, Any]]) -> EvaluatorResult:
    del traces
    metric = rule.inputs[0]
    value = snapshot["metrics"].get(metric)
    if value is None:
        return EvaluatorResult(None, None, {"metric": metric})
    score = apply_bands(value, rule.thresholds["bands"])
    return EvaluatorResult(value, score, {"metric": metric})


@register("metric.boolean")
def metric_boolean(rule: RuleDefinition, snapshot: Mapping[str, Any], traces: Mapping[str, dict[str, Any]]) -> EvaluatorResult:
    del traces
    metric = rule.inputs[0]
    value = snapshot["metrics"].get(metric)
    if value is None:
        return EvaluatorResult(None, None, {"metric": metric})
    score = apply_bands(bool(value), rule.thresholds["bands"])
    return EvaluatorResult(bool(value), score, {"metric": metric})


@register("aggregate.rules")
def aggregate_rules(rule: RuleDefinition, snapshot: Mapping[str, Any], traces: Mapping[str, dict[str, Any]]) -> EvaluatorResult:
    del snapshot
    members = list(rule.parameters.get("members", []))
    member_weights = dict(rule.parameters.get("memberWeights", {}))
    available = [(member, traces[member]["score"]) for member in members if member in traces and traces[member]["score"] is not None]
    if not available:
        return EvaluatorResult(None, None, {"members": members, "available": []})
    weights = [float(member_weights.get(member, 1.0)) for member, _ in available]
    weighted = sum(float(score) * weight for (_, score), weight in zip(available, weights)) / sum(weights)
    if rule.parameters.get("invert"):
        weighted = 100.0 - weighted
    score = apply_bands(weighted, rule.thresholds["bands"])
    return EvaluatorResult(round(weighted, 8), score, {"members": members, "available": [member for member, _ in available]})
