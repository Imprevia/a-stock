"""Explicit Fuyao THS write operations with fail-closed provider gates."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from ...domain.analysis.ths_sector import catalog_checksum, catalog_observation_revision_id
from ...domain.models.ths_sector import (
    ThsBackfillCheckpoint,
    ThsBackfillRun,
    ThsOperation,
    ThsSectorBar,
    normalize_thscode,
)
def _checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _enabled(value: bool | Callable[[], bool]) -> bool:
    return value() if callable(value) else bool(value)


def _request_count(adapter: Any | None) -> int:
    if adapter is None:
        return 0
    return max(0, int(getattr(adapter.client, "request_count", 0)))


def _merge_daily_dump_rows(
    daily_rows: Sequence[Mapping[str, Any]],
    incremental_rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Overlay the recent dump by business key before immutable persistence."""

    selected: dict[tuple[str, date], Mapping[str, Any]] = {}
    for raw in (*daily_rows, *incremental_rows):
        key = (str(raw.get("security_id") or ""), raw.get("date"))
        if not key[0] or not isinstance(key[1], date):
            raise ValueError("member dump row lacks a normalized business key")
        selected[(key[0], key[1])] = raw
    return [selected[key] for key in sorted(selected)]


def catalog_sync_request_plan(
    catalog_report: Any,
    membership_report: Any,
    *,
    explicit_membership_codes: int,
    snapshot_batch_size: int = 80,
) -> tuple[int, int, int]:
    """Return catalog requests, membership upper bound, and total budget floor."""

    fields = dict(getattr(catalog_report, "field_coverage", {}) or {})
    try:
        unique_codes = int(fields["uniqueCodes"])
        tag_counts = {str(key): int(value) for key, value in dict(fields["tagCounts"]).items()}
    except (KeyError, TypeError, ValueError) as exc:
        raise ThsOperationGateError(
            "catalog capability lacks request-planning evidence"
        ) from exc
    if unique_codes < 1 or set(tag_counts) != {"industry", "cn_concept", "region", "tszs"}:
        raise ThsOperationGateError("catalog capability lacks request-planning evidence")
    catalog_requests = 4 + max(1, (unique_codes + snapshot_batch_size - 1) // snapshot_batch_size)
    membership_requests = sum(min(10, max(0, count)) for count in tag_counts.values())
    membership_requests += max(0, int(explicit_membership_codes))
    catalog_budget = int(catalog_report.rate_limit_evidence["requestBudget"])
    membership_budget = int(membership_report.rate_limit_evidence["requestBudget"])
    if catalog_requests > catalog_budget:
        raise ThsOperationGateError(
            "catalog request plan exceeds industry-ranking capability evidence"
        )
    if membership_requests > membership_budget:
        raise ThsOperationGateError(
            "membership request plan exceeds sector-membership capability evidence"
        )
    return catalog_requests, membership_requests, catalog_requests + membership_requests


class ThsOperationGateError(RuntimeError):
    pass


class ThsDumpManifestLike(Protocol):
    dump_id: str
    kind: str
    schema_revision: str
    capability_revision: str
    checksum: str
    start_date: date
    end_date: date


class ThsDumpReader(Protocol):
    def read(
        self,
        path: str | Path,
        manifest: ThsDumpManifestLike,
    ) -> Sequence[Mapping[str, Any]]: ...


class ThsMemberFactMerger(Protocol):
    def __call__(
        self,
        daily_rows: Sequence[Mapping[str, Any]],
        adjustment_rows: Sequence[Mapping[str, Any]],
        *,
        source_revision: str,
        tdx_rows: Sequence[Mapping[str, Any]],
    ) -> Sequence[Any]: ...


@dataclass(frozen=True, slots=True)
class ThsOperationGates:
    manual_write_enabled: bool | Callable[[], bool]
    authorized: bool | Callable[[], bool]
    after_market: Callable[[date], bool]

    def require(self, as_of: date) -> None:
        if not _enabled(self.manual_write_enabled):
            raise ThsOperationGateError("manual THS writes are disabled")
        if not _enabled(self.authorized):
            raise ThsOperationGateError("THS write permission is not authorized")
        if not self.after_market(as_of):
            raise ThsOperationGateError("THS provider writes require a completed Shanghai session")


@dataclass(frozen=True, slots=True)
class CatalogSyncRequest:
    as_of: date
    capability_revision: str
    request_budget: int
    run_id: str | None = None
    membership_capability_revision: str | None = None
    membership_thscodes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_revision.strip():
            raise ValueError("catalog capability_revision is required")
        if self.membership_capability_revision is not None and not self.membership_capability_revision.strip():
            raise ValueError("membership capability_revision must not be blank")
        if self.request_budget < 1:
            raise ValueError("catalog sync request_budget must be positive")
        codes = tuple(sorted({normalize_thscode(code) for code in self.membership_thscodes}))
        if len(codes) > 60:
            raise ValueError("catalog sync accepts at most 60 selected membership codes")
        object.__setattr__(self, "membership_thscodes", codes)


@dataclass(frozen=True, slots=True)
class TurnoverBackfillRequest:
    thscodes: tuple[str, ...]
    start_date: date
    end_date: date
    capability_revision: str
    request_budget: int
    run_id: str | None = None
    window_days: int = 366

    def as_run(self, run_id: str) -> ThsBackfillRun:
        if self.window_days < 1:
            raise ValueError("window_days must be positive")
        return ThsBackfillRun(
            run_id=run_id,
            thscodes=self.thscodes,
            start_date=self.start_date,
            end_date=self.end_date,
            capability_revision=self.capability_revision,
            request_budget=self.request_budget,
        )


@dataclass(frozen=True, slots=True)
class MemberImportRequest:
    as_of: date
    daily_path: str | Path
    daily_manifest: ThsDumpManifestLike
    adjustment_path: str | Path
    adjustment_manifest: ThsDumpManifestLike
    source_revision: str
    request_budget: int | None = None
    incremental_path: str | Path | None = None
    incremental_manifest: ThsDumpManifestLike | None = None
    tdx_rows: Sequence[Mapping[str, Any]] = ()
    run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_revision.strip():
            raise ValueError("member import source_revision is required")
        if self.request_budget is not None and self.request_budget <= 0:
            raise ValueError("member import request_budget must be positive when supplied")
        if (self.incremental_path is None) != (self.incremental_manifest is None):
            raise ValueError("incremental path and manifest must be supplied together")
        if self.daily_manifest.kind != "daily":
            raise ValueError("daily manifest kind must be daily")
        if self.adjustment_manifest.kind != "adjustment":
            raise ValueError("adjustment manifest kind must be adjustment")
        if self.incremental_manifest and self.incremental_manifest.kind != "incremental":
            raise ValueError("incremental manifest kind must be incremental")


class ThsCatalogSyncService:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], Any],
        *,
        adapter_factory: Callable[[], Any],
        capability_policy: Any,
        gates: ThsOperationGates,
        clock: Callable[[], datetime] = _clock,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._adapter_factory = adapter_factory
        self._capability_policy = capability_policy
        self._gates = gates
        self._clock = clock

    def run(self, request: CatalogSyncRequest):
        self._gates.require(request.as_of)
        report = self._capability_policy.require(
            "industry-ranking",
            request.capability_revision,
        )
        membership_report = None
        if request.membership_capability_revision is not None:
            membership_report = self._capability_policy.require(
                "sector-membership",
                request.membership_capability_revision,
            )
            catalog_requests, membership_request_limit, minimum_budget = catalog_sync_request_plan(
                report,
                membership_report,
                explicit_membership_codes=len(request.membership_thscodes),
            )
            authorized_budget = min(
                int(report.rate_limit_evidence["requestBudget"]),
                int(membership_report.rate_limit_evidence["requestBudget"]),
            )
            if request.request_budget < minimum_budget:
                raise ThsOperationGateError(
                    f"catalog sync request budget must be at least {minimum_budget}"
                )
        else:
            # Direct legacy service callers may omit membership.  The formal
            # HTTP/compatibility runtime always supplies the exact membership
            # revision, so this cannot bypass the production gate.
            membership_request_limit = 0
            authorized_budget = int(report.rate_limit_evidence["requestBudget"])
        if request.request_budget > authorized_budget:
            raise ThsOperationGateError("catalog sync request budget exceeds capability evidence")
        run_id = request.run_id or uuid.uuid4().hex
        requested_at = self._clock()
        operation = ThsOperation(
            run_id=run_id,
            kind="catalog-sync",
            status="running",
            capability_revision=request.capability_revision,
            request_checksum=_checksum(
                {
                    "asOf": request.as_of.isoformat(),
                    "capabilityRevision": request.capability_revision,
                    "membershipCapabilityRevision": request.membership_capability_revision,
                    "membershipThscodes": list(request.membership_thscodes),
                    "requestBudget": request.request_budget,
                }
            ),
            requested_at=requested_at,
            started_at=requested_at,
            request_metadata={
                "asOf": request.as_of.isoformat(),
                "membershipCapabilityRevision": request.membership_capability_revision,
                "membershipThscodes": list(request.membership_thscodes),
            },
            total_items=4 + membership_request_limit,
            request_budget=request.request_budget,
        )
        self._put_operation(operation)
        adapter = None
        before = 0
        try:
            adapter = self._adapter_factory()
            before = _request_count(adapter)
            client_budget = int(getattr(adapter.client, "request_budget", 0) or 0)
            if client_budget < request.request_budget:
                raise ThsOperationGateError(
                    "catalog sync request budget exceeds the Fuyao client budget"
                )
            bundle = adapter.fetch_catalog_snapshot(request.as_of)
            requests_used = max(0, _request_count(adapter) - before)
            if requests_used > int(report.rate_limit_evidence["requestBudget"]):
                raise ThsOperationGateError(
                    "catalog sync exceeded industry-ranking capability evidence"
                )
            if requests_used > request.request_budget:
                raise ThsOperationGateError("catalog sync exhausted its request budget")
            missing_live_codes, missing_ranking_codes = self._validate_bundle(
                bundle,
                request.as_of,
            )
            bars = tuple(
                self._snapshot_bar(item, bundle.revision.revision_id)
                for item in bundle.snapshots
                if self._has_live_values(item)
            )
            with self._uow_factory() as unit_of_work:
                repository = unit_of_work.ths_sectors
                repository.put_catalog_revision(bundle.revision, bundle.relations)
                ranking_counts = repository.put_rankings(bundle.rankings)
                bar_counts = repository.put_sector_bars(bars)
                conflicts = int(ranking_counts.get("conflict", 0)) + int(bar_counts.get("conflict", 0))
                if conflicts:
                    raise ValueError("catalog sync encountered immutable fact conflicts")
                unit_of_work.commit()
            membership_codes = tuple(
                sorted(
                    {
                        *(
                            row.thscode
                            for row in bundle.rankings
                            if row.rank <= 10
                            and row.change_pct is not None
                            and getattr(row, "quality", "ok")
                            not in {"insufficient", "missing", "failed"}
                        ),
                        *request.membership_thscodes,
                    }
                )
            ) if membership_report is not None else ()
            membership_results: dict[str, dict[str, Any]] = {}
            membership_successes = 0
            membership_failures = 0
            membership_conflicts = 0
            membership_requests_used = 0
            for code in membership_codes:
                if requests_used >= request.request_budget:
                    membership_failures += 1
                    membership_results[code] = {
                        "status": "failed",
                        "warning": "request budget exhausted",
                    }
                    continue
                membership_before = _request_count(adapter)
                membership_delta = 0
                try:
                    memberships = adapter.fetch_memberships(code, as_of=request.as_of)
                    membership_delta = max(
                        0, _request_count(adapter) - membership_before
                    )
                    requests_used += membership_delta
                    membership_requests_used += membership_delta
                    if membership_requests_used > int(
                        membership_report.rate_limit_evidence["requestBudget"]
                    ):
                        raise ThsOperationGateError(
                            "catalog sync exceeded sector-membership capability evidence"
                        )
                    if requests_used > request.request_budget:
                        raise ThsOperationGateError(
                            "catalog sync exhausted its request budget"
                        )
                    with self._uow_factory() as unit_of_work:
                        counts = unit_of_work.ths_sectors.put_sector_memberships(
                            memberships
                        )
                        if counts.get("conflict"):
                            membership_conflicts += 1
                            membership_results[code] = {
                                "status": "conflict",
                                "rows": len(memberships),
                            }
                            continue
                        unit_of_work.commit()
                    membership_successes += 1
                    membership_results[code] = {
                        "status": "success",
                        "rows": len(memberships),
                    }
                except Exception as exc:
                    if membership_delta == 0:
                        membership_delta = max(
                            0, _request_count(adapter) - membership_before
                        )
                        requests_used += membership_delta
                        membership_requests_used += membership_delta
                    membership_failures += 1
                    membership_results[code] = {
                        "status": "failed",
                        "warning": str(exc),
                    }
            value_gaps = bool(missing_live_codes or missing_ranking_codes)
            status = (
                "success"
                if not membership_failures and not membership_conflicts and not value_gaps
                else "partial"
            )
            warning_parts: list[str] = []
            if membership_failures or membership_conflicts:
                warning_parts.append(
                    f"{membership_failures} membership code(s) failed; "
                    f"{membership_conflicts} conflict(s) retained"
                )
            if value_gaps:
                warning_parts.append(
                    f"{len(missing_live_codes)} live-value gap(s); "
                    f"{len(missing_ranking_codes)} ranking-value gap(s)"
                )
            warning = "; ".join(warning_parts) or None
            completed = replace(
                operation,
                status=status,
                completed_at=self._clock(),
                total_items=4 + len(membership_codes),
                completed_items=4 + membership_successes,
                failed_items=membership_failures,
                conflict_items=membership_conflicts,
                requests_used=requests_used,
                progress={
                    "tagsCompleted": 4,
                    "catalogRows": len(bundle.relations),
                    "expectedCodes": len({row.thscode for row in bundle.relations}),
                    "barRows": len(bars),
                    "missingLiveCodes": list(missing_live_codes),
                    "missingRankingCodes": list(missing_ranking_codes),
                    "membershipCodes": membership_results,
                },
                result={
                    "catalogRevisionId": bundle.revision.revision_id,
                    "catalogRevision": bundle.revision.revision_id,
                    "rankingRows": len(bundle.rankings),
                    "barRows": len(bars),
                    "membershipCapabilityRevision": request.membership_capability_revision,
                    "membershipCodes": len(membership_codes),
                },
                warning=warning,
            )
            self._put_operation(completed)
            return bundle, completed
        except Exception as exc:
            failed = replace(
                operation,
                status="failed",
                completed_at=self._clock(),
                failed_items=4,
                warning=str(exc),
                requests_used=max(
                    0,
                    _request_count(adapter) - before,
                ),
            )
            self._put_operation(failed)
            raise

    def _put_operation(self, operation: ThsOperation) -> None:
        with self._uow_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_operation(operation)
            unit_of_work.commit()

    @staticmethod
    def _has_live_values(snapshot: Any) -> bool:
        declared = getattr(snapshot, "has_live_values", None)
        if declared is not None:
            return bool(declared)
        return any(
            getattr(snapshot, name) is not None
            for name in ("open", "high", "low", "close", "volume", "turnover")
        )

    @classmethod
    def _validate_bundle(
        cls,
        bundle: Any,
        as_of: date,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        revision_id = bundle.revision.revision_id
        if revision_id == bundle.revision.capability_revision:
            raise ValueError(
                "catalog sync requires a date-and-content catalog observation revision"
            )
        relations = tuple(bundle.relations)
        expected_checksum = catalog_checksum(relations)
        if bundle.revision.checksum != expected_checksum:
            raise ValueError("catalog sync catalog checksum does not match relations")
        expected_revision = catalog_observation_revision_id(
            provider=bundle.revision.source,
            capability_revision=bundle.revision.capability_revision,
            as_of=as_of,
            checksum=expected_checksum,
        )
        if revision_id != expected_revision:
            raise ValueError(
                "catalog sync catalog revision does not match date-and-content identity"
            )
        snapshots = tuple(bundle.snapshots)
        rankings = tuple(bundle.rankings)
        relation_keys = [(row.tag, row.thscode) for row in relations]
        ranking_keys = [(row.tag, row.thscode) for row in rankings]
        if (
            len(relation_keys) != len(set(relation_keys))
            or len(ranking_keys) != len(set(ranking_keys))
            or set(relation_keys) != set(ranking_keys)
        ):
            raise ValueError("catalog sync rankings do not cover complete catalog relations")
        if any(row.revision_id != revision_id for row in relations):
            raise ValueError("catalog sync relation revision mismatch")
        if any(
            row.catalog_revision != revision_id or row.as_of != as_of
            for row in rankings
        ):
            raise ValueError("catalog sync ranking revision/date mismatch")
        expected_codes = {row.thscode for row in relations}
        observed_codes = [row.thscode for row in snapshots]
        if len(observed_codes) != len(set(observed_codes)) or set(observed_codes) != expected_codes:
            raise ValueError("catalog sync snapshot identities do not cover the catalog")
        if any(row.as_of != as_of for row in snapshots):
            raise ValueError("catalog sync snapshot date mismatch")
        computed_live = {
            row.thscode for row in snapshots if not cls._has_live_values(row)
        }
        computed_ranking = {
            row.thscode for row in snapshots if row.change_pct is None
        }

        def declared(name: str, computed: set[str]) -> tuple[str, ...]:
            value = getattr(bundle, name, None)
            if value is None:
                return tuple(sorted(computed))
            normalized = tuple(str(code).strip().upper() for code in value)
            if len(normalized) != len(set(normalized)) or set(normalized) != computed:
                raise ValueError(f"catalog sync {name} do not match snapshot availability")
            return tuple(sorted(normalized))

        missing_live_codes = declared("missing_live_codes", computed_live)
        missing_ranking_codes = declared("missing_ranking_codes", computed_ranking)
        ranking_missing = {
            row.thscode for row in rankings if row.change_pct is None
        }
        if ranking_missing != set(missing_ranking_codes):
            raise ValueError(
                "catalog sync missing_ranking_codes do not match ranking rows"
            )
        bar_codes = {
            row.thscode for row in snapshots if cls._has_live_values(row)
        }
        if bar_codes & set(missing_live_codes) or bar_codes | set(
            missing_live_codes
        ) != expected_codes:
            raise ValueError("catalog sync live-value coverage does not reconcile")
        return missing_live_codes, missing_ranking_codes

    @staticmethod
    def _snapshot_bar(snapshot: Any, source_revision: str) -> ThsSectorBar:
        logical = {
            "thscode": snapshot.thscode,
            "tradingDate": snapshot.as_of.isoformat(),
            "open": snapshot.open,
            "high": snapshot.high,
            "low": snapshot.low,
            "close": snapshot.close,
            "volume": snapshot.volume,
            "turnover": snapshot.turnover,
            "sourceRevision": source_revision,
        }
        missing = tuple(
            f"{name} is unavailable"
            for name in ("open", "high", "low", "close", "volume", "turnover")
            if getattr(snapshot, name) is None
        )
        return ThsSectorBar(
            thscode=snapshot.thscode,
            trading_date=snapshot.as_of,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
            turnover=snapshot.turnover,
            source="fuyao",
            source_revision=source_revision,
            checksum=_checksum(logical),
            fetched_at=snapshot.provider_timestamp,
            quality="partial" if missing else "ok",
            warnings=missing,
        )


class ThsTurnoverBackfillService:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], Any],
        *,
        adapter_factory: Callable[[], Any],
        capability_policy: Any,
        gates: ThsOperationGates,
        clock: Callable[[], datetime] = _clock,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._adapter_factory = adapter_factory
        self._capability_policy = capability_policy
        self._gates = gates
        self._clock = clock

    def run(self, request: TurnoverBackfillRequest) -> ThsBackfillRun:
        self._gates.require(request.end_date)
        report = self._capability_policy.require(
            "sector-turnover-history",
            request.capability_revision,
        )
        authorized_budget = int(report.rate_limit_evidence["requestBudget"])
        if request.request_budget > authorized_budget:
            raise ThsOperationGateError("backfill request budget exceeds capability evidence")
        run_id = request.run_id or uuid.uuid4().hex
        requested = request.as_run(run_id)
        existing, checkpoints = self._load_run(run_id)
        if existing is not None:
            requested = replace(requested, requests_used=existing.requests_used)
        self._put_run(requested)
        windows = tuple(
            self._windows(
                requested.start_date,
                requested.end_date,
                request.window_days,
            )
        )
        planned_keys = {
            (code, window_start, window_end)
            for code in requested.thscodes
            for window_start, window_end in windows
        }
        completed_keys = {
            (item.thscode, item.window_start, item.window_end)
            for item in checkpoints
            if item.status == "success"
        }
        adapter = None
        requests_used = requested.requests_used
        outcomes: list[ThsBackfillCheckpoint] = list(checkpoints)
        known_keys = {
            (item.thscode, item.window_start, item.window_end) for item in checkpoints
        }
        for code in requested.thscodes:
            for window_start, window_end in windows:
                key = (code, window_start, window_end)
                if key in completed_keys:
                    continue
                if requests_used >= request.request_budget:
                    checkpoint = ThsBackfillCheckpoint(
                        run_id,
                        code,
                        window_start,
                        window_end,
                        "failed",
                        request.capability_revision,
                        warning="request budget exhausted",
                    )
                    self._put_checkpoint(checkpoint)
                    if key in known_keys:
                        outcomes = [item for item in outcomes if (item.thscode, item.window_start, item.window_end) != key]
                    outcomes.append(checkpoint)
                    known_keys.add(key)
                    continue
                running = ThsBackfillCheckpoint(
                    run_id,
                    code,
                    window_start,
                    window_end,
                    "running",
                    request.capability_revision,
                )
                self._put_checkpoint(running)
                before = 0
                try:
                    if adapter is None:
                        adapter = self._adapter_factory()
                    before = _request_count(adapter)
                    bars = adapter.fetch_history(
                        code,
                        start_date=window_start,
                        end_date=window_end,
                    )
                    with self._uow_factory() as unit_of_work:
                        counts = unit_of_work.ths_sectors.put_sector_bars(bars)
                        state = "conflict" if counts.get("conflict") else "success"
                        checkpoint = ThsBackfillCheckpoint(
                            run_id,
                            code,
                            window_start,
                            window_end,
                            state,
                            request.capability_revision,
                            rows_written=int(counts.get("inserted", 0)),
                            rows_skipped=int(counts.get("identical", 0)),
                            conflicts=int(counts.get("conflict", 0)),
                            warning=(
                                "immutable bar conflicts retained"
                                if counts.get("conflict")
                                else None
                            ),
                        )
                        unit_of_work.ths_sectors.put_backfill_checkpoint(checkpoint)
                        unit_of_work.commit()
                except Exception as exc:
                    checkpoint = ThsBackfillCheckpoint(
                        run_id,
                        code,
                        window_start,
                        window_end,
                        "failed",
                        request.capability_revision,
                        warning=str(exc),
                    )
                    self._put_checkpoint(checkpoint)
                requests_used += max(0, _request_count(adapter) - before)
                outcomes = [
                    item
                    for item in outcomes
                    if (item.thscode, item.window_start, item.window_end) != key
                ]
                outcomes.append(checkpoint)
                known_keys.add(key)
                self._put_run(replace(requested, status="running", requests_used=requests_used))
        terminal = [
            item
            for item in outcomes
            if (item.thscode, item.window_start, item.window_end) in planned_keys
            and item.status != "running"
        ]
        success_count = sum(item.status == "success" for item in terminal)
        partial_count = sum(item.status == "partial" for item in terminal)
        failed_count = sum(item.status == "failed" for item in terminal)
        conflict_count = sum(item.status == "conflict" for item in terminal)
        if terminal and success_count == len(planned_keys):
            status = "success"
        elif success_count or partial_count:
            status = "partial"
        elif conflict_count and not failed_count:
            status = "conflict"
        else:
            status = "failed"
        warning = None
        if partial_count or failed_count or conflict_count:
            warning = (
                f"{partial_count} checkpoint(s) partial; "
                f"{failed_count} failed; {conflict_count} conflict(s) retained"
            )
        completed = replace(
            requested,
            status=status,
            requests_used=requests_used,
            warning=warning,
        )
        self._put_run(completed)
        operation = self._get_operation(run_id)
        if operation is not None:
            self._put_operation(
                replace(
                    operation,
                    status=status,
                    completed_at=self._clock(),
                    total_items=len(planned_keys),
                    completed_items=success_count + partial_count,
                    failed_items=failed_count,
                    conflict_items=conflict_count,
                    requests_used=requests_used,
                    warning=warning,
                    progress={
                        "checkpoints": len(terminal),
                        "partialCheckpoints": partial_count,
                    },
                )
            )
        return completed

    @staticmethod
    def _windows(start_date: date, end_date: date, window_days: int):
        current = start_date
        while current <= end_date:
            window_end = min(end_date, current + timedelta(days=window_days - 1))
            yield current, window_end
            current = window_end + timedelta(days=1)

    def _load_run(self, run_id: str):
        with self._uow_factory() as unit_of_work:
            return (
                unit_of_work.ths_sectors.get_backfill_run(run_id),
                tuple(unit_of_work.ths_sectors.list_backfill_checkpoints(run_id)),
            )

    def _put_run(self, run: ThsBackfillRun) -> None:
        with self._uow_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_backfill_run(run)
            unit_of_work.commit()

    def _put_checkpoint(self, checkpoint: ThsBackfillCheckpoint) -> None:
        with self._uow_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_backfill_checkpoint(checkpoint)
            unit_of_work.commit()

    def _get_operation(self, run_id: str):
        with self._uow_factory() as unit_of_work:
            return unit_of_work.ths_sectors.get_operation(run_id)

    def _put_operation(self, operation: ThsOperation) -> None:
        with self._uow_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_operation(operation)
            unit_of_work.commit()


