"""Closed-schema YAML registry loading and lifecycle validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from ..evaluation.evaluators import evaluator_names
from .models import RuleDefinition, RuleSetDefinition, RuleValidationError

LIFECYCLE = ("draft", "defined", "backtested", "validated", "retired")
VALIDATION_EVIDENCE_PREFIXES = (
    "in-sample:",
    "out-of-sample:",
    "costs:",
    "confidence-interval:",
    "version:",
    "rollback:",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _schema_validator(root: Path) -> Draft202012Validator:
    schema_path = root / "trading-rules" / "schemas" / "rule.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_rule_sets(root: Path | None = None) -> dict[str, RuleSetDefinition]:
    repo = root or repository_root()
    rule_dir = repo / "trading-rules" / "rule-sets"
    validator = _schema_validator(repo)
    known_evaluators = evaluator_names()
    result: dict[str, RuleSetDefinition] = {}
    seen_ids: dict[str, Path] = {}

    for path in sorted(rule_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(raw), key=lambda error: list(error.path))
        if errors:
            messages = [f"{path}: {'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors]
            raise RuleValidationError("\n".join(messages))

        rules = tuple(RuleDefinition.from_dict(item) for item in raw["rules"])
        if raw["ruleSet"] in result:
            raise RuleValidationError(f"duplicate rule set: {raw['ruleSet']}")
        for rule in rules:
            if rule.rule_id in seen_ids:
                raise RuleValidationError(f"duplicate rule ID {rule.rule_id}: {seen_ids[rule.rule_id]} and {path}")
            seen_ids[rule.rule_id] = path
            if rule.evaluator not in known_evaluators:
                raise RuleValidationError(f"{rule.rule_id}: unknown evaluator {rule.evaluator}")
            _validate_lifecycle(rule)

        result[raw["ruleSet"]] = RuleSetDefinition(
            name=raw["ruleSet"],
            version=raw["version"],
            rules=rules,
            source_path=path.relative_to(repo).as_posix(),
        )

    if not result:
        raise RuleValidationError(f"no rule sets found in {rule_dir}")
    return result


def _validate_lifecycle(rule: RuleDefinition) -> None:
    if rule.status not in LIFECYCLE:
        raise RuleValidationError(f"{rule.rule_id}: invalid lifecycle state {rule.status}")
    provenance = rule.thresholds["provenance"]
    if rule.status == "validated":
        missing = [prefix for prefix in VALIDATION_EVIDENCE_PREFIXES if not any(ref.startswith(prefix) for ref in rule.evidence_refs)]
        if missing:
            raise RuleValidationError(f"{rule.rule_id}: validated rule missing evidence {', '.join(missing)}")
        if provenance != "validated":
            raise RuleValidationError(f"{rule.rule_id}: validated lifecycle requires validated threshold provenance")


def validate_transition(previous: RuleDefinition, current: RuleDefinition) -> None:
    """Validate an explicit lifecycle transition between rule versions."""

    if current.version < previous.version:
        raise RuleValidationError(f"{current.rule_id}: version cannot decrease")
    old_index = LIFECYCLE.index(previous.status)
    new_index = LIFECYCLE.index(current.status)
    if new_index > old_index + 1:
        raise RuleValidationError(f"{current.rule_id}: lifecycle cannot skip states")
    changed = (
        previous.evaluator != current.evaluator
        or previous.inputs != current.inputs
        or previous.parameters != current.parameters
        or previous.thresholds != current.thresholds
    )
    if changed and previous.status == "validated" and current.status not in {"defined", "backtested"}:
        raise RuleValidationError(f"{current.rule_id}: changed validated rule must return to defined or backtested")


def all_rules(rule_sets: Iterable[RuleSetDefinition]) -> dict[str, RuleDefinition]:
    return {rule.rule_id: rule for rule_set in rule_sets for rule in rule_set.rules}


def validate_registry(root: Path | None = None) -> dict[str, int]:
    rule_sets = load_rule_sets(root)
    return {
        "ruleSets": len(rule_sets),
        "rules": sum(len(rule_set.rules) for rule_set in rule_sets.values()),
    }
