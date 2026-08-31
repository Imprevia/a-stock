"""Unified command-line interface for the trading rule platform."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from .backtest.runner import run_backtest
from .data.canonical import canonical_json_bytes, load_snapshot, validate_snapshot
from .data.providers import create_after_market_snapshot
from .evaluation.engine import evaluate_rule_set
from .evidence.bundle import create_evidence_bundle, verify_evidence_bundle
from .rules.coverage import validate_coverage, write_coverage
from .rules.registry import load_rule_sets, validate_registry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-system", description="Deterministic trading rule engineering CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    rules = commands.add_parser("rules", help="Validate registry and coverage")
    rule_commands = rules.add_subparsers(dest="rules_command", required=True)
    rule_commands.add_parser("validate")
    coverage = rule_commands.add_parser("coverage")
    coverage.add_argument("--write", action="store_true")

    snapshot = commands.add_parser("snapshot", help="Create canonical snapshots")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    create = snapshot_commands.add_parser("create")
    create.add_argument("--as-of", required=True)
    create.add_argument("--output", type=Path, required=True)

    evaluate = commands.add_parser("evaluate", help="Evaluate a fixed snapshot")
    evaluate.add_argument("--rule-set", required=True)
    evaluate.add_argument("--snapshot", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)

    backtest = commands.add_parser("backtest", help="Chronologically replay snapshots")
    backtest.add_argument("--rule-set", required=True)
    backtest.add_argument("--snapshots", type=Path, required=True)
    backtest.add_argument("--output", type=Path, required=True)
    backtest.add_argument("--transaction-cost-bps", type=float, default=10.0)

    evidence = commands.add_parser("evidence", help="Verify evidence bundles")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    verify = evidence_commands.add_parser("verify")
    verify.add_argument("path", type=Path)

    docs = commands.add_parser("docs", help="Check Markdown and registry synchronization")
    docs_commands = docs.add_subparsers(dest="docs_command", required=True)
    docs_commands.add_parser("sync-check")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _rule_set(name: str):
    rule_sets = load_rule_sets()
    if name not in rule_sets:
        raise ValueError(f"unknown rule set: {name}")
    return rule_sets[name]


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "rules" and args.rules_command == "validate":
        _print(validate_registry())
        return 0
    if args.command == "rules" and args.rules_command == "coverage":
        if args.write:
            path = write_coverage()
            _print({"written": path.as_posix()})
        else:
            _print(validate_coverage())
        return 0
    if args.command == "docs" and args.docs_command == "sync-check":
        _print(validate_coverage())
        return 0
    if args.command == "snapshot" and args.snapshot_command == "create":
        as_of = date.fromisoformat(args.as_of)
        snapshot = create_after_market_snapshot(as_of)
        validate_snapshot(snapshot)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json_bytes(snapshot))
        _print({"output": args.output.as_posix(), "status": snapshot["status"]})
        return 0
    if args.command == "evaluate":
        rule_set = _rule_set(args.rule_set)
        snapshot = load_snapshot(args.snapshot)
        result = evaluate_rule_set(rule_set, snapshot)
        manifest = create_evidence_bundle(args.output, snapshot, result, rule_set)
        _print({"manifest": manifest.as_posix(), "status": snapshot["status"], "resultHash": result["resultHash"]})
        return 0
    if args.command == "backtest":
        rule_set = _rule_set(args.rule_set)
        paths = sorted(args.snapshots.glob("*.json"))
        result = run_backtest(paths, rule_set, transaction_cost_bps=args.transaction_cost_bps)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json_bytes(result))
        _print({"output": args.output.as_posix(), "days": result["availableTradingDays"], "validationEligible": result["validationEligible"]})
        return 0
    if args.command == "evidence" and args.evidence_command == "verify":
        _print(verify_evidence_bundle(args.path))
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
