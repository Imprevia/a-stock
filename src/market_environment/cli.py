"""Command-line operations for market environment data."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from typing import Any

from .collection import SUPPORTED_COLLECTION_DATASETS, CollectionCoordinator
from .fuyao_market import FuyaoMarketAdapter, FuyaoMarketClient
from .provider_capability import ProviderCapabilityReport
from .date_relabel import relabel_date, rollback_date_relabel
from .postgres_migration import backup_sqlite, import_sqlite
from .refresh import MARKET_TIME_ZONE, effective_market_date, settlement_time
from .snapshot_store import SnapshotStore


def _add_dataset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset",
        action="append",
        choices=SUPPORTED_COLLECTION_DATASETS,
        dest="datasets",
        help="refresh one dataset; repeat to select multiple datasets",
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.market_environment.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshots = commands.add_parser("snapshots", help="manage persistent market snapshots")
    snapshot_commands = snapshots.add_subparsers(dest="snapshot_command", required=True)
    refresh = snapshot_commands.add_parser("refresh", help="refresh after-market dataset snapshots")
    refresh.add_argument("--as-of", required=True, type=date.fromisoformat)
    _add_dataset_arguments(refresh)
    refresh.add_argument("--force", action="store_true", help="allow explicit local diagnostic refresh")
    refresh.add_argument(
        "--history-sessions",
        type=_positive_int,
        default=1,
        help="collect the latest N confirmed sessions; values above 1 require --dataset limits",
    )
    scheduled_refresh = snapshot_commands.add_parser(
        "scheduled-refresh",
        help="refresh the current Shanghai market date after settlement",
    )
    _add_dataset_arguments(scheduled_refresh)
    relabel = snapshot_commands.add_parser(
        "relabel-date",
        aliases=["relabel", "migrate-date", "date-relabel", "migrate"],
        help="relabel an explicitly selected SQLite or PostgreSQL date (dry-run by default)",
    )
    relabel.add_argument("--from", "--source", "--source-as-of", "--source-date", "--from-date", dest="source_as_of", required=True, type=date.fromisoformat)
    relabel.add_argument("--to", "--target", "--target-as-of", "--target-date", "--to-date", dest="target_as_of", required=True, type=date.fromisoformat)
    relabel.add_argument("--path", default=None, help="path to an isolated SQLite copy")
    relabel.add_argument(
        "--database-url",
        default=None,
        help="explicit PostgreSQL URL for a controlled date relabel (never inferred from SQLite path)",
    )
    relabel.add_argument("--apply", action="store_true", help="commit the relabel; omitted means dry-run")
    relabel.add_argument("--dry-run", action="store_true", help="explicitly request the default read-only plan")
    relabel.add_argument(
        "--conflict",
        "--conflict-policy",
        dest="conflict_policy",
        choices=("reject", "skip", "overwrite"),
        default="reject",
        help="destination conflict policy (reject is safest)",
    )
    relabel.add_argument("--operator", default="local", help="audit operator label")
    rollback = snapshot_commands.add_parser(
        "relabel-rollback",
        aliases=["rollback-relabel"],
        help="restore a previously applied date relabel in the selected backend (dry-run by default)",
    )
    rollback.add_argument("--audit-id", required=True)
    rollback.add_argument("--path", default=None, help="path to the isolated SQLite copy")
    rollback.add_argument(
        "--database-url",
        default=None,
        help="explicit PostgreSQL URL for a controlled relabel rollback",
    )
    rollback.add_argument("--apply", action="store_true", help="commit rollback; omitted means dry-run")
    rollback.add_argument("--dry-run", action="store_true", help="explicitly request the default read-only plan")
    database = commands.add_parser("database", help="manage PostgreSQL runtime storage")
    database_commands = database.add_subparsers(dest="database_command", required=True)
    migrate = database_commands.add_parser("migrate", help="import an isolated SQLite copy into PostgreSQL")
    migrate.add_argument("--source", required=True, help="read-only SQLite source path")
    migrate.add_argument("--database-url", default=None, help="PostgreSQL URL (defaults to environment)")
    migrate.add_argument("--backup", default=None, help="optional non-existing before-image destination")
    migrate.add_argument("--apply", action="store_true", help="commit the import; omitted means dry-run")
    fuyao = commands.add_parser("fuyao", help="audit Fuyao market-data capability")
    fuyao_commands = fuyao.add_subparsers(dest="fuyao_command", required=True)
    probe = fuyao_commands.add_parser("capability-probe", help="run a deterministic fixture probe")
    probe.add_argument("--fixture", required=True, help="redacted JSON fixture path")
    probe.add_argument("--as-of", required=True, type=date.fromisoformat)
    probe.add_argument("--output", default=None, help="optional redacted report output path")
    probe.add_argument("--path", default=None, help="optional isolated SQLite store for reports")
    real = fuyao_commands.add_parser("real-probe", help="run an explicitly authorized local provider probe")
    real.add_argument("--as-of", required=True, type=date.fromisoformat)
    real.add_argument("--output", required=True, help="redacted report output path")
    real.add_argument("--path", required=True, help="isolated SQLite store path")
    real.add_argument("--allow-real", action="store_true", help="required explicit authorization")
    return parser


def _capability_report_from_result(dataset: str, result: Any, as_of: date, *, revision: str = "fuyao-market-v1") -> ProviderCapabilityReport:
    status = "eligible" if getattr(result, "status", "insufficient") == "ok" else "ineligible"
    quality = getattr(result, "quality", {}) or {}
    warnings = tuple(str(item) for item in getattr(result, "warnings", ()) or quality.get("warnings", ()))
    if status != "eligible" and not warnings:
        warnings = ("fixture contract evidence is incomplete",)
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset=dataset,
        revision=revision,
        status=status,
        endpoint=f"fixture:{dataset}",
        field_coverage={"qualityStatus": getattr(result, "status", None), "fields": sorted(result.payload) if hasattr(result, "payload") else []},
        date_evidence={"requested": as_of.isoformat(), "response": quality.get("asOf")},
        history_window={"proven": dataset == "core" and status == "eligible"},
        pagination_evidence={"proven": dataset in {"breadth", "activeDirection"} and status == "eligible"},
        permission_evidence={"configured": False, "mode": "offline-fixture"},
        rate_limit_evidence={"requestBudget": 0},
        sample_count=int(getattr(result, "observations", 0) or 0),
        warnings=warnings,
        missing_evidence=tuple(warnings) if status != "eligible" else (),
        checked_at=datetime.combine(as_of, clock_time(12), tzinfo=timezone.utc),
    ).normalized()


def _run_offline_capability_probe(fixture_path: Path, as_of: date) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    adapter = FuyaoMarketAdapter()
    reports: list[ProviderCapabilityReport] = []
    core = adapter.normalize_core(fixture.get("core", {}), as_of, min_bars=1)
    core_result = type("CoreProbe", (), {"status": "ok" if core and all(item.status == "ok" for item in core.values()) else "insufficient", "payload": {"indices": [item.payload for item in core.values()]}, "quality": {"asOf": as_of.isoformat()}, "warnings": (), "observations": sum(item.observations for item in core.values())})()
    reports.append(_capability_report_from_result("core", core_result, as_of))
    for dataset, method, key in (("breadth", "normalize_breadth", "breadth_pages"), ("activeDirection", "normalize_active_direction", "active_direction"), ("sectors", "normalize_sectors", "sectors")):
        if dataset == "breadth":
            result = adapter.normalize_breadth(fixture.get(key, ()), as_of)
        elif dataset == "activeDirection":
            result = adapter.normalize_active_direction(fixture.get(key, ()), as_of, ordering_proven=True)
        else:
            result = adapter.normalize_sectors(fixture.get(key, ()), as_of)
        reports.append(_capability_report_from_result(dataset, result, as_of))
    return {"provider": "fuyao", "asOf": as_of.isoformat(), "reports": [item.redacted_dict() for item in reports]}


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
    if args.command == "fuyao":
        if args.fuyao_command == "capability-probe":
            try:
                payload = _run_offline_capability_probe(Path(args.fixture), args.as_of)
                if args.path:
                    store = SnapshotStore(args.path)
                    for item in payload["reports"]:
                        store.put_capability_report(ProviderCapabilityReport.from_dict(item))
                if args.output:
                    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
                _print_payload(payload)
                return 0
            except Exception as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
        if args.fuyao_command == "real-probe":
            if not args.allow_real:
                _print_payload({"status": "rejected", "error": "real probe requires --allow-real"})
                return 2
            if not os.getenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "").strip():
                _print_payload({"status": "rejected", "error": "MARKET_ENVIRONMENT_FUYAO_API_KEY is required"})
                return 2
            try:
                adapter = FuyaoMarketAdapter(FuyaoMarketClient())
                results = {
                    "breadth": adapter.fetch_breadth(args.as_of),
                    "activeDirection": adapter.fetch_active_direction(args.as_of),
                    "sectors": adapter.fetch_sectors(args.as_of),
                }
                payload = {"provider": "fuyao", "asOf": args.as_of.isoformat(), "reports": [_capability_report_from_result(k, v, args.as_of).redacted_dict() for k, v in results.items()]}
                Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
                store = SnapshotStore(args.path)
                for item in payload["reports"]:
                    store.put_capability_report(ProviderCapabilityReport.from_dict(item))
                _print_payload(payload)
                return 0
            except Exception as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
    if args.command == "database" and args.database_command == "migrate":
        try:
            source = Path(args.source)
            backup = (
                backup_sqlite(source, Path(args.backup), immutable=True)
                if args.backup
                else None
            )
            url = args.database_url or os.getenv("MARKET_ENVIRONMENT_DATABASE_URL", "")
            if not url:
                raise ValueError("--database-url or MARKET_ENVIRONMENT_DATABASE_URL is required")
            result = import_sqlite(
                source,
                database_url=url,
                apply=args.apply,
                immutable=True,
            )
            if backup:
                result["backup"] = backup
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        _print_payload(result)
        return 0
    if args.command == "snapshots" and args.snapshot_command == "refresh":
        active_coordinator = coordinator or CollectionCoordinator()
        if args.history_sessions > 1:
            selected = tuple(dict.fromkeys(args.datasets or ()))
            if selected != ("limits",):
                _print_payload(
                    {
                        "status": "rejected",
                        "error": "--history-sessions above 1 requires exactly --dataset limits",
                    }
                )
                return 2
            try:
                sessions = active_coordinator.prepare_limit_history_sessions(
                    args.as_of,
                    args.history_sessions,
                )
            except Exception as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
            results = []
            for session in sessions:
                try:
                    results.append(
                        active_coordinator.collect(
                            session,
                            ("limits",),
                            fetch_previous_limit_details=False,
                        )
                    )
                except Exception as exc:
                    results.append(exc)
            run_statuses = [
                result.run.status for result in results if not isinstance(result, Exception)
            ]
            failures = [
                result
                for result in results
                if isinstance(result, Exception) or result.run.status == "failed"
            ]
            if len(failures) == len(results):
                status = "failed"
            elif failures or any(value != "success" for value in run_statuses):
                status = "partial"
            else:
                status = "success"
            _print_payload(
                {
                    "asOf": args.as_of.isoformat(),
                    "status": status,
                    "forced": args.force,
                    "historySessions": args.history_sessions,
                    "sessions": [
                        {
                            "asOf": session.isoformat(),
                            "status": "failed" if isinstance(result, Exception) else result.run.status,
                            "error": str(result) if isinstance(result, Exception) else None,
                            "datasets": []
                            if isinstance(result, Exception)
                            else _collection_payload(result)["datasets"],
                        }
                        for session, result in zip(sessions, results)
                    ],
                }
            )
            return 2 if failures else 0
        try:
            result = active_coordinator.collect(args.as_of, args.datasets)
        except ValueError as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        payload = _collection_payload(result, forced=args.force)
        _print_payload(payload)
        return 0 if result.run.status == "success" else 2
    if args.command == "snapshots" and args.snapshot_command == "scheduled-refresh":
        current = _market_now(now)
        calendar_date = current.date()
        selected = tuple(args.datasets or SUPPORTED_COLLECTION_DATASETS)

        # Weekend invocations are harmless no-ops; weekday holidays remain auditable provider failures.
        if current.weekday() >= 5:
            _print_payload(
                {
                    "trigger": "scheduled",
                    "asOf": calendar_date.isoformat(),
                    "status": "skipped",
                    "reason": "weekend",
                    "datasets": [],
                }
            )
            return 0

        as_of = effective_market_date(current)

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
    if args.command == "snapshots" and args.snapshot_command in {"relabel-date", "relabel", "migrate-date", "date-relabel", "migrate"}:
        # Date relabels must always select their backend explicitly.  In
        # particular, never fall back to MARKET_ENVIRONMENT_SNAPSHOT_PATH:
        # that variable is reserved for the one-shot SQLite import tool.
        if bool(args.path) == bool(args.database_url):
            _print_payload({"status": "rejected", "error": "exactly one of --path or --database-url is required"})
            return 2
        try:
            store = SnapshotStore(args.path) if args.path else SnapshotStore(database_url=args.database_url)
            result = relabel_date(
                store,
                args.source_as_of,
                args.target_as_of,
                apply=bool(args.apply and not args.dry_run),
                conflict_policy=args.conflict_policy,
                operator=args.operator,
            )
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        _print_payload(result.as_dict())
        return 0 if result.status in {"dry-run", "applied"} and not result.conflicts else 2
    if args.command == "snapshots" and args.snapshot_command in {"relabel-rollback", "rollback-relabel"}:
        if bool(args.path) == bool(args.database_url):
            _print_payload({"status": "rejected", "error": "exactly one of --path or --database-url is required"})
            return 2
        try:
            store = SnapshotStore(args.path) if args.path else SnapshotStore(database_url=args.database_url)
            result = rollback_date_relabel(store, args.audit_id, apply=bool(args.apply and not args.dry_run))
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        _print_payload(result.as_dict())
        return 0 if result.status in {"dry-run", "rolled-back"} else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
