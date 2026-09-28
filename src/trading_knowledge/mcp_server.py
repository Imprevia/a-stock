"""MCP stdio server exposing five read-only trading knowledge tools."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

from .config import KnowledgeConfig
from .service import KnowledgeService


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def create_server(service: KnowledgeService) -> MCPServer:
    server = MCPServer(
        name="trading-knowledge",
        title="Trading Knowledge",
        description="Local read-only trading system knowledge index for Codex.",
        version="1.0.0",
    )

    @server.tool(
        name="search_trading_knowledge",
        description="Search controlled trading knowledge sources with optional source, path, rule and status filters.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def search_trading_knowledge(
        query: str,
        source_layer: str | None = None,
        chapter: str | None = None,
        document_ref: str | None = None,
        rule_id: str | None = None,
        rule_status: str | None = None,
        evidence_status: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return service.search_trading_knowledge(
            query=query,
            source_layer=source_layer,
            chapter=chapter,
            document_ref=document_ref,
            rule_id=rule_id,
            rule_status=rule_status,
            evidence_status=evidence_status,
            limit=limit,
        )

    @server.tool(
        name="get_source_excerpt",
        description="Read an indexed source excerpt by citation_id, or by registered document_ref and line range.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_source_excerpt(
        citation_id: str | None = None,
        document_ref: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        heading_path: str | None = None,
    ) -> dict[str, Any]:
        return service.get_source_excerpt(
            citation_id=citation_id,
            document_ref=document_ref,
            line_start=line_start,
            line_end=line_end,
            heading_path=heading_path,
        )

    @server.tool(
        name="get_rule",
        description="Return one QTS rule with YAML facts, coverage, evidence status and source citations.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_rule(rule_id: str) -> dict[str, Any]:
        return service.get_rule(rule_id)

    @server.tool(
        name="get_evidence_status",
        description="Return Git evidence-index status by rule_set, rule_id, document_ref, or all rule sets.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_evidence_status(
        rule_set: str | None = None,
        rule_id: str | None = None,
        document_ref: str | None = None,
    ) -> dict[str, Any]:
        return service.get_evidence_status(rule_set=rule_set, rule_id=rule_id, document_ref=document_ref)

    @server.tool(
        name="get_index_status",
        description="Return local knowledge index version, source freshness, counts and warnings.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_index_status() -> dict[str, Any]:
        return service.get_index_status()

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the trading knowledge MCP stdio server")
    parser.add_argument("--repo-root", type=Path, help="repository root; defaults to this checkout")
    parser.add_argument("--index-dir", type=Path, help="ignored SQLite index directory inside repo")
    return parser


def main() -> None:
    args = _parser().parse_args()
    config = KnowledgeConfig.from_root(args.repo_root, args.index_dir)
    server = create_server(KnowledgeService(config))
    server.run("stdio")


if __name__ == "__main__":
    main()
