"""Deterministic SQLite FTS5 index construction and health checks."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import INDEX_VERSION, PARSER_VERSION, KnowledgeConfig
from .models import Chunk, IndexBuildError, RuleCatalog, SourceFile
from .parsers import (
    build_structured_chunks,
    discover_source_files,
    enrich_markdown_evidence,
    load_rule_catalog,
    parse_markdown,
)
from .text import canonical_hash, canonical_json, sha256_bytes

SCHEMA_VERSION = "1"


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE documents (
            source_layer TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            line_count INTEGER NOT NULL,
            PRIMARY KEY (source_layer, document_ref)
        );

        CREATE TABLE chunks (
            citation_id TEXT PRIMARY KEY,
            source_layer TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            heading_path_json TEXT NOT NULL,
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            rule_ids_json TEXT NOT NULL,
            rule_ids_csv TEXT NOT NULL,
            lifecycle_status TEXT,
            evidence_status TEXT NOT NULL,
            content TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            search_text TEXT NOT NULL,
            cjk_text TEXT NOT NULL,
            authority TEXT NOT NULL
        );

        CREATE INDEX chunks_document_idx ON chunks (source_layer, document_ref, line_start);
        CREATE INDEX chunks_rule_idx ON chunks (rule_ids_csv);
        CREATE INDEX chunks_status_idx ON chunks (lifecycle_status, evidence_status);

        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            citation_id UNINDEXED,
            body,
            cjk,
            heading,
            path,
            rule_ids,
            tokenize = 'unicode61'
        );

        CREATE TABLE rules (
            rule_id TEXT PRIMARY KEY,
            rule_set TEXT,
            lifecycle_status TEXT NOT NULL,
            implementation_status TEXT NOT NULL,
            evaluator TEXT,
            threshold_provenance TEXT,
            document_refs_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            raw_rule_json TEXT,
            coverage_json TEXT,
            evidence_json TEXT NOT NULL,
            machine_citation_id TEXT,
            evidence_status TEXT NOT NULL
        );

        CREATE TABLE evidence_summaries (
            rule_set TEXT PRIMARY KEY,
            evidence_status TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            source_ref TEXT
        );

        CREATE TABLE conflicts (
            rule_id TEXT NOT NULL,
            conflict_json TEXT NOT NULL
        );
        """
    )


