"""Command-line operations for market environment data."""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Sequence

from .refresh import SUPPORTED_SNAPSHOT_DATASETS, SnapshotRefresher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.market_environment.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshots = commands.add_parser("snapshots", help="manage persistent market snapshots")
    snapshot_commands = snapshots.add_subparsers(dest="snapshot_command", required=True)
    refresh = snapshot_commands.add_parser("refresh", help="refresh after-market dataset snapshots")
    refresh.add_argument("--as-of", required=True, type=date.fromisoformat)
    refresh.add_argument(
        "--dataset",
        action="append",
        choices=SUPPORTED_SNAPSHOT_DATASETS,
        dest="datasets",
        help="refresh one dataset; repeat to select multiple datasets",
    )
    refresh.add_argument("--force", action="store_true", help="allow explicit local diagnostic refresh")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "snapshots" and args.snapshot_command == "refresh":
        try:
            result = SnapshotRefresher().refresh(args.as_of, args.datasets, force=args.force)
        except ValueError as exc:
            print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "ok" else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

