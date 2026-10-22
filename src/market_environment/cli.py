"""Command-line operations for market environment data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .bootstrap.container import ContainerAdapters
from .application.commands import (
    BreadthHistoryMaintenanceRequest,
    CapabilityPromotionError,
    CapabilityPromotionRepositoryError,
    MAX_BREADTH_HISTORY_DATES,
)
from .infrastructure.collection import SUPPORTED_COLLECTION_DATASETS, CollectionCoordinator
from .infrastructure.providers.fuyao.market import FuyaoMarketAdapter, FuyaoMarketClient
from .infrastructure.providers.fuyao.ths_probe import run_fuyao_ths_capability_probe
from .infrastructure.providers.capability import ProviderCapabilityReport
from .domain.models.capability import THS_CAPABILITY_REVISIONS
from .infrastructure.persistence.sqlite_import.date_relabel import relabel_date, rollback_date_relabel
from .infrastructure.persistence.sqlite_import.migration import backup_sqlite, import_sqlite
from .providers import INDEX_SPECS, MarketDataProvider
from .infrastructure.collection.refresh import MARKET_TIME_ZONE, effective_market_date, settlement_time
from .snapshot_store import SnapshotStore
from .infrastructure.persistence.sqlite_import import LegacySqliteSnapshotStore
from .infrastructure.providers.tdx.daily_package import TDXDailyPackageClient
from .interfaces.cli.container import build_cli_container
from .interfaces.cli.capability_promotion import build_capability_promotion_runtime


_DEFAULT_COLLECTION_COORDINATOR_CLASS = CollectionCoordinator


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


def _add_breadth_history_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        action="append",
        dest="maintenance_dates",
        type=date.fromisoformat,
        default=[],
        help="exact confirmed trading date; repeat up to the maintenance maximum",
    )
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true", help="commit the bounded repair")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly request the default read-only plan",
    )
    parser.add_argument(
        "--allow-real-provider",
        action="store_true",
        help="explicitly authorize real provider access for --apply",
    )
    parser.add_argument(
        "--allow-snapshot-writes",
        action="store_true",
        help="explicitly authorize snapshot/aggregate writes for --apply",
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
    refresh.add_argument(
        "--repair-integrity",
        action="store_true",
        help="replace a corrupt same-date core snapshot; requires --force and --dataset core",
    )
    refresh.add_argument(
        "--history-sessions",
        type=_positive_int,
        default=1,
        help="collect the latest N confirmed sessions; values above 1 require --dataset limits",
    )
    breadth_history = snapshot_commands.add_parser(
        "breadth-history",
        help="plan or explicitly apply bounded exact-date breadth history repair",
    )
    _add_breadth_history_arguments(breadth_history)
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
    capabilities = commands.add_parser(
        "capabilities",
        help="validate and promote provider capability reports",
    )
    capability_commands = capabilities.add_subparsers(
        dest="capability_command",
        required=True,
    )
    promote = capability_commands.add_parser(
        "promote",
        help="promote one reviewed report (dry-run by default)",
    )
    promote.add_argument(
        "--input",
        required=True,
        help="redacted report envelope path, or - to read stdin",
    )
    promote.add_argument("--provider", required=True)
    promote.add_argument("--dataset", required=True)
    promote.add_argument("--revision", required=True)
    promote.add_argument(
        "--apply",
        action="store_true",
        help="commit the selected report; omitted means dry-run",
    )
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
    ths_real = fuyao_commands.add_parser(
        "ths-real-probe",
        help="probe six independently versioned THS contracts",
    )
    ths_real.add_argument("--as-of", required=True, type=date.fromisoformat)
    ths_real.add_argument("--thscode", required=True)
    ths_real.add_argument("--history-start", required=True, type=date.fromisoformat)
    ths_real.add_argument("--max-dump-bytes", required=True, type=_positive_int)
    ths_real.add_argument("--output", required=True, help="redacted report output path")
    ths_real.add_argument("--path", required=True, help="isolated SQLite store path")
    ths_real.add_argument("--allow-real", action="store_true", help="required explicit authorization")
    for dataset, argument in (
        ("industry-ranking", "catalog-revision"),
        ("sector-membership", "membership-revision"),
        ("sector-turnover-history", "history-revision"),
        ("sector-member-daily-dump", "daily-dump-revision"),
        ("sector-member-incremental-dump", "incremental-dump-revision"),
        ("sector-member-adjustment-dump", "adjustment-dump-revision"),
    ):
        ths_real.add_argument(
            f"--{argument}",
            default=THS_CAPABILITY_REVISIONS[dataset],
        )
    tdx = commands.add_parser("tdx", help="audit the TDX daily-package provider")
    tdx_commands = tdx.add_subparsers(dest="tdx_command", required=True)
    tdx_probe = tdx_commands.add_parser(
        "real-probe",
        help="read one settled package without writing snapshots or databases",
    )
    tdx_probe.add_argument("--as-of", required=True, type=date.fromisoformat)
    tdx_probe.add_argument("--output", required=True, help="redacted report output path")
    tdx_probe.add_argument("--allow-real", action="store_true", help="required explicit authorization")
    sectors_html = commands.add_parser(
        "sectors-html",
        help="audit static-HTML sectors adapters",
    )
    sectors_html_commands = sectors_html.add_subparsers(
        dest="sectors_html_command",
        required=True,
    )
    sectors_probe = sectors_html_commands.add_parser(
        "real-probe",
        help="run an authorized local HTML probe (dry-run by default)",
    )
    sectors_probe.add_argument(
        "--source",
        required=True,
        choices=("sina-html", "xueqiu-html"),
    )
    sectors_probe.add_argument("--as-of", required=True, type=date.fromisoformat)
    sectors_probe.add_argument(
        "--output",
        required=True,
        help="redacted report output path",
    )
    sectors_probe.add_argument(
        "--allow-real",
        action="store_true",
        help="required explicit authorization for the network call",
    )
    industry_probe = commands.add_parser(
        "industry-capability-probe",
        help="audit one point-in-time industry input capability",
    )
    industry_probe.add_argument(
        "--dataset",
        required=True,
        choices=(
            "shenwan-taxonomy",
            "shenwan-point-in-time-membership",
            "stock-adjusted-price",
            "tdx-original-daily-facts",
            "benchmark-history",
        ),
    )
    industry_probe.add_argument("--source", required=True)
    industry_probe.add_argument("--revision", required=True)
    industry_probe.add_argument("--as-of", required=True, type=date.fromisoformat)
    industry_probe.add_argument("--output", required=True, help="redacted report output path")
    industry_probe.add_argument("--allow-real", action="store_true")
    continuity = commands.add_parser(
        "sector-continuity",
        help="explicitly plan or inspect Shenwan sector continuity backfill",
    )
    continuity_commands = continuity.add_subparsers(dest="continuity_command", required=True)
    continuity_backfill = continuity_commands.add_parser("backfill", help="plan an explicit finite backfill")
    continuity_backfill.add_argument("--as-of", required=True, type=date.fromisoformat)
    continuity_backfill.add_argument("--start-as-of", type=date.fromisoformat)
    continuity_backfill.add_argument("--sessions", type=_positive_int, default=272)
    continuity_backfill.add_argument("--session-date", action="append", type=date.fromisoformat, default=[])
    continuity_backfill.add_argument("--calculation-version", required=True)
    continuity_backfill.add_argument("--source-revision", action="append", default=[], metavar="KEY=VALUE")
    continuity_backfill.add_argument("--apply", action="store_true", help="requires a separately configured runtime; never implied")
    continuity_readiness = continuity_commands.add_parser("readiness", help="read local readiness without provider I/O")
    continuity_readiness.add_argument("--as-of", required=True, type=date.fromisoformat)
    continuity_readiness.add_argument("--required-history", type=_positive_int, default=272)
    ths = commands.add_parser(
        "ths",
        help="run explicitly authorized THS catalog, turnover, and member-fact operations",
    )
    ths_commands = ths.add_subparsers(dest="ths_command", required=True)
    ths_catalog = ths_commands.add_parser("catalog-sync", help="synchronize all four THS catalogs")
    ths_catalog.add_argument("--as-of", required=True, type=date.fromisoformat)
    ths_catalog.add_argument("--capability-revision")
    ths_catalog.add_argument("--membership-capability-revision")
    ths_catalog.add_argument(
        "--membership-thscode",
        action="append",
        default=[],
        dest="membership_thscodes",
    )
    ths_catalog.add_argument("--request-budget", type=_positive_int)
    ths_catalog.add_argument("--apply", action="store_true")
    ths_backfill = ths_commands.add_parser("turnover-backfill", help="backfill bounded THS K-lines")
    ths_backfill.add_argument("--thscode", action="append", required=True, dest="thscodes")
    ths_backfill.add_argument("--start-date", required=True, type=date.fromisoformat)
    ths_backfill.add_argument("--end-date", required=True, type=date.fromisoformat)
    ths_backfill.add_argument("--capability-revision")
    ths_backfill.add_argument("--request-budget", type=_positive_int)
    ths_backfill.add_argument("--apply", action="store_true")
    ths_import = ths_commands.add_parser(
        "member-import",
        help="import a local, verified member-fact request JSON",
    )
    ths_import.add_argument("--request", required=True, help="local JSON request path")
    ths_import.add_argument("--apply", action="store_true")
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
            "catalogIdentityUnique": quality.get("catalogIdentityUnique"),
            "snapshotIdentityUnique": quality.get("snapshotIdentityUnique"),
            "snapshotCoverage": quality.get("snapshotCoverage"),
            "snapshotBatchCount": quality.get("snapshotBatchCount"),
            "snapshotTimestampCount": quality.get("snapshotTimestampCount"),
            "snapshotTimestamps": quality.get("snapshotTimestamps", []),
            "snapshotTimestampDateConsistent": quality.get(
                "snapshotTimestampDateConsistent"
            ),
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


def _core_probe_result(
    core_results: Mapping[str, Any],
    as_of: date,
    *,
    revision: str,
    permission_evidence: Mapping[str, Any],
    rate_limit_evidence: Mapping[str, Any],
    independent_quote_checked: bool,
    independent_quote_samples: int,
) -> SimpleNamespace:
    canonical_identities = {
        spec.code: (
            f"{spec.digits}.SH"
            if spec.code.lower().startswith("sh")
            else f"{spec.digits}.SZ"
        )
        for spec in INDEX_SPECS
    }
    observations_by_index: dict[str, int] = {}
    date_by_index: dict[str, dict[str, Any]] = {}
    valid_codes: set[str] = set()
    ohlc_complete = True
    turnover_complete = True
    direct_turnover = True
    warnings: list[str] = []
    for code, expected_identity in canonical_identities.items():
        item = core_results.get(code)
        if item is None:
            observations_by_index[code] = 0
            date_by_index[code] = {
                "identity": expected_identity,
                "lastValid": None,
                "exact": False,
            }
            ohlc_complete = turnover_complete = direct_turnover = False
            warnings.append(f"core probe omitted {code}")
            continue
        payload = dict(getattr(item, "payload", {}) or {})
        quality = dict(getattr(item, "quality", {}) or {})
        bars = list(payload.get("bars") or ())
        observations = int(getattr(item, "observations", len(bars)) or 0)
        observations_by_index[code] = observations
        last_valid = None
        if bars:
            value = getattr(bars[-1], "date", None)
            last_valid = value.isoformat() if isinstance(value, date) else None
        identity = str(payload.get("identity") or "")
        exact = last_valid == as_of.isoformat()
        date_by_index[code] = {
            "identity": identity or expected_identity,
            "lastValid": last_valid,
            "exact": exact,
        }
        item_ohlc = bool(bars) and all(
            all(getattr(bar, name, None) is not None for name in ("open", "high", "low", "close"))
            for bar in bars
        )
        item_turnover = bool(bars) and all(
            getattr(bar, "amount", None) is not None for bar in bars
        )
        item_direct = (
            payload.get("amountEvidence") == "direct-turnover"
            and quality.get("amountEvidence") == "direct-turnover"
        )
        item_valid = (
            getattr(item, "status", "insufficient") == "ok"
            and identity == expected_identity
            and observations >= 280
            and exact
            and item_ohlc
            and item_turnover
            and item_direct
        )
        if item_valid:
            valid_codes.add(code)
        ohlc_complete = ohlc_complete and item_ohlc
        turnover_complete = turnover_complete and item_turnover
        direct_turnover = direct_turnover and item_direct
        warnings.extend(str(value) for value in getattr(item, "warnings", ()) if value)

    quote_required = True
    quote_complete = independent_quote_checked and independent_quote_samples == len(
        canonical_identities
    )
    eligible = len(valid_codes) == len(canonical_identities) and quote_complete
    return SimpleNamespace(
        status="ok" if eligible else "insufficient",
        payload={
            "indices": [
                dict(getattr(core_results[code], "payload", {}) or {})
                for code in canonical_identities
                if code in core_results
            ]
        },
        quality={
            "asOf": as_of.isoformat(),
            "providerRevision": revision,
            "endpoint": "/api/a-share-index/prices/historical",
            "fieldCoverage": {
                "canonicalIdentities": canonical_identities,
                "validIndices": len(valid_codes),
                "ohlcComplete": ohlc_complete,
                "turnoverComplete": turnover_complete,
                "directTurnover": direct_turnover,
                "independentQuote": {
                    "provider": "tencent",
                    "required": quote_required,
                    "checked": independent_quote_checked,
                    "sampleCount": independent_quote_samples,
                },
            },
            "dateEvidence": {
                "requested": as_of.isoformat(),
                "exact": all(value["exact"] is True for value in date_by_index.values()),
                "indices": date_by_index,
            },
            "historyWindow": {
                "proven": all(value >= 280 for value in observations_by_index.values()),
                "minimumBars": 280,
                "observationsByIndex": observations_by_index,
            },
            "permissionEvidence": dict(permission_evidence),
            "rateLimitEvidence": dict(rate_limit_evidence),
        },
        warnings=tuple(dict.fromkeys(warnings)),
        observations=sum(observations_by_index.values()),
    )


def _run_offline_capability_probe(fixture_path: Path, as_of: date) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    adapter = FuyaoMarketAdapter()
    reports: list[ProviderCapabilityReport] = []
    core = adapter.normalize_core(fixture.get("core", {}), as_of, min_bars=280)
    core_result = _core_probe_result(
        core,
        as_of,
        revision=adapter.source_revision,
        permission_evidence={
            "configured": False,
            "approved": False,
            "mode": "offline-fixture",
        },
        rate_limit_evidence={"requestBudget": 0, "requestsUsed": 0},
        independent_quote_checked=False,
        independent_quote_samples=0,
    )
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


def _validate_fuyao_real_probe_boundary(as_of: date, current: datetime) -> None:
    if current.weekday() >= 5:
        raise ValueError("Fuyao real probe requires a Shanghai market weekday")
    if current.time().replace(tzinfo=None) < settlement_time():
        raise ValueError(
            "Fuyao real probe is only allowed after the configured settlement time"
        )
    if as_of != effective_market_date(current):
        raise ValueError(
            "Fuyao real probe requires the current effective Shanghai market date"
        )


def _validate_isolated_probe_paths(output: str, store: str) -> None:
    output_path = Path(output).resolve()
    store_path = Path(store).resolve()
    if output_path == store_path:
        raise ValueError("probe output and isolated evidence store must be different paths")
    for label, path in (("probe output", output_path), ("isolated evidence store", store_path)):
        if not path.parent.is_dir():
            raise ValueError(f"{label} parent directory does not exist")
        if path.exists():
            raise ValueError(f"{label} path must not already exist")


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _close_capability_runtime(runtime: Any | None) -> bool:
    if runtime is None:
        return True
    try:
        runtime.close()
    except Exception:
        return False
    return True


def _run_sectors_html_real_probe(
    *,
    as_of: date,
    source: str,
    allow_real: bool,
) -> dict[str, Any]:
    """Dry-run by default; only call the network when ``--allow-real`` is set.

    The probe reuses the static-HTML adapter with a transport override that
    invokes the configured Scrapling engine. The output is a redacted JSON
    envelope ready for the capability-promotion CLI; the envelope never
    contains a raw response body, a token, a cookie, or an authorization
    header.
    """
    from .infrastructure.providers.sina_html import SinaHtmlSectorAdapter
    from .infrastructure.providers.xueqiu_html import XueqiuHtmlSectorAdapter
    from .infrastructure.providers.html_common.base_adapter import (
        StaticHtmlTransportError,
    )
    from .infrastructure.providers.html_common.fixture_loader import (
        load_host_fixture,
    )
    from .application.ports.acquisition import SourceRequest, DatasetDate

    if source == "sina-html":
        adapter = SinaHtmlSectorAdapter()
        host_id = "sina"
    elif source == "xueqiu-html":
        adapter = XueqiuHtmlSectorAdapter()
        host_id = "xueqiu"
    else:
        raise ValueError(f"unknown source: {source!r}")

    fixture = load_host_fixture(host_id)
    started = time.perf_counter()
    probe = {
        "provider": host_id,
        "dataset": "sectors",
        "source": source,
        "revision": adapter.capability.revision,
        "requestedDate": as_of.isoformat(),
        "scraplingProfile": "default-off",
        "allowReal": bool(allow_real),
        "fixtureFootprint": dict(fixture.footprint),
        "fixtureCoverage": dict(fixture.meta),
        "elapsedMs": None,
        "transports": [],
        "hostClassification": None,
        "fieldCoverage": {
            "code": 0.0,
            "name": 0.0,
            "changePct": 0.0,
            "amount": 0.0,
            "leader": 0.0,
            "mainNet": 0.0,
            "mainNetPct": 0.0,
            "upCount": 0.0,
            "downCount": 0.0,
        },
        "permissionEvidence": {"configured": False, "scraplingAllowlist": False},
        "rateLimitEvidence": {"transports": 0, "singleFlight": True},
        "warnings": [],
        "status": "dry-run",
    }

    if not allow_real:
        probe["warnings"].append(
            "dry-run requested; pass --allow-real to issue a single bodyless GET"
        )
        probe["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
        return probe

    if not os.getenv("MARKET_ENVIRONMENT_PROBE_ALLOW_REAL"):
        probe["status"] = "rejected"
        probe["warnings"].append(
            "MARKET_ENVIRONMENT_PROBE_ALLOW_REAL must be set for live probes"
        )
        return probe

    request = SourceRequest(
        identity=DatasetDate(dataset="sectors", as_of=as_of),
        source_id=adapter.source_id,
        current_market_date=as_of,
        settled=False,
        params={"fixture": fixture},
    )

    def _classify_transport(exc: Exception) -> str:
        if isinstance(exc, StaticHtmlTransportError):
            return exc.signal
        return "transport-error"

    try:
        from .infrastructure.providers.html_common import ScraplingStaticHttpEngine  # noqa: F401
    except Exception:
        pass

    fetch_started = time.perf_counter()
    try:
        from src.trading_system.data.provider_scrapling import (
            ScraplingStaticEngineConfig,
            ScraplingStaticHttpEngine,
        )

        config = ScraplingStaticEngineConfig(
            enabled=True,
            allowlist=frozenset(
                {(adapter.expected_endpoint().split("//", 1)[-1].rstrip("/"), adapter.source_id)}
            ),
        )
        engine = ScraplingStaticHttpEngine(config)
        body = engine.fetch(str(adapter.expected_endpoint()))
        probe["transports"].append(
            {
                "engine": "scrapling",
                "endpoint": adapter.expected_endpoint(),
                "classification": "ok",
                "elapsedMs": round((time.perf_counter() - fetch_started) * 1000, 2),
            }
        )
    except Exception as exc:  # noqa: BLE001 - classify for report
        classification = _classify_transport(exc)
        probe["transports"].append(
            {
                "engine": "scrapling",
                "endpoint": adapter.expected_endpoint(),
                "classification": classification,
                "elapsedMs": round((time.perf_counter() - fetch_started) * 1000, 2),
            }
        )
        probe["hostClassification"] = classification
        probe["warnings"].append(f"transport reported {classification}: {exc!s}")
        probe["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
        if classification in {"host-permission-denied", "host-challenge-detected"}:
            probe["status"] = "ineligible"
        else:
            probe["status"] = "rejected"
        return probe

    try:
        adapter.set_gate_predicate(lambda _req: True)
        adapter.set_fetch_override(lambda _req: body)
        result = adapter.acquire(request)
    except Exception as exc:  # noqa: BLE001
        probe["warnings"].append(f"adapter failed: {exc!s}")
        probe["status"] = "insufficient"
        probe["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
        return probe

    rows = getattr(result, "payload", {}).get("rows", []) if not isinstance(result, Exception) else []
    if rows:
        counts = {field: 0 for field in probe["fieldCoverage"]}
        per_row = lambda field: any(row.get(field) is not None for row in rows)
        for field in counts:
            if per_row(field):
                counts[field] = 1.0
        probe["fieldCoverage"] = counts
        probe["status"] = "ok"
    else:
        probe["status"] = "insufficient"
        probe["warnings"].append("adapter returned no rows")

    probe["elapsedMs"] = round((time.perf_counter() - started) * 1000, 2)
    return probe


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


@contextmanager
def _collection_coordinator_scope(
    injected: CollectionCoordinator | None,
    *,
    clock: Callable[[], datetime] | None = None,
):
    if injected is not None:
        yield injected
        return
    # Preserve the historical module-level test seam for callers that replace
    # the coordinator class explicitly. Normal runtime composition still goes
    # through the shared CLI container below.
    if CollectionCoordinator is not _DEFAULT_COLLECTION_COORDINATOR_CLASS:
        yield CollectionCoordinator()
        return
    adapters = ContainerAdapters(clock=clock) if clock is not None else None
    container = build_cli_container(adapters=adapters)
    try:
        yield container.coordinator
    finally:
        container.close()


def _run_snapshot_refresh(args, active_coordinator: CollectionCoordinator) -> int:
    selected = tuple(dict.fromkeys(args.datasets or ()))
    if args.repair_integrity and (
        not args.force
        or selected != ("core",)
        or args.history_sessions != 1
    ):
        _print_payload(
            {
                "status": "rejected",
                "error": "--repair-integrity requires --force, exactly --dataset core, and --history-sessions 1",
            }
        )
        return 2
    if args.history_sessions > 1:
        if selected != ("limits",):
            _print_payload(
                {
                    "status": "rejected",
                    "error": "--history-sessions above 1 requires exactly --dataset limits",
                }
            )
            return 2
        try:
            from .application.ports import (
                CollectionRefreshRequest,
                LimitHistoryPreparationRequest,
            )
            sessions = active_coordinator.prepare_limit_history(
                LimitHistoryPreparationRequest(args.as_of, args.history_sessions)
            )
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        results = []
        for session in sessions:
            try:
                results.append(
                    active_coordinator.collect_request(
                        CollectionRefreshRequest(
                            as_of=session,
                            datasets=("limits",),
                            fetch_previous_limit_details=False,
                        )
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
                repair_integrity=args.repair_integrity,
            )
        else:
            if args.repair_integrity:
                result = active_coordinator.collect(
                    args.as_of,
                    args.datasets,
                    repair_integrity=True,
                )
            else:
                result = active_coordinator.collect(args.as_of, args.datasets)
    except ValueError as exc:
        _print_payload({"status": "rejected", "error": str(exc)})
        return 2
    payload = _collection_payload(result, forced=args.force)
    _print_payload(payload)
    return 0 if result.run.status == "success" else 2


def _run_breadth_history(args, service=None) -> int:
    try:
        if args.apply and args.dry_run:
            raise ValueError("--apply and --dry-run cannot be combined")
        request = BreadthHistoryMaintenanceRequest(
            dates=tuple(args.maintenance_dates),
            start_date=args.start_date,
            end_date=args.end_date,
            apply=bool(args.apply and not args.dry_run),
            allow_real_provider=bool(args.allow_real_provider),
            allow_snapshot_writes=bool(args.allow_snapshot_writes),
        )
    except ValueError as exc:
        _print_payload(
            {
                "status": "rejected",
                "error": str(exc),
                "providerCalls": 0,
                "formalWrites": 0,
                "maximumDates": MAX_BREADTH_HISTORY_DATES,
            }
        )
        return 2

    # Build the runtime only after request-level gates pass.  Dry-run uses the
    # same local repository/session resolution but no provider or formal write.
    runtime = None
    try:
        if service is None:
            runtime = build_cli_container()
            service = runtime.breadth_history
        result = service.execute(request)
    except (ValueError, RuntimeError) as exc:
        _print_payload(
            {
                "status": "rejected",
                "error": str(exc),
                "providerCalls": 0,
                "formalWrites": 0,
                "maximumDates": MAX_BREADTH_HISTORY_DATES,
            }
        )
        return 2
    finally:
        if runtime is not None:
            runtime.close()
    _print_payload(result.as_dict())
    return 0 if result.as_dict()["status"] in {"planned", "success", "partial"} else 2


def main(
    argv: Sequence[str] | None = None,
    *,
    coordinator: CollectionCoordinator | None = None,
    now: Callable[[], datetime] | None = None,
    capability_runtime_factory: Callable[[], Any] | None = None,
    ths_runtime_factory: Callable[[], Any] | None = None,
    breadth_history_service: Any | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ths":
        if not args.apply:
            payload: dict[str, Any] = {
                "status": "planned",
                "operation": args.ths_command,
                "formalWrites": 0,
                "providerCalls": 0,
                "warning": "dry-run only; --apply requires manual-write, settlement, permission, budget, and capability gates",
            }
            if args.ths_command == "catalog-sync":
                payload["asOf"] = args.as_of.isoformat()
                payload["membershipCodes"] = len(set(args.membership_thscodes))
            elif args.ths_command == "turnover-backfill":
                payload.update(
                    {
                        "codes": len(set(args.thscodes)),
                        "startDate": args.start_date.isoformat(),
                        "endDate": args.end_date.isoformat(),
                    }
                )
            _print_payload(payload)
            return 0

        runtime = None
        result = None
        try:
            if ths_runtime_factory is None:
                from .bootstrap.container import build_container

                runtime = build_container()
            else:
                runtime = ths_runtime_factory()
            commands = runtime.commands.ths_sectors
            if args.ths_command == "catalog-sync":
                result = commands.start_catalog_sync(
                    as_of=args.as_of,
                    capability_revision=args.capability_revision,
                    membership_capability_revision=args.membership_capability_revision,
                    membership_thscodes=args.membership_thscodes,
                    request_budget=args.request_budget,
                )
            elif args.ths_command == "turnover-backfill":
                result = commands.start_turnover_backfill(
                    thscodes=args.thscodes,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    capability_revision=args.capability_revision,
                    request_budget=args.request_budget,
                )
            else:
                raw = json.loads(Path(args.request).read_text(encoding="utf-8"))

                def dump_request(name: str) -> dict[str, Any]:
                    value = raw[name]
                    local_path = str(value["path"])
                    if "://" in local_path:
                        raise ValueError("member import CLI accepts local files only")
                    return {
                        "path": local_path,
                        "dump_id": value["dumpId"],
                        "schema_revision": value["schemaRevision"],
                        "capability_revision": value["capabilityRevision"],
                        "checksum": value["checksum"],
                        "start_date": date.fromisoformat(value["startDate"]),
                        "end_date": date.fromisoformat(value["endDate"]),
                    }

                result = commands.start_member_import(
                    as_of=date.fromisoformat(raw["asOf"]),
                    source_revision=raw["sourceRevision"],
                    request_budget=raw.get("requestBudget"),
                    daily=dump_request("daily"),
                    adjustment=dump_request("adjustment"),
                    incremental=(
                        dump_request("incremental")
                        if raw.get("incremental") is not None
                        else None
                    ),
                )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            _close_capability_runtime(runtime)
            _print_payload(
                {"status": "rejected", "error": "THS operation input could not be read"}
            )
            return 2
        except Exception as exc:
            from .application.commands import ThsOperationGateError

            _close_capability_runtime(runtime)
            if isinstance(exc, (ValueError, ThsOperationGateError)):
                error = str(exc)
            else:
                error = "THS operation runtime is unavailable"
            _print_payload({"status": "rejected", "error": error})
            return 2
        if not _close_capability_runtime(runtime):
            _print_payload(
                {"status": "rejected", "error": "THS operation runtime did not close cleanly"}
            )
            return 3
        _print_payload(dict(result or {}))
        return 0
    if args.command == "capabilities" and args.capability_command == "promote":
        runtime = None
        try:
            envelope = (
                json.load(sys.stdin)
                if args.input == "-"
                else json.loads(Path(args.input).read_text(encoding="utf-8"))
            )
            runtime_builder = (
                capability_runtime_factory or build_capability_promotion_runtime
            )
            runtime = runtime_builder()
            result = runtime.command.execute(
                envelope,
                provider=args.provider,
                dataset=args.dataset,
                revision=args.revision,
                target_backend=runtime.target_backend,
                apply=args.apply,
            )
        except CapabilityPromotionRepositoryError:
            _close_capability_runtime(runtime)
            _print_payload(
                {
                    "status": "rejected",
                    "error": "capability repository operation failed",
                }
            )
            return 3
        except CapabilityPromotionError as exc:
            _close_capability_runtime(runtime)
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        except (OSError, UnicodeError, json.JSONDecodeError):
            _close_capability_runtime(runtime)
            _print_payload(
                {"status": "rejected", "error": "capability input could not be read"}
            )
            return 2
        except Exception:
            _close_capability_runtime(runtime)
            _print_payload(
                {
                    "status": "rejected",
                    "error": "capability repository operation failed",
                }
            )
            return 3
        if not _close_capability_runtime(runtime):
            _print_payload(
                {
                    "status": "rejected",
                    "error": "capability repository operation failed",
                }
            )
            return 3
        _print_payload(result.to_dict())
        return 0
    if args.command == "fuyao":
        if args.fuyao_command == "capability-probe":
            try:
                payload = _run_offline_capability_probe(Path(args.fixture), args.as_of)
                if args.path:
                    store = LegacySqliteSnapshotStore(args.path)
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
            probe_now = _market_now(now)
            try:
                _validate_fuyao_real_probe_boundary(args.as_of, probe_now)
            except ValueError as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
            if not os.getenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "").strip():
                _print_payload({"status": "rejected", "error": "MARKET_ENVIRONMENT_FUYAO_API_KEY is required"})
                return 2
            try:
                adapter = FuyaoMarketAdapter(FuyaoMarketClient())
                # Current-date core evidence must include an independent quote
                # source; historical probes intentionally remain quote-free.
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
                core_result = _core_probe_result(
                    core_results,
                    args.as_of,
                    revision=getattr(adapter, "source_revision", "fuyao-market-v2"),
                    permission_evidence={
                        "configured": client_configured,
                        "approved": True,
                        "mode": "explicit-real-probe",
                    },
                    rate_limit_evidence={
                        "requestBudget": request_budget,
                        "requestsUsed": request_count,
                    },
                    independent_quote_checked=bool(quotes),
                    independent_quote_samples=len(quotes),
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
                store = LegacySqliteSnapshotStore(args.path)
                for item in payload["reports"]:
                    store.put_capability_report(ProviderCapabilityReport.from_dict(item))
                _print_payload(payload)
                return 0
            except Exception as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
        if args.fuyao_command == "ths-real-probe":
            if not args.allow_real:
                _print_payload({"status": "rejected", "error": "real probe requires --allow-real"})
                return 2
            probe_now = _market_now(now)
            try:
                _validate_fuyao_real_probe_boundary(args.as_of, probe_now)
            except ValueError as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
            if not os.getenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", "").strip():
                _print_payload({"status": "rejected", "error": "MARKET_ENVIRONMENT_FUYAO_API_KEY is required"})
                return 2
            try:
                _validate_isolated_probe_paths(args.output, args.path)
                payload = run_fuyao_ths_capability_probe(
                    as_of=args.as_of,
                    thscode=args.thscode,
                    history_start=args.history_start,
                    max_dump_bytes=args.max_dump_bytes,
                    revisions={
                        "industry-ranking": args.catalog_revision,
                        "sector-membership": args.membership_revision,
                        "sector-turnover-history": args.history_revision,
                        "sector-member-daily-dump": args.daily_dump_revision,
                        "sector-member-incremental-dump": args.incremental_dump_revision,
                        "sector-member-adjustment-dump": args.adjustment_dump_revision,
                    },
                    now=lambda: probe_now.astimezone(timezone.utc),
                )
                Path(args.output).write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8",
                )
                store = LegacySqliteSnapshotStore(args.path)
                for item in payload["reports"]:
                    store.put_capability_report(ProviderCapabilityReport.from_dict(item))
                _print_payload(payload)
                return 0 if all(item["status"] == "eligible" for item in payload["reports"]) else 2
            except Exception as exc:
                error = str(exc) if isinstance(exc, ValueError) else "THS capability probe failed"
                _print_payload({"status": "rejected", "error": error})
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
    if args.command == "sectors-html" and args.sectors_html_command == "real-probe":
        try:
            payload = _run_sectors_html_real_probe(
                as_of=args.as_of,
                source=args.source,
                allow_real=args.allow_real,
            )
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        _print_payload(payload)
        return 0 if payload.get("status") == "ok" else 2
    if args.command == "industry-capability-probe":
        from .interfaces.cli.industry_capability_probe import (
            IndustryProbeError,
            run_industry_capability_probe,
        )

        try:
            payload = run_industry_capability_probe(
                dataset=args.dataset,
                source=args.source,
                revision=args.revision,
                as_of=args.as_of,
                output=args.output,
                allow_real=args.allow_real,
            )
        except IndustryProbeError as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        _print_payload(payload)
        return 0 if payload.get("status") == "dry-run" else 2
    if args.command == "sector-continuity":
        if args.continuity_command == "backfill":
            revisions: dict[str, str] = {}
            for item in args.source_revision:
                if "=" not in item:
                    _print_payload({"status": "rejected", "error": "--source-revision must use KEY=VALUE"})
                    return 2
                key, value = item.split("=", 1)
                if not key.strip() or not value.strip():
                    _print_payload({"status": "rejected", "error": "--source-revision must use non-empty KEY=VALUE"})
                    return 2
                revisions[key.strip()] = value.strip()
            try:
                from .application.commands import BackfillRequest

                request = BackfillRequest(
                    as_of=args.as_of,
                    start_as_of=args.start_as_of,
                    sessions=args.sessions,
                    calculation_version=args.calculation_version,
                    source_revisions=revisions,
                )
                supplied_sessions = tuple(sorted(set(args.session_date)))
                if supplied_sessions and any(item > args.as_of for item in supplied_sessions):
                    raise ValueError("--session-date cannot be later than --as-of")
            except ValueError as exc:
                _print_payload({"status": "rejected", "error": str(exc)})
                return 2
            if args.apply:
                _print_payload({"status": "rejected", "error": "backfill runtime is not configured; production DB/provider writes require separate authorization"})
                return 2
            _print_payload({
                "status": "planned",
                "asOf": args.as_of.isoformat(),
                "startAsOf": args.start_as_of.isoformat() if args.start_as_of else None,
                "sessions": args.sessions,
                "sessionDates": [item.isoformat() for item in supplied_sessions],
                "calculationVersion": args.calculation_version,
                "sourceRevisions": revisions,
                "formalWrites": 0,
                "providerCalls": 0,
                "warning": "dry-run plan only; pass through an authorized application runtime to execute",
            })
            return 0
        if args.continuity_command == "readiness":
            _print_payload({
                "status": "unavailable",
                "asOf": args.as_of.isoformat(),
                "requiredHistory": args.required_history,
                "availableHistory": 0,
                "missingSessions": [],
                "coverage": 0,
                "providerCalls": 0,
                "warning": "local readiness repository is not configured; this command never starts backfill",
            })
            return 0
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
        with _collection_coordinator_scope(coordinator) as active_coordinator:
            return _run_snapshot_refresh(args, active_coordinator)
    if args.command == "snapshots" and args.snapshot_command == "breadth-history":
        return _run_breadth_history(args, breadth_history_service)
    if args.command == "snapshots" and args.snapshot_command in {"relabel-date", "relabel", "migrate-date", "date-relabel", "migrate"}:
        # Date relabels must always select their backend explicitly.  In
        # particular, never fall back to MARKET_ENVIRONMENT_SNAPSHOT_PATH:
        # that variable is reserved for the one-shot SQLite import tool.
        if bool(args.path) == bool(args.database_url):
            _print_payload({"status": "rejected", "error": "exactly one of --path or --database-url is required"})
            return 2
        try:
            store = LegacySqliteSnapshotStore(args.path) if args.path else SnapshotStore(database_url=args.database_url)
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
            store = LegacySqliteSnapshotStore(args.path) if args.path else SnapshotStore(database_url=args.database_url)
            result = rollback_date_relabel(store, args.audit_id, apply=bool(args.apply and not args.dry_run))
        except Exception as exc:
            _print_payload({"status": "rejected", "error": str(exc)})
            return 2
        _print_payload(result.as_dict())
        return 0 if result.status in {"dry-run", "rolled-back"} else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