def _insert_meta(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
    connection.executemany(
        "INSERT INTO index_meta(key, value) VALUES (?, ?)",
        [(key, str(value)) for key, value in sorted(values.items())],
    )


def _source_manifest(sources: Iterable[SourceFile]) -> list[dict[str, Any]]:
    return [source.manifest_item() for source in sorted(sources, key=lambda item: (item.layer, item.document_ref))]


def _parse_chunks(
    sources: list[SourceFile],
    catalog: RuleCatalog,
) -> tuple[list[Chunk], dict[str, Chunk]]:
    chunks: list[Chunk] = []
    by_ref: dict[str, Chunk] = {}
    for source in sources:
        if source.layer in {"original", "quantified"}:
            parsed, _ = parse_markdown(
                source,
                evidence_by_rule={
                    rule_id: catalog.evidence_status(catalog.rules.get(rule_id, {}).get("ruleSet"))
                    for rule_id in catalog.rules
                },
            )
            parsed = enrich_markdown_evidence(parsed, catalog)
        else:
            parsed = build_structured_chunks(source, catalog)
        for chunk in parsed:
            if chunk.citation_id in by_ref:
                raise IndexBuildError(f"duplicate citation ID generated for {chunk.document_ref}:{chunk.line_start}")
            by_ref[chunk.citation_id] = chunk
            chunks.append(chunk)
    chunks.sort(key=lambda item: (item.source_layer, item.document_ref, item.line_start, item.line_end, item.citation_id))
    return chunks, by_ref


def _rule_records(catalog: RuleCatalog, chunks: list[Chunk]) -> list[dict[str, Any]]:
    machine_citations = {
        rule_id: chunk.citation_id
        for chunk in chunks
        if chunk.source_layer == "machine-rule"
        for rule_id in chunk.rule_ids
    }
    result: list[dict[str, Any]] = []
    for rule_id in sorted(catalog.rules):
        item = catalog.rules[rule_id]
        raw = item.get("raw")
        coverage = catalog.coverage.get(rule_id)
        rule_set = item.get("ruleSet")
        evidence = catalog.evidence_summary(rule_set)
        if isinstance(raw, dict):
            lifecycle_status = str(raw.get("status", "defined"))
            implementation_status = "executable"
            evaluator = raw.get("evaluator")
            threshold_provenance = raw.get("thresholds", {}).get("provenance")
            document_refs = list(raw.get("documentRefs", []))
            evidence_refs = list(raw.get("evidenceRefs", []))
        else:
            lifecycle_status = "documented-only"
            implementation_status = str((coverage or {}).get("implementation", "documented-only"))
            evaluator = (coverage or {}).get("evaluator")
            threshold_provenance = None
            document_refs = [str((coverage or {}).get("documentRef"))] if coverage else []
            evidence_refs = list((coverage or {}).get("evidenceRefs", []))
        result.append(
            {
                "rule_id": rule_id,
                "rule_set": rule_set,
                "lifecycle_status": lifecycle_status,
                "implementation_status": implementation_status,
                "evaluator": evaluator,
                "threshold_provenance": threshold_provenance,
                "document_refs_json": canonical_json(document_refs),
                "evidence_refs_json": canonical_json(evidence_refs),
                "raw_rule_json": canonical_json(raw) if raw is not None else None,
                "coverage_json": canonical_json(coverage) if coverage is not None else None,
                "evidence_json": canonical_json(evidence),
                "machine_citation_id": machine_citations.get(rule_id),
                "evidence_status": catalog.evidence_status(rule_set),
            }
        )
    return result


def _revision_payload(
    sources: list[SourceFile],
    chunks: list[Chunk],
    catalog: RuleCatalog,
) -> dict[str, Any]:
    return {
        "index_version": INDEX_VERSION,
        "parser_version": PARSER_VERSION,
        "sources": _source_manifest(sources),
        "chunks": [chunk.canonical_item() for chunk in chunks],
        "facts": catalog.canonical_facts(),
    }


def build_index(config: KnowledgeConfig) -> dict[str, Any]:
    """Build a complete index in a temporary file and replace atomically."""

    config.index_dir.mkdir(parents=True, exist_ok=True)
    sources = discover_source_files(config)
    if not sources:
        raise IndexBuildError(f"no controlled knowledge sources found under {config.repo_root}")
    catalog = load_rule_catalog(config, sources)
    chunks, _ = _parse_chunks(sources, catalog)
    if not chunks:
        raise IndexBuildError("controlled sources produced no index chunks")

    source_manifest = _source_manifest(sources)
    source_manifest_hash = canonical_hash(source_manifest)
    revision = canonical_hash(_revision_payload(sources, chunks, catalog))
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=".knowledge.sqlite3.",
            suffix=".tmp",
            dir=config.index_dir,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        connection = _connect(temp_path)
        try:
            _create_schema(connection)
            _insert_meta(
                connection,
                {
                    "built_at": built_at,
                    "chunk_count": len(chunks),
                    "index_revision": revision,
                    "index_status": "ready",
                    "index_version": INDEX_VERSION,
                    "parser_version": PARSER_VERSION,
                    "source_file_count": len(sources),
                    "source_manifest": canonical_json(source_manifest),
                    "source_manifest_sha256": source_manifest_hash,
                    "schema_version": SCHEMA_VERSION,
                },
            )
            connection.executemany(
                """
                INSERT INTO documents(
                    source_layer, document_ref, content_sha256, byte_size, line_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        source.layer,
                        source.document_ref,
                        source.content_sha256,
                        source.byte_size,
                        source.line_count,
                    )
                    for source in sources
                ],
            )
            connection.executemany(
                """
                INSERT INTO chunks(
                    citation_id, source_layer, document_ref, heading_path_json,
                    line_start, line_end, rule_ids_json, rule_ids_csv,
                    lifecycle_status, evidence_status, content, content_sha256,
                    search_text, cjk_text, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.citation_id,
                        chunk.source_layer,
                        chunk.document_ref,
                        canonical_json(list(chunk.heading_path)),
                        chunk.line_start,
                        chunk.line_end,
                        canonical_json(list(chunk.rule_ids)),
                        "|" + "|".join(chunk.rule_ids) + "|",
                        chunk.lifecycle_status,
                        chunk.evidence_status,
                        chunk.content,
                        chunk.content_sha256,
                        chunk.search_text,
                        chunk.cjk_text,
                        chunk.authority,
                    )
                    for chunk in chunks
                ],
            )
            connection.executemany(
                """
                INSERT INTO chunks_fts(citation_id, body, cjk, heading, path, rule_ids)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.citation_id,
                        chunk.search_text,
                        chunk.cjk_text,
                        " ".join(chunk.heading_path),
                        chunk.document_ref,
                        " ".join(chunk.rule_ids),
                    )
                    for chunk in chunks
                ],
            )
            rule_rows = _rule_records(catalog, chunks)
            connection.executemany(
                """
                INSERT INTO rules(
                    rule_id, rule_set, lifecycle_status, implementation_status,
                    evaluator, threshold_provenance, document_refs_json,
                    evidence_refs_json, raw_rule_json, coverage_json,
                    evidence_json, machine_citation_id, evidence_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["rule_id"],
                        row["rule_set"],
                        row["lifecycle_status"],
                        row["implementation_status"],
                        row["evaluator"],
                        row["threshold_provenance"],
                        row["document_refs_json"],
                        row["evidence_refs_json"],
                        row["raw_rule_json"],
                        row["coverage_json"],
                        row["evidence_json"],
                        row["machine_citation_id"],
                        row["evidence_status"],
                    )
                    for row in rule_rows
                ],
            )
            connection.executemany(
                """
                INSERT INTO evidence_summaries(rule_set, evidence_status, summary_json, source_ref)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        rule_set,
                        catalog.evidence_status(rule_set),
                        canonical_json(catalog.evidence_summary(rule_set)),
                        catalog.evidence_sources.get(rule_set),
                    )
                    for rule_set in sorted(catalog.evidence_by_rule_set)
                ],
            )
            connection.executemany(
                "INSERT INTO conflicts(rule_id, conflict_json) VALUES (?, ?)",
                [
                    (rule_id, canonical_json(conflict))
                    for rule_id, conflicts in sorted(catalog.conflicts.items())
                    for conflict in conflicts
                ],
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise IndexBuildError(f"SQLite integrity check failed: {integrity}")
        finally:
            connection.close()
        os.replace(temp_path, config.index_path)
        temp_path = None
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return {
        "status": "ready",
        "index_path": config.index_path.as_posix(),
        "index_revision": revision,
        "source_manifest_sha256": source_manifest_hash,
        "source_file_count": len(sources),
        "chunk_count": len(chunks),
        "rule_count": len(catalog.rules),
    }


class KnowledgeIndex:
    """Read-only view over one built SQLite index."""

    def __init__(self, config: KnowledgeConfig):
        self.config = config

    def _meta(self, connection: sqlite3.Connection) -> dict[str, str]:
        return {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM index_meta ORDER BY key")
        }

    def status(self) -> dict[str, Any]:
        if not self.config.index_path.exists():
            return {
                "status": "missing",
                "index_path": self.config.index_path.as_posix(),
                "index_version": INDEX_VERSION,
                "warnings": ["knowledge index has not been built"],
            }
        try:
            connection = _connect(self.config.index_path, readonly=True)
            try:
                meta = self._meta(connection)
                source_count = int(meta.get("source_file_count", "0"))
                chunk_count = int(meta.get("chunk_count", "0"))
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            return {
                "status": "failed",
                "index_path": self.config.index_path.as_posix(),
                "index_version": INDEX_VERSION,
                "warnings": [f"cannot read knowledge index: {exc}"],
            }
        warnings: list[str] = []
        current_manifest_hash: str | None = None
        try:
            current_manifest_hash = canonical_hash(_source_manifest(discover_source_files(self.config)))
        except Exception as exc:
            warnings.append(str(exc))
        index_status = meta.get("index_status", "failed")
        status = "ready" if index_status == "ready" else index_status
        if current_manifest_hash is not None and current_manifest_hash != meta.get("source_manifest_sha256"):
            status = "stale"
            warnings.append("controlled source files changed; rebuild the knowledge index")
        return {
            "status": status,
            "index_path": self.config.index_path.as_posix(),
            "index_version": meta.get("index_version", INDEX_VERSION),
            "parser_version": meta.get("parser_version", PARSER_VERSION),
            "index_revision": meta.get("index_revision"),
            "source_manifest_sha256": meta.get("source_manifest_sha256"),
            "current_source_manifest_sha256": current_manifest_hash,
            "source_file_count": source_count,
            "chunk_count": chunk_count,
            "built_at": meta.get("built_at"),
            "warnings": warnings,
        }

    def open_ready(self) -> tuple[sqlite3.Connection | None, dict[str, Any]]:
        status = self.status()
        if status["status"] != "ready":
            return None, status
        try:
            return _connect(self.config.index_path, readonly=True), status
        except (OSError, sqlite3.Error) as exc:
            return None, {
                **status,
                "status": "failed",
                "warnings": [*status.get("warnings", []), f"cannot open read-only index: {exc}"],
            }

    @staticmethod
    def row_json(row: sqlite3.Row, key: str, default: Any = None) -> Any:
        value = row[key]
        if value is None:
            return default
        import json

        return json.loads(value)
