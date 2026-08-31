"""Typed immutable rule definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RuleValidationError(ValueError):
    """Raised when registry or lifecycle validation fails."""


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    version: int
    title: str
    status: str
    scope: str
    evaluator: str
    inputs: tuple[str, ...]
    windows: tuple[int, ...]
    parameters: dict[str, Any]
    thresholds: dict[str, Any]
    scoring: dict[str, Any]
    vetoes: tuple[dict[str, Any], ...]
    missing_data: str
    outputs: tuple[str, ...]
    document_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RuleDefinition":
        return cls(
            rule_id=value["ruleId"],
            version=value["version"],
            title=value["title"],
            status=value["status"],
            scope=value["scope"],
            evaluator=value["evaluator"],
            inputs=tuple(value["inputs"]),
            windows=tuple(value["windows"]),
            parameters=dict(value["parameters"]),
            thresholds=dict(value["thresholds"]),
            scoring=dict(value["scoring"]),
            vetoes=tuple(dict(item) for item in value["vetoes"]),
            missing_data=value["missingData"],
            outputs=tuple(value["outputs"]),
            document_refs=tuple(value["documentRefs"]),
            evidence_refs=tuple(value["evidenceRefs"]),
        )


@dataclass(frozen=True)
class RuleSetDefinition:
    name: str
    version: int
    rules: tuple[RuleDefinition, ...]
    source_path: str

    @property
    def by_id(self) -> dict[str, RuleDefinition]:
        return {rule.rule_id: rule for rule in self.rules}
