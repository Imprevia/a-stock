"""Small immutable models shared by the parser, index and service layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class KnowledgeError(ValueError):
    """Expected, user-facing knowledge service error."""


class IndexBuildError(KnowledgeError):
    """Raised when a complete index cannot be built safely."""


@dataclass(frozen=True)
class SourceFile:
    layer: str
    document_ref: str
    path: Path
    content_sha256: str
    byte_size: int
    line_count: int

    def manifest_item(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "document_ref": self.document_ref,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "line_count": self.line_count,
        }


@dataclass(frozen=True)
class Chunk:
    citation_id: str
    source_layer: str
    document_ref: str
    heading_path: tuple[str, ...]
    line_start: int
    line_end: int
    rule_ids: tuple[str, ...]
    lifecycle_status: str | None
    evidence_status: str
    content: str
    content_sha256: str
    search_text: str
    cjk_text: str
    authority: str

    def canonical_item(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "source_layer": self.source_layer,
            "document_ref": self.document_ref,
            "heading_path": list(self.heading_path),
            "line_start": self.line_start,
            "line_end": self.line_end,
            "rule_ids": list(self.rule_ids),
            "lifecycle_status": self.lifecycle_status,
            "evidence_status": self.evidence_status,
            "content_sha256": self.content_sha256,
            "search_text": self.search_text,
            "cjk_text": self.cjk_text,
            "authority": self.authority,
        }


@dataclass
class RuleCatalog:
    """Validated structured facts used to enrich searchable chunks."""

    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    coverage: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_by_rule_set: dict[str, dict[str, Any]] = field(default_factory=dict)
    monthly_records: list[dict[str, Any]] = field(default_factory=list)
    conflicts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rule_set_sources: dict[str, str] = field(default_factory=dict)
    evidence_sources: dict[str, str] = field(default_factory=dict)

    def evidence_summary(self, rule_set: str | None) -> dict[str, Any]:
        if not rule_set or rule_set not in self.evidence_by_rule_set:
            return {
                "status": "insufficient",
                "latestEvidence": None,
                "validationEvidence": [],
                "note": "no evidence index entry",
            }
        summary = dict(self.evidence_by_rule_set[rule_set])
        latest = summary.get("latestEvidence")
        if latest is None:
            summary["status"] = "insufficient"
        else:
            summary["status"] = str(latest.get("status", "insufficient"))
        summary["monthlyEvidence"] = [
            record
            for record in self.monthly_records
            if record.get("ruleSet") == rule_set
        ]
        return summary

    def evidence_status(self, rule_set: str | None) -> str:
        return str(self.evidence_summary(rule_set).get("status", "insufficient"))

    def canonical_facts(self) -> dict[str, Any]:
        return {
            "rules": self.rules,
            "coverage": self.coverage,
            "evidence_by_rule_set": self.evidence_by_rule_set,
            "monthly_records": self.monthly_records,
            "conflicts": self.conflicts,
            "rule_set_sources": self.rule_set_sources,
            "evidence_sources": self.evidence_sources,
        }
