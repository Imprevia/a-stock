"""Bidirectional synchronization between quantified Markdown and YAML rules."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .models import RuleValidationError
from .registry import all_rules, load_rule_sets, repository_root

RULE_ID_PATTERN = re.compile(r"QTS-[0-9]{2}-[0-9]{2}-[0-9]{2}")


def scan_documented_rules(root: Path | None = None) -> dict[str, str]:
    repo = root or repository_root()
    docs_root = repo / "搭建交易系统-量化版"
    result: dict[str, str] = {}
    for path in sorted(docs_root.rglob("*.md")):
        relative = path.relative_to(repo).as_posix()
        for rule_id in RULE_ID_PATTERN.findall(path.read_text(encoding="utf-8")):
            if rule_id in result:
                if result[rule_id] == relative:
                    continue
                raise RuleValidationError(f"documented rule ID {rule_id} appears in both {result[rule_id]} and {relative}")
            result[rule_id] = relative
    return result


def build_coverage(root: Path | None = None) -> dict[str, Any]:
    repo = root or repository_root()
    documented = scan_documented_rules(repo)
    registry = all_rules(load_rule_sets(repo).values())
    entries = []
    for rule_id, document_ref in sorted(documented.items()):
        rule = registry.get(rule_id)
        entries.append(
            {
                "ruleId": rule_id,
                "documentRef": document_ref,
                "implementation": "executable" if rule else "documented-only",
                "evaluator": rule.evaluator if rule else None,
                "tests": ["tests/test_trading_rule_platform.py"] if rule else [],
                "evidenceRefs": list(rule.evidence_refs) if rule else [],
            }
        )
    return {"version": 1, "documentedRules": len(documented), "executableRules": len(registry), "entries": entries}


def write_coverage(root: Path | None = None) -> Path:
    repo = root or repository_root()
    path = repo / "trading-rules" / "coverage.yaml"
    path.write_text(yaml.safe_dump(build_coverage(repo), allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    return path


def validate_coverage(root: Path | None = None) -> dict[str, int]:
    repo = root or repository_root()
    expected = build_coverage(repo)
    coverage_path = repo / "trading-rules" / "coverage.yaml"
    if not coverage_path.exists():
        raise RuleValidationError("trading-rules/coverage.yaml is missing")
    actual = yaml.safe_load(coverage_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise RuleValidationError("trading-rules/coverage.yaml is stale; run rules coverage --write")

    registry = all_rules(load_rule_sets(repo).values())
    for rule in registry.values():
        for document_ref in rule.document_refs:
            path = repo / Path(document_ref)
            if not path.exists():
                raise RuleValidationError(f"{rule.rule_id}: missing document reference {document_ref}")
            if rule.rule_id not in path.read_text(encoding="utf-8"):
                raise RuleValidationError(f"{rule.rule_id}: document reference does not contain the rule ID")
    return {"documentedRules": expected["documentedRules"], "executableRules": expected["executableRules"]}
