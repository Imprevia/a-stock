"""Command-line operations for market environment data."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .collection import SUPPORTED_COLLECTION_DATASETS, CollectionCoordinator
from .fuyao_market import FuyaoMarketAdapter, FuyaoMarketClient
from .provider_capability import ProviderCapabilityReport
from .date_relabel import relabel_date, rollback_date_relabel
from .postgres_migration import backup_sqlite, import_sqlite
from .providers import INDEX_SPECS, MarketDataProvider
from .refresh import MARKET_TIME_ZONE, effective_market_date, settlement_time
from .snapshot_store import SnapshotStore
from .tdx_daily import TDXDailyPackageClient


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
    tdx = commands.add_parser("tdx", help="audit the TDX daily-package provider")
    tdx_commands = tdx.add_subparsers(dest="tdx_command", required=True)
    tdx_probe = tdx_commands.add_parser(
        "real-probe",
        help="read one settled package without writing snapshots or databases",
    )
    tdx_probe.add_argument("--as-of", required=True, type=date.fromisoformat)
    tdx_probe.add_argument("--output", required=True, help="redacted report output path")
    tdx_probe.add_argument("--allow-real", action="store_true", help="required explicit authorization")
    return parser


def _capability_report_from_result(dataset: str, result: Any, as_of: date, *, revision: str = "fuyao-market-v2") -> ProviderCapabilityReport:
    quality = getattr(result, "quality", {}) or {}
    result_status = str(getattr(result, "status", "insufficient"))
    report_revision = str(quality.get("providerRevision") or revision)
    # ``fallback`` is the intentional quality status for the THS sectors
    # contract: required identity/change/turnover evidence is valid while
    # optional funds/width/leader fields are unavailable.  It is eligible for
    # capability approval, but those omissions remain explicit evidence.
    status = "eligible" if result_status == "ok" or (dataset == "sectors" and result_status == "fallback") else "ineligible"
    if dataset == "activeDirection":
        # The v2 migration deliberately leaves this dataset on the existing
        # Eastmoney/TDX route; a Fuyao probe is evidence only, never a cutover
        # approval for the stale/latest-only adapter.
        status = "unverified"
    warnings = tuple(str(item) for item in getattr(result, "warnings", ()) or quality.get("warnings", ()))
    if dataset == "activeDirection":
        warnings = tuple(dict.fromkeys([*warnings, "activeDirection remains on the existing Eastmoney/TDX route"])
        )
    elif status != "eligible" and not warnings:
        warnings = ("fixture contract evidence is incomplete",)
    endpoints = quality.get("endpoints") if isinstance(quality.get("endpoints"), dict) else {}
    endpoint = quality.get("endpoint") or endpoints.get("snapshot") or f"fixture:{dataset}"
    field_coverage = quality.get("fieldCoverage")
    if not isinstance(field_coverage, dict):
        field_coverage = {
            "qualityStatus": result_status,
            "fields": sorted(result.payload) if hasattr(result, "payload") else [],
        }
    elif endpoints:
        field_coverage = {**field_coverage, "endpoints": dict(endpoints)}
    date_evidence = quality.get("dateEvidence")
    if not isinstance(date_evidence, dict):
        date_evidence = {"requested": as_of.isoformat(), "response": quality.get("asOf")}
    pagination_evidence = quality.get("paginationEvidence")
    if not isinstance(pagination_evidence, dict):
        pagination_evidence = {
            "proven": dataset in {"breadth", "activeDirection"} and status == "eligible",
        }
    if dataset == "sectors":
        pagination_evidence = {
            **pagination_evidence,
            "catalogCount": quality.get("catalogCount"),
            "snapshotCount": quality.get("snapshotCount"),
            "snapshotCoverage": quality.get("snapshotCoverage"),
            "snapshotBatchCount": quality.get("snapshotBatchCount"),
            "snapshotTimestamps": quality.get("snapshotTimestamps", []),
        }
    permission_evidence = quality.get("permissionEvidence")
    if not isinstance(permission_evidence, dict):
        permission_evidence = {"configured": False, "mode": "offline-fixture"}
    rate_limit_evidence = quality.get("rateLimitEvidence")
    if not isinstance(rate_limit_evidence, dict):
        rate_limit_evidence = {"requestBudget": 0}
    unsupported = quality.get("unsupportedFields") or ()
    missing_evidence = tuple(str(item) for item in unsupported)
    if status != "eligible":
        missing_evidence = tuple(dict.fromkeys([*missing_evidence, *warnings]))
    return ProviderCapabilityReport(
        provider="fuyao",
        dataset=dataset,
        revision=report_revision,
        status=status,
        endpoint=str(endpoint),
        field_coverage=field_coverage,
        date_evidence=date_evidence,
        history_window=(
            dict(quality["historyWindow"])
            if isinstance(quality.get("historyWindow"), dict)
            else {"proven": dataset == "core" and status == "eligible"}
        ),
        pagination_evidence=pagination_evidence,
        permission_evidence=permission_evidence,
        rate_limit_evidence=rate_limit_evidence,
        sample_count=int(getattr(result, "observations", 0) or 0),
        warnings=warnings,
        missing_evidence=missing_evidence,
        checked_at=datetime.combine(as_of, clock_time(12), tzinfo=timezone.utc),
    ).normalized()


def _run_offline_capability_probe(fixture_path: Path, as_of: date) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    adapter = FuyaoMarketAdapter()
    reports: list[ProviderCapabilityReport] = []
    core = adapter.normalize_core(fixture.get("core", {}), as_of, min_bars=280)
    core_result = type(
        "CoreProbe",
        (),
        {
            "status": "ok" if len(core) == 5 and all(item.status == "ok" for item in core.values()) else "insufficient",
            "payload": {"indices": [item.payload for item in core.values()]},
            "quality": {
                "asOf": as_of.isoformat(),
                "providerRevision": adapter.source_revision,
                "endpoint": "/api/a-share-index/prices/historical",
                "fieldCoverage": {"indices": len(core), "minimumBars": 280},
                "dateEvidence": {"requested": as_of.isoformat()},
            },
            "warnings": tuple(warning for item in core.values() for warning in item.warnings),
            "observations": sum(item.observations for item in core.values()),
        },
    )()
    reports.append(_capability_report_from_result("core", core_result, as_of))
    for dataset, method, key in (("breadth", "normalize_breadth", "breadth_snapshot_pages"), ("activeDirection", "normalize_active_direction", "active_direction"), ("sectors", "normalize_sectors", "sectors")):
        if dataset == "breadth":
            snapshot_pages = fixture.get(key)
            if not snapshot_pages:
                result = adapter._result(
                    "market-breadth",
                    {"state": "insufficient", "advanceCount": None, "declineCount": None, "flatCount": None, "validCount": None, "advanceRatio": None, "medianReturn": None},
                    status="insufficient",
                    as_of=as_of,
                    observations=0,
                    warnings=["v2 snapshot fixture is missing; legacy breadth fixture is not capability evidence"],
                    quality_extra={"endpoint": "/api/a-share/prices/snapshot", "dateCapability": "latest-only"},
                )
            else:
                result = adapter.normalize_breadth(snapshot_pages, as_of)
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


def _run_tdx_real_probe(as_of: date) -> dict[str, Any]:
    started = time.perf_counter()
    client = TDXDailyPackageClient()
    package = client.fetch(as_of)

    class ProbeClient:
        stock_universe_minimums = getattr(client, "stock_universe_minimums", None)
        stock_universe_minimum_total = getattr(client, "stock_universe_minimum_total", None)
        stock_universe_required_markets = getattr(client, "stock_universe_required_markets", None)
        stock_universe_max_unclassified_ratio = getattr(
            client,
            "stock_universe_max_unclassified_ratio",
            None,
        )

        def fetch(self, requested_date: date):
            if requested_date != as_of:
                raise ValueError("probe attempted a date outside the requested package")
            return package

    from .providers import MarketDataProvider

    provider = MarketDataProvider(
        tdx_daily_package=ProbeClient(),
        tdx_active_direction_derived_enabled=True,
    )
    derived_rows, metadata = provider._fetch_tdx_active_direction_rows(as_of)
    package_rows = list(package.rows)
    valid_rows = [
        row for row in package_rows
        if row.amount is not None and row.close is not None
    ]
    named_rows = [row for row in valid_rows if provider._valid_tdx_name(row.name, row.code)]
    market_counts = package.metadata.get("marketCounts", {})
    return {
        "provider": "tdx-daily-package",
        "requestedDate": as_of.isoformat(),
        "sourceDate": package.source_date.isoformat(),
        "fetchedAt": package.fetched_at.isoformat(),
        "marketCounts": dict(market_counts) if isinstance(market_counts, dict) else {},
        "rowCount": len(package_rows),
        "validRows": len(valid_rows),
        "stockUniversePolicyVersion": metadata.get("stockUniversePolicyVersion"),
        "stockUniverseRawCount": metadata.get("stockUniverseRawCount"),
        "stockUniverseRetainedCount": metadata.get("stockUniverseRetainedCount"),
        "stockUniverseExcludedCount": metadata.get("stockUniverseExcludedCount"),
        "stockUniverseUnclassifiedCount": metadata.get("stockUniverseUnclassifiedCount"),
        "stockUniverseRetainedByMarket": metadata.get("stockUniverseRetainedByMarket"),
        "stockUniverseExcludedByReason": metadata.get("stockUniverseExcludedByReason"),
        "stockUniverseUnclassifiedByReason": metadata.get("stockUniverseUnclassifiedByReason"),
        "derivedTopRows": len(derived_rows),
        "amountCoverage": len([row for row in package_rows if row.amount is not None]) / len(package_rows) if package_rows else 0.0,
        "nameCoverage": len(named_rows) / len(valid_rows) if valid_rows else 0.0,
        "rankingMethod": metadata.get("rankingMethod"),
        "industryMappingRevision": metadata.get("industryMappingRevision"),
        "industryMappingCoverage": metadata.get("industryMappingCoverage"),
        "sourceRevision": metadata.get("sourceRevision"),
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        "quality": "fallback-derived",
    }


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
                # Current-date core evidence must include an independent quote
                # source; historical probes intentionally remain quote-free.
                probe_now = _market_now(now)
                quotes = (
                    MarketDataProvider().fetch_quotes(INDEX_SPECS)
                    if args.as_of == effective_market_date(probe_now)
                    else {}
                )
                core_results = (
                    adapter.fetch_core(args.as_of, quotes_by_code=quotes)
                    if quotes
                    else adapter.fetch_core(args.as_of)
                )
                market_client = getattr(adapter, "client", None)
                client_configured = bool(
                    getattr(market_client, "configured", bool(os.getenv("MARKET_ENVIRONMENT_FUYAO_API_KEY")))
                )
                request_budget = int(getattr(market_client, "request_budget", 0) or 0)
                request_count = int(getattr(market_client, "request_count", 0) or 0)
                core_result = SimpleNamespace(
                    status="ok"
                    if len(core_results) == 5
                    and all(item.status == "ok" for item in core_results.values())
                    else "insufficient",
                    payload={"indices": [item.payload for item in core_results.values()]},
                    quality={
                        "asOf": args.as_of.isoformat(),
                        "providerRevision": getattr(adapter, "source_revision", "fuyao-market-v2"),
                        "endpoint": "/api/a-share-index/prices/historical",
                        "fieldCoverage": {
                            "indices": len(core_results),
                            "validIndices": sum(item.status == "ok" for item in core_results.values()),
                            "minimumBars": 280,
                            "ohlcTurnover": all(
                                bool(item.payload.get("bars")) for item in core_results.values()
                            ),
                            "independentQuote": {
                                "provider": "tencent",
                                "required": args.as_of == effective_market_date(probe_now),
                                "checked": bool(quotes),
                                "sampleCount": len(quotes),
                            },
                        },
                        "dateEvidence": {
                            "requested": args.as_of.isoformat(),
                            "indices": {
                                code: item.quality.get("dateEvidence", {})
                                for code, item in core_results.items()
                            },
                        },
                        "historyWindow": {
                            "proven": all(item.status == "ok" for item in core_results.values()),
                            "minimumBars": min(
                                (
                                    int(item.quality.get("historyWindow", {}).get("observations", 0))
                                    for item in core_results.values()
                                ),
                                default=0,
                            ),
                        },
                        "permissionEvidence": {
                            "configured": client_configured,
                        },
                        "rateLimitEvidence": {
                            "requestBudget": request_budget,
                            "requestsUsed": request_count,
                        },
                    },
                    warnings=tuple(warning for item in core_results.values() for warning in item.warnings),
                    observations=sum(item.observations for item in core_results.values()),
                )
                probe_results = {
                    "core": core_result,
                    "breadth": adapter.fetch_breadth(args.as_of),
                    "activeDirection": adapter.fetch_active_direction(args.as_of),
                    "sectors": adapter.fetch_sectors(args.as_of),
                }
                request_count = int(getattr(market_client, "request_count", request_count) or 0)
                for dataset, result in tuple(probe_results.items()):
                    quality = dict(getattr(result, "quality", {}) or {})
                    quality.setdefault("permissionEvidence", {"configured": client_configured})
                    quality.setdefault(
                        "rateLimitEvidence",
                        {
                            "requestBudget": request_budget,
                            "requestsUsed": request_count,
                        },
                    )
                    probe_results[dataset] = SimpleNamespace(
                        payload=getattr(result, "payload", {}),
                        quality=quality,
                        status=getattr(result, "status", "insufficient"),
                        warnings=getattr(result, "warnings", ()),
                        observations=getattr(result, "observations", 0),
                    )
                results = probe_results
                payload = {
                    "provider": "fuyao",
                    "asOf": args.as_of.isoformat(),
                    "reports": [
                        _capability_report_from_result(k, v, args.as_of).redacted_dict()
                        for k, v in results.items()
                    ],
                }
                Path(args.output).write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8",
                )
                store = SnapshotStore(args.path)
                for item in payload["reports"]:
                    store.put_capability_report(ProviderCapabilityReport.from_dict(item))
                _print_payload(payload)
                return 0
            except Exception as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
    if args.command == "tdx" and args.tdx_command == "real-probe":
        if not args.allow_real:
            _print_payload({"status": "rejected", "error": "real probe requires --allow-real"})
            return 2
        try:
            payload = _run_tdx_real_probe(args.as_of)
            Path(args.output).write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            _print_payload(payload)
            return 0 if payload["quality"] in {"ok", "fallback-derived"} else 2
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
            if args.force:
                result = active_coordinator.collect(
                    args.as_of,
                    args.datasets,
                    allow_historical_latest_only=True,
                )
            else:
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
