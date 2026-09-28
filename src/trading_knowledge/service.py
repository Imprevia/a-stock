"""Read-only JSON service used by CLI and MCP tools."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from .config import SOURCE_AUTHORITY, SOURCE_LAYERS, KnowledgeConfig
from .index import KnowledgeIndex
from .text import RULE_ID_RE, fts_match_expression, sha256_bytes


class KnowledgeService:
    """Pure read-only operations over a built knowledge index."""

    def __init__(self, config: KnowledgeConfig):
        self.config = config
        self.index = KnowledgeIndex(config)

    def search_trading_knowledge(
        self,
        query: str,
        source_layer: str | None = None,
        chapter: str | None = None,
        document_ref: str | None = None,
        rule_id: str | None = None,
        rule_status: str | None = None,
        evidence_status: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        invalid = self._validate_search_inputs(
            query=query,
            source_layer=source_layer,
            document_ref=document_ref,
            rule_id=rule_id,
            limit=limit,
        )
        if invalid:
            return invalid
        connection, status = self.index.open_ready()
        if connection is None:
            return self._not_ready(status, results=[])
        try:
            filters = {
                "source_layer": source_layer,
                "chapter": chapter,
                "document_ref": document_ref,
                "rule_id": rule_id,
                "rule_status": rule_status,
                "evidence_status": evidence_status,
                "limit": limit,
            }
            exact_rule = (rule_id or _extract_first_rule_id(query))
            rows = self._search_rows(
                connection,
                query=query,
                exact_rule=exact_rule,
                source_layer=source_layer,
                document_ref=document_ref,
                rule_status=rule_status,
                evidence_status=evidence_status,
                limit=max(limit * 3, 20),
            )
            rows = [
                row
                for row in rows
                if self._row_matches_chapter(row, chapter)
            ][:limit]
            results = [self._result_from_row(connection, row, query_rule=exact_rule) for row in rows]
            citations = [result["citation"] for result in results]
            warnings = sorted({warning for result in results for warning in result.get("warnings", [])})
            response_status = "ok" if results else "no-match"
            missing_inputs = [] if results else ["matching evidence"]
            return {
                "status": response_status,
                "query": query,
                "filters": filters,
                "results": results,
                "citations": citations,
                "warnings": warnings,
                "missing_inputs": missing_inputs,
                "index_revision": status.get("index_revision"),
            }
        finally:
            connection.close()

    def get_source_excerpt(
        self,
        citation_id: str | None = None,
        document_ref: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        heading_path: str | None = None,
    ) -> dict[str, Any]:
        if not citation_id:
            invalid = self._validate_excerpt_path(document_ref, line_start, line_end)
            if invalid:
                return invalid
        connection, status = self.index.open_ready()
        if connection is None:
            return self._not_ready(status, record=None)
        try:
            if citation_id:
                row = connection.execute("SELECT * FROM chunks WHERE citation_id = ?", (citation_id,)).fetchone()
                if row is None:
                    return self._base("no-match", status, record=None, warnings=["citation_id not found"])
                document_ref = row["document_ref"]
                line_start = int(row["line_start"])
                line_end = int(row["line_end"])
                heading = json.loads(row["heading_path_json"])
                expected_content_sha = row["content_sha256"]
                source_layer = row["source_layer"]
            else:
                assert document_ref is not None and line_start is not None and line_end is not None
                row = connection.execute(
                    """
                    SELECT * FROM documents
                    WHERE document_ref = ?
                    ORDER BY CASE source_layer
                        WHEN 'machine-rule' THEN 0
                        WHEN 'quantified' THEN 1
                        WHEN 'original' THEN 2
                        ELSE 3
                    END
                    LIMIT 1
                    """,
                    (document_ref,),
                ).fetchone()
                if row is None:
                    return self._base("invalid", status, record=None, warnings=["document_ref is not registered in the index"])
                heading = [part for part in [heading_path] if part]
                expected_content_sha = None
                source_layer = row["source_layer"]

            assert document_ref is not None and line_start is not None and line_end is not None
            doc = connection.execute(
                "SELECT * FROM documents WHERE source_layer = ? AND document_ref = ?",
                (source_layer, document_ref),
            ).fetchone()
            if doc is None:
                return self._base("invalid", status, record=None, warnings=["source document is not registered"])
            source_path = self.config.repo_root / PurePosixPath(document_ref)
            try:
                source_path.resolve().relative_to(self.config.repo_root)
            except ValueError:
                return self._base("invalid", status, record=None, warnings=["source path resolves outside repository root"])
            if source_path.is_symlink():
                return self._base("invalid", status, record=None, warnings=["symlinked source paths are not allowed"])
            current_sha = sha256_bytes(source_path.read_bytes())
            if current_sha != doc["content_sha256"]:
                return self._base(
                    "stale",
                    status,
                    record=None,
                    warnings=["source file hash changed; rebuild the knowledge index"],
                    missing_inputs=["fresh knowledge index"],
                )
            lines = source_path.read_text(encoding="utf-8").splitlines()
            if line_start < 1 or line_end < line_start or line_end > len(lines):
                return self._base("invalid", status, record=None, warnings=["line range is outside the source document"])
            content = "\n".join(lines[line_start - 1 : line_end])
            if expected_content_sha is not None and sha256_bytes(content.encode("utf-8")) != expected_content_sha:
                return self._base(
                    "stale",
                    status,
                    record=None,
                    warnings=["source excerpt hash changed; rebuild the knowledge index"],
                    missing_inputs=["fresh source excerpt"],
                )
            citation = {
                "citation_id": citation_id,
                "source_layer": source_layer,
                "document_ref": document_ref,
                "heading_path": heading,
                "line_start": line_start,
                "line_end": line_end,
                "content_sha256": sha256_bytes(content.encode("utf-8")),
            }
            return self._base(
                "ok",
                status,
                record={"content": content, "citation": citation},
                citations=[citation],
            )
        except (OSError, UnicodeError) as exc:
            return self._base("failed", status, record=None, warnings=[f"cannot read source excerpt: {exc}"])
        finally:
            connection.close()

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        normalized = (rule_id or "").upper()
        if not RULE_ID_RE.fullmatch(normalized):
            return {"status": "invalid", "warnings": ["rule_id must match QTS-00-00-00"], "record": None}
        connection, status = self.index.open_ready()
        if connection is None:
            return self._not_ready(status, record=None)
        try:
            row = connection.execute("SELECT * FROM rules WHERE rule_id = ?", (normalized,)).fetchone()
            if row is None:
                return self._base("no-match", status, record=None, warnings=["rule_id not found"])
            citations = self._rule_citations(connection, normalized)
            conflicts = self._conflict_warnings(connection, normalized)
            evidence = json.loads(row["evidence_json"])
            raw_rule = json.loads(row["raw_rule_json"]) if row["raw_rule_json"] else None
            coverage = json.loads(row["coverage_json"]) if row["coverage_json"] else None
            warning_values = [item.get("warning", "") for item in conflicts if item.get("warning")]
            if row["lifecycle_status"] != "validated":
                warning_values.append(f"{normalized} lifecycle_status={row['lifecycle_status']}，不得解释为已验证收益优势")
            if row["evidence_status"] != "ok":
                warning_values.append(f"{normalized} evidence_status={row['evidence_status']}，没有完整验证证据")
            record = {
                "rule_id": normalized,
                "rule_set": row["rule_set"],
                "lifecycle_status": row["lifecycle_status"],
                "implementation_status": row["implementation_status"],
                "evaluator": row["evaluator"],
                "threshold_provenance": row["threshold_provenance"],
                "document_refs": json.loads(row["document_refs_json"]),
                "evidence_refs": json.loads(row["evidence_refs_json"]),
                "raw_rule": raw_rule,
                "coverage": coverage,
                "evidence_status": row["evidence_status"],
                "evidence": evidence,
                "conflicts": conflicts,
            }
            return self._base(
                "ok",
                status,
                record=record,
                citations=citations,
                warnings=sorted(set(warning_values)),
            )
        finally:
            connection.close()

    def get_evidence_status(
        self,
        rule_set: str | None = None,
        rule_id: str | None = None,
        document_ref: str | None = None,
    ) -> dict[str, Any]:
        connection, status = self.index.open_ready()
        if connection is None:
            return self._not_ready(status, record=None)
        try:
            warnings: list[str] = []
            records: list[dict[str, Any]] = []
            if rule_id:
                normalized = rule_id.upper()
                if not RULE_ID_RE.fullmatch(normalized):
                    return self._base("invalid", status, record=None, warnings=["rule_id must match QTS-00-00-00"])
                row = connection.execute("SELECT * FROM rules WHERE rule_id = ?", (normalized,)).fetchone()
                if row is None:
                    return self._base("no-match", status, record=None, warnings=["rule_id not found"])
                records.append(self._evidence_record_from_rule_row(row))
            elif rule_set:
                rows = connection.execute(
                    "SELECT * FROM evidence_summaries WHERE rule_set = ?",
                    (rule_set,),
                ).fetchall()
                records.extend(self._evidence_record_from_summary(row) for row in rows)
            elif document_ref:
                if self._unsafe_ref(document_ref):
                    return self._base("invalid", status, record=None, warnings=["document_ref is not a safe repository-relative path"])
                rows = connection.execute(
                    """
                    SELECT * FROM rules
                    WHERE document_refs_json LIKE ?
                    ORDER BY rule_id
                    """,
                    (f"%{document_ref}%",),
                ).fetchall()
                records.extend(self._evidence_record_from_rule_row(row) for row in rows)
            else:
                rows = connection.execute("SELECT * FROM evidence_summaries ORDER BY rule_set").fetchall()
                records.extend(self._evidence_record_from_summary(row) for row in rows)
            if not records:
                return self._base("no-match", status, record=None, warnings=["no evidence status matched the filters"])
            evidence_status = _combined_evidence_status([record["evidence_status"] for record in records])
            response_status = "ok" if evidence_status == "ok" else evidence_status
            if evidence_status != "ok":
                warnings.append("证据不足或降级：不能把规则解释为 validated 收益结论")
            citations = self._evidence_citations(connection, rule_set, rule_id, records)
            return self._base(
                response_status,
                status,
                record={
                    "filters": {
                        "rule_set": rule_set,
                        "rule_id": rule_id,
                        "document_ref": document_ref,
                    },
                    "evidence_status": evidence_status,
                    "records": records,
                },
                warnings=warnings,
                missing_inputs=["latestEvidence"] if evidence_status == "insufficient" else [],
                citations=citations,
            )
        finally:
            connection.close()

    def get_index_status(self) -> dict[str, Any]:
        status = self.index.status()
        return {
            "status": status["status"],
            "record": status,
            "warnings": status.get("warnings", []),
            "missing_inputs": ["fresh knowledge index"] if status["status"] in {"missing", "stale", "failed"} else [],
            "index_revision": status.get("index_revision"),
        }

    def _search_rows(
        self,
        connection: sqlite3.Connection,
        query: str,
        exact_rule: str | None,
        source_layer: str | None,
        document_ref: str | None,
        rule_status: str | None,
        evidence_status: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_layer:
            clauses.append("c.source_layer = ?")
            params.append(source_layer)
        if document_ref:
            clauses.append("c.document_ref = ?")
            params.append(document_ref)
        if rule_status:
            clauses.append("c.lifecycle_status = ?")
            params.append(rule_status)
        if evidence_status:
            clauses.append("c.evidence_status = ?")
            params.append(evidence_status)
        if exact_rule:
            clauses.append("c.rule_ids_csv LIKE ?")
            params.append(f"%|{exact_rule}|%")
        filter_clauses = [
            clause for clause in clauses if not (exact_rule and clause == "c.rule_ids_csv LIKE ?")
        ]
        filter_params = [
            param
            for clause, param in zip(clauses, params)
            if not (exact_rule and clause == "c.rule_ids_csv LIKE ?")
        ]
        filter_where = (" AND " + " AND ".join(filter_clauses)) if filter_clauses else ""
        exact_rows: list[sqlite3.Row] = []
        if exact_rule:
            exact_rows = connection.execute(
                f"""
                SELECT c.*, -100000.0 AS rank_score
                FROM chunks c
                WHERE c.rule_ids_csv LIKE ? {filter_where}
                ORDER BY CASE c.source_layer
                    WHEN 'machine-rule' THEN 0
                    WHEN 'coverage' THEN 1
                    WHEN 'quantified' THEN 2
                    WHEN 'evidence' THEN 3
                    ELSE 4
                END, c.document_ref, c.line_start
                LIMIT ?
                """,
                [f"%|{exact_rule}|%", *filter_params, limit],
            ).fetchall()
        match = fts_match_expression(query)
        fts_rows: list[sqlite3.Row] = []
        if match:
            base_where = "WHERE chunks_fts MATCH ?"
            fts_params: list[Any] = [match]
            if filter_clauses:
                base_where += " AND " + " AND ".join(filter_clauses)
                fts_params.extend(filter_params)
            fts_rows = connection.execute(
                f"""
                SELECT c.*, bm25(chunks_fts) AS rank_score
                FROM chunks_fts
                JOIN chunks c ON c.citation_id = chunks_fts.citation_id
                {base_where}
                ORDER BY rank_score, c.document_ref, c.line_start
                LIMIT ?
                """,
                [*fts_params, limit],
            ).fetchall()
        merged: dict[str, sqlite3.Row] = {}
        for row in exact_rows:
            merged[row["citation_id"]] = row
        for row in fts_rows:
            merged.setdefault(row["citation_id"], row)
        return sorted(
            merged.values(),
            key=lambda row: (
                float(row["rank_score"]),
                0 if exact_rule and f"|{exact_rule}|" in row["rule_ids_csv"] else 1,
                _source_priority(row["source_layer"]),
                row["document_ref"],
                row["line_start"],
            ),
        )

    def _result_from_row(self, connection: sqlite3.Connection, row: sqlite3.Row, query_rule: str | None) -> dict[str, Any]:
        rule_ids = json.loads(row["rule_ids_json"])
        citation = self._citation_from_row(row)
        warnings: list[str] = []
        for rule_id in rule_ids:
            warnings.extend(item.get("warning", "") for item in self._conflict_warnings(connection, rule_id) if item.get("warning"))
        if row["lifecycle_status"] in {"defined", "draft", "documented-only", "needs-backtest"}:
            warnings.append(f"lifecycle_status={row['lifecycle_status']}，不能视为已验证收益结论")
        if row["evidence_status"] != "ok":
            warnings.append(f"evidence_status={row['evidence_status']}，证据不足或未完成验证")
        return {
            "citation_id": row["citation_id"],
            "source_layer": row["source_layer"],
            "authority": row["authority"],
            "document_ref": row["document_ref"],
            "heading_path": json.loads(row["heading_path_json"]),
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "rule_ids": rule_ids,
            "matched_rule_id": query_rule if query_rule in rule_ids else None,
            "lifecycle_status": row["lifecycle_status"],
            "evidence_status": row["evidence_status"],
            "excerpt": _shorten(row["content"]),
            "content_sha256": row["content_sha256"],
            "warnings": sorted(set(warnings)),
            "citation": citation,
        }

    def _citation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "citation_id": row["citation_id"],
            "source_layer": row["source_layer"],
            "document_ref": row["document_ref"],
            "heading_path": json.loads(row["heading_path_json"]),
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "content_sha256": row["content_sha256"],
        }

    def _rule_citations(self, connection: sqlite3.Connection, rule_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT * FROM chunks
            WHERE rule_ids_csv LIKE ?
            ORDER BY CASE source_layer
                WHEN 'machine-rule' THEN 0
                WHEN 'coverage' THEN 1
                WHEN 'quantified' THEN 2
                WHEN 'evidence' THEN 3
                ELSE 4
            END, document_ref, line_start
            LIMIT 20
            """,
            (f"%|{rule_id}|%",),
        ).fetchall()
        return [self._citation_from_row(row) for row in rows]

    def _evidence_citations(
        self,
        connection: sqlite3.Connection,
        rule_set: str | None,
        rule_id: str | None,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if rule_id:
            return self._rule_citations(connection, rule_id)
        if rule_set:
            rows = connection.execute(
                """
                SELECT * FROM chunks
                WHERE source_layer = 'evidence' AND heading_path_json LIKE ?
                ORDER BY document_ref, line_start
                LIMIT 20
                """,
                (f'%"{rule_set}"%',),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM chunks
                WHERE source_layer = 'evidence'
                ORDER BY document_ref, line_start
                LIMIT 20
                """
            ).fetchall()
        if rows:
            return [self._citation_from_row(row) for row in rows]
        return [
            {
                "citation_id": None,
                "source_layer": "evidence",
                "document_ref": record.get("source_ref"),
                "heading_path": [],
                "line_start": None,
                "line_end": None,
                "content_sha256": None,
            }
            for record in records
            if record.get("source_ref")
        ]

    def _conflict_warnings(self, connection: sqlite3.Connection, rule_id: str) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT conflict_json FROM conflicts WHERE rule_id = ?", (rule_id,)).fetchall()
        return [json.loads(row["conflict_json"]) for row in rows]

    def _validate_search_inputs(
        self,
        query: str,
        source_layer: str | None,
        document_ref: str | None,
        rule_id: str | None,
        limit: int,
    ) -> dict[str, Any] | None:
        warnings = []
        if not query or not query.strip():
            warnings.append("query must not be empty")
        if source_layer and source_layer not in SOURCE_LAYERS:
            warnings.append(f"source_layer must be one of {', '.join(SOURCE_LAYERS)}")
        if document_ref and self._unsafe_ref(document_ref):
            warnings.append("document_ref is not a safe repository-relative path")
        if rule_id and not RULE_ID_RE.fullmatch(rule_id.upper()):
            warnings.append("rule_id must match QTS-00-00-00")
        if limit < 1 or limit > 50:
            warnings.append("limit must be between 1 and 50")
        if warnings:
            return {
                "status": "invalid",
                "results": [],
                "citations": [],
                "warnings": warnings,
                "missing_inputs": [],
                "index_revision": None,
            }
        return None

    def _validate_excerpt_path(
        self,
        document_ref: str | None,
        line_start: int | None,
        line_end: int | None,
    ) -> dict[str, Any] | None:
        warnings = []
        if not document_ref:
            warnings.append("document_ref is required when citation_id is not provided")
        elif self._unsafe_ref(document_ref):
            warnings.append("document_ref is not a safe repository-relative path")
        if line_start is None or line_end is None:
            warnings.append("line_start and line_end are required when citation_id is not provided")
        elif line_start < 1 or line_end < line_start:
            warnings.append("line range must be positive and ordered")
        elif line_end - line_start > 240:
            warnings.append("line range is too large; request a narrower excerpt")
        if warnings:
            return {"status": "invalid", "record": None, "citations": [], "warnings": warnings, "missing_inputs": []}
        return None

    def _unsafe_ref(self, document_ref: str) -> bool:
        if "\x00" in document_ref or "\\" in document_ref:
            return True
        path = PurePosixPath(document_ref)
        return path.is_absolute() or ".." in path.parts or not document_ref.strip()

    def _row_matches_chapter(self, row: sqlite3.Row, chapter: str | None) -> bool:
        if not chapter:
            return True
        normalized = chapter.strip("/")
        parts = PurePosixPath(row["document_ref"]).parts
        return normalized in parts or row["document_ref"].startswith(normalized + "/")

    def _evidence_record_from_rule_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "rule_id": row["rule_id"],
            "rule_set": row["rule_set"],
            "lifecycle_status": row["lifecycle_status"],
            "implementation_status": row["implementation_status"],
            "evidence_status": row["evidence_status"],
            "evidence": json.loads(row["evidence_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
        }

    def _evidence_record_from_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "rule_set": row["rule_set"],
            "evidence_status": row["evidence_status"],
            "evidence": json.loads(row["summary_json"]),
            "source_ref": row["source_ref"],
        }

    def _not_ready(self, status: dict[str, Any], **payload: Any) -> dict[str, Any]:
        return self._base(
            status["status"],
            status,
            warnings=status.get("warnings", []),
            missing_inputs=["fresh knowledge index"],
            **payload,
        )

    def _base(
        self,
        response_status: str,
        index_status: dict[str, Any],
        warnings: list[str] | None = None,
        missing_inputs: list[str] | None = None,
        citations: list[dict[str, Any]] | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        result = {
            "status": response_status,
            "warnings": warnings or [],
            "missing_inputs": missing_inputs or [],
            "citations": citations or [],
            "index_revision": index_status.get("index_revision"),
        }
        result.update(payload)
        return result


def _extract_first_rule_id(query: str) -> str | None:
    match = RULE_ID_RE.search(query or "")
    return match.group(0).upper() if match else None


def _shorten(value: str, limit: int = 1200) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _source_priority(source_layer: str) -> int:
    return {
        "machine-rule": 0,
        "coverage": 1,
        "evidence": 2,
        "quantified": 3,
        "original": 4,
    }.get(source_layer, 9)


def _combined_evidence_status(statuses: list[str]) -> str:
    order = {"failed": 5, "insufficient": 4, "degraded": 3, "unverified": 2, "ok": 1}
    return max(statuses, key=lambda value: order.get(value, 4))
