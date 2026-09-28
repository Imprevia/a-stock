"""Command-line entry points for building and querying the local knowledge index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import KnowledgeConfig
from .index import KnowledgeIndex, build_index
from .service import KnowledgeService


def _scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, help="repository root; defaults to this checkout")
    parser.add_argument("--index-dir", type=Path, help="ignored SQLite index directory inside repo")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-knowledge", description="Offline trading knowledge index and MCP backend")
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="build or inspect the local SQLite index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    build = index_commands.add_parser("build", help="rebuild the controlled knowledge index")
    _scope(build)
    status = index_commands.add_parser("status", help="show index and source freshness")
    _scope(status)

    search = commands.add_parser("search", help="search indexed knowledge")
    _scope(search)
    search.add_argument("query")
    search.add_argument("--source-layer")
    search.add_argument("--chapter")
    search.add_argument("--document-ref")
    search.add_argument("--rule-id")
    search.add_argument("--rule-status")
    search.add_argument("--evidence-status")
    search.add_argument("--limit", type=int, default=8)

    excerpt = commands.add_parser("excerpt", help="read an indexed source excerpt")
    _scope(excerpt)
    excerpt.add_argument("--citation-id")
    excerpt.add_argument("--document-ref")
    excerpt.add_argument("--line-start", type=int)
    excerpt.add_argument("--line-end", type=int)
    excerpt.add_argument("--heading-path")

    rule = commands.add_parser("rule", help="read one rule record")
    _scope(rule)
    rule.add_argument("rule_id")

    evidence = commands.add_parser("evidence", help="read evidence status")
    _scope(evidence)
    evidence.add_argument("--rule-set")
    evidence.add_argument("--rule-id")
    evidence.add_argument("--document-ref")

    return parser


def _config(args: argparse.Namespace) -> KnowledgeConfig:
    return KnowledgeConfig.from_root(args.repo_root, args.index_dir)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "index" and args.index_command == "build":
        _print(build_index(_config(args)))
        return 0
    if args.command == "index" and args.index_command == "status":
        _print(KnowledgeIndex(_config(args)).status())
        return 0

    service = KnowledgeService(_config(args))
    if args.command == "search":
        _print(
            service.search_trading_knowledge(
                query=args.query,
                source_layer=args.source_layer,
                chapter=args.chapter,
                document_ref=args.document_ref,
                rule_id=args.rule_id,
                rule_status=args.rule_status,
                evidence_status=args.evidence_status,
                limit=args.limit,
            )
        )
        return 0
    if args.command == "excerpt":
        _print(
            service.get_source_excerpt(
                citation_id=args.citation_id,
                document_ref=args.document_ref,
                line_start=args.line_start,
                line_end=args.line_end,
                heading_path=args.heading_path,
            )
        )
        return 0
    if args.command == "rule":
        _print(service.get_rule(args.rule_id))
        return 0
    if args.command == "evidence":
        _print(
            service.get_evidence_status(
                rule_set=args.rule_set,
                rule_id=args.rule_id,
                document_ref=args.document_ref,
            )
        )
        return 0
    raise RuntimeError("unhandled command")


def main() -> None:
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
