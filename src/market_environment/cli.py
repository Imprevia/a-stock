"""Command-line operations for market environment data."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from .collection import SUPPORTED_COLLECTION_DATASETS, CollectionCoordinator
from .refresh import MARKET_TIME_ZONE, settlement_time


def _add_dataset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset",
        action="append",
        choices=SUPPORTED_COLLECTION_DATASETS,
        dest="datasets",
        help="refresh one dataset; repeat to select multiple datasets",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.market_environment.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshots = commands.add_parser("snapshots", help="manage persistent market snapshots")
    snapshot_commands = snapshots.add_subparsers(dest="snapshot_command", required=True)
    refresh = snapshot_commands.add_parser("refresh", help="refresh after-market dataset snapshots")
    refresh.add_argument("--as-of", required=True, type=date.fromisoformat)
    _add_dataset_arguments(refresh)
    refresh.add_argument("--force", action="store_true", help="allow explicit local diagnostic refresh")
    scheduled_refresh = snapshot_commands.add_parser(
        "scheduled-refresh",
        help="refresh the current Shanghai market date after settlement",
    )
    _add_dataset_arguments(scheduled_refresh)
    return parser


def _collection_payload(result: Any, **extra: Any) -> dict[str, Any]:
    return {
        "runId": result.run.run_id,
        "asOf": result.run.as_of.isoformat(),
        "status": result.run.status,
        **extra,
        "datasets": [
            {
                "taskId": task.task_id,
                "dataset": task.dataset,
                "source": task.source,
                "observations": task.observations,
                "durationMs": task.duration_ms,
                "status": task.status,
                "warning": task.warning,
            }
            for task in result.tasks
        ],
    }


def _market_now(now: Callable[[], datetime] | None = None) -> datetime:
    current = now() if now is not None else datetime.now(MARKET_TIME_ZONE)
    if current.tzinfo is None:
        return current.replace(tzinfo=MARKET_TIME_ZONE)
    return current.astimezone(MARKET_TIME_ZONE)


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main(
    argv: Sequence[str] | None = None,
    *,
    coordinator: CollectionCoordinator | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "snapshots" and args.snapshot_command == "refresh":
        try:
            result = (coordinator or CollectionCoordinator()).collect(args.as_of, args.datasets)
        except ValueError as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        payload = _collection_payload(result, forced=args.force)
        _print_payload(payload)
        return 0 if result.run.status == "success" else 2
    if args.command == "snapshots" and args.snapshot_command == "scheduled-refresh":
        current = _market_now(now)
        as_of = current.date()
        selected = tuple(args.datasets or SUPPORTED_COLLECTION_DATASETS)

        # Weekend invocations are harmless no-ops; weekday holidays remain auditable provider failures.
        if current.weekday() >= 5:
            _print_payload(
                {
                    "trigger": "scheduled",
                    "asOf": as_of.isoformat(),
                    "status": "skipped",
                    "reason": "weekend",
                    "datasets": [],
                }
            )
            return 0

        try:
            if current.time().replace(tzinfo=None) < settlement_time():
                raise ValueError("scheduled refresh is only allowed after the configured settlement time")
            active_coordinator = coordinator or CollectionCoordinator(now=lambda: current)
            result = active_coordinator.collect(as_of, selected)
        except ValueError as exc:
            _print_payload(
                {
                    "trigger": "scheduled",
                    "asOf": as_of.isoformat(),
                    "status": "rejected",
                    "error": str(exc),
                    "datasets": [],
                }
            )
            return 2

        _print_payload(_collection_payload(result, trigger="scheduled"))
        return 0 if result.run.status == "success" else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