class ThsMemberImportService:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], Any],
        *,
        reader: ThsDumpReader,
        fact_merger: ThsMemberFactMerger,
        capability_policy: Any,
        gates: ThsOperationGates,
        clock: Callable[[], datetime] = _clock,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._reader = reader
        self._fact_merger = fact_merger
        self._capability_policy = capability_policy
        self._gates = gates
        self._clock = clock

    def run(self, request: MemberImportRequest) -> ThsOperation:
        self._gates.require(request.as_of)
        capabilities = [
            ("sector-member-daily-dump", request.daily_manifest.capability_revision),
            ("sector-member-adjustment-dump", request.adjustment_manifest.capability_revision),
        ]
        if request.incremental_manifest is not None:
            capabilities.append(
                (
                    "sector-member-incremental-dump",
                    request.incremental_manifest.capability_revision,
                )
            )
        for dataset, revision in capabilities:
            self._capability_policy.require(dataset, revision)

        run_id = request.run_id or uuid.uuid4().hex
        now = self._clock()
        manifests = [request.daily_manifest, request.adjustment_manifest]
        if request.incremental_manifest is not None:
            manifests.append(request.incremental_manifest)
        metadata = {
            "asOf": request.as_of.isoformat(),
            "dumpIds": [item.dump_id for item in manifests],
            "checksums": [item.checksum for item in manifests],
            "schemaRevisions": [item.schema_revision for item in manifests],
        }
        operation = ThsOperation(
            run_id=run_id,
            kind="member-import",
            status="running",
            capability_revision=request.source_revision,
            request_checksum=_checksum(metadata),
            requested_at=now,
            started_at=now,
            request_metadata=metadata,
            total_items=len(manifests),
            request_budget=request.request_budget,
        )
        self._put_operation(operation)
        try:
            daily_rows = list(self._reader.read(request.daily_path, request.daily_manifest))
            if request.incremental_path is not None and request.incremental_manifest is not None:
                daily_rows = _merge_daily_dump_rows(
                    daily_rows,
                    self._reader.read(
                        request.incremental_path,
                        request.incremental_manifest,
                    ),
                )
            adjustment_rows = self._reader.read(
                request.adjustment_path,
                request.adjustment_manifest,
            )
            facts = self._fact_merger(
                daily_rows,
                adjustment_rows,
                source_revision=request.source_revision,
                tdx_rows=request.tdx_rows,
            )
            counts = {"inserted": 0, "identical": 0, "conflict": 0}
            with self._uow_factory() as unit_of_work:
                for fact in facts:
                    outcome = unit_of_work.ths_sectors.put_member_fact(fact)
                    counts[outcome] += 1
                if counts["conflict"]:
                    raise ValueError("member import encountered immutable fact conflicts")
                unit_of_work.commit()
            completed = replace(
                operation,
                status="success",
                completed_at=self._clock(),
                completed_items=len(manifests),
                result={"facts": len(facts), **counts},
            )
            self._put_operation(completed)
            return completed
        except Exception as exc:
            failed = replace(
                operation,
                status="failed",
                completed_at=self._clock(),
                failed_items=len(manifests),
                warning=str(exc),
            )
            self._put_operation(failed)
            raise

    def _put_operation(self, operation: ThsOperation) -> None:
        with self._uow_factory() as unit_of_work:
            unit_of_work.ths_sectors.put_operation(operation)
            unit_of_work.commit()


__all__ = [
    "CatalogSyncRequest",
    "MemberImportRequest",
    "ThsCatalogSyncService",
    "ThsDumpManifestLike",
    "ThsDumpReader",
    "ThsMemberImportService",
    "ThsMemberFactMerger",
    "ThsOperationGateError",
    "ThsOperationGates",
    "ThsTurnoverBackfillService",
    "TurnoverBackfillRequest",
]
