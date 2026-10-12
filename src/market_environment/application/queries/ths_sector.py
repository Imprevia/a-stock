"""Provider-free local queries for normalized THS sector datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..ports import ThsSectorRepository
from ...domain.models.ths_sector import THS_TAGS, normalize_thscode


def _page(page: int, page_size: int, *, maximum: int) -> tuple[int, int]:
    if page <= 0:
        raise ValueError("page must be positive")
    if page_size <= 0 or page_size > maximum:
        raise ValueError(f"page_size must be within 1..{maximum}")
    return (page - 1) * page_size, page_size


@dataclass(frozen=True, slots=True)
class ListThsCatalogQuery:
    repository: ThsSectorRepository

    def execute(
        self,
        *,
        tag: str | None = None,
        search: str | None = None,
        revision_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        if tag is not None and tag not in THS_TAGS:
            raise ValueError(f"unsupported THS tag: {tag}")
        offset, limit = _page(page, page_size, maximum=500)
        normalized_search = search.strip() if search and search.strip() else None
        revision = (
            self.repository.get_catalog_revision(revision_id)
            if revision_id is not None
            else self.repository.latest_catalog_revision()
        )
        if revision_id is not None and revision is None:
            raise LookupError(f"THS catalog revision not found: {revision_id}")
        if revision is None:
            return {
                "revision": None,
                "filters": {"tag": tag, "search": normalized_search},
                "items": [],
                "pagination": {"page": page, "pageSize": page_size, "total": 0},
            }
        relations = self.repository.list_catalog(
            tag=tag,
            search=normalized_search,
            revision_id=revision.revision_id,
            offset=offset,
            limit=limit,
        )
        total = self.repository.count_catalog(
            tag=tag,
            search=normalized_search,
            revision_id=revision.revision_id,
        )
        return {
            "revision": {
                "id": revision.revision_id,
                "source": revision.source,
                "capabilityRevision": revision.capability_revision,
                "providerTimestamp": revision.provider_timestamp.isoformat(),
                "fetchedAt": revision.fetched_at.isoformat(),
                "checksum": revision.checksum,
                "rowCount": revision.row_count,
                "tagCounts": dict(revision.tag_counts),
            },
            "filters": {"tag": tag, "search": normalized_search},
            "items": [
                {
                    "tag": item.tag,
                    "thscode": item.thscode,
                    "name": item.name,
                    "revisionId": item.revision_id,
                }
                for item in relations
            ],
            "pagination": {"page": page, "pageSize": page_size, "total": total},
        }


@dataclass(frozen=True, slots=True)
class GetThsSectorBarsQuery:
    repository: ThsSectorRepository

    def execute(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        page_size: int = 250,
    ) -> dict[str, Any]:
        code = normalize_thscode(thscode)
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if start_date is not None and end_date is not None:
            if (end_date - start_date).days > 366 * 5 + 2:
                raise ValueError("K-line query range cannot exceed five years")
        offset, limit = _page(page, page_size, maximum=1000)
        rows = self.repository.list_sector_bars(
            code,
            start_date=start_date,
            end_date=end_date,
            offset=offset,
            limit=limit,
        )
        total = self.repository.count_sector_bars(
            code, start_date=start_date, end_date=end_date
        )
        coverage = GetThsSectorBarCoverageQuery(self.repository).execute(
            code, start_date=start_date, end_date=end_date
        )
        return {
            "thscode": code,
            "requestedRange": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None,
            },
            "coverage": coverage,
            "items": [
                {
                    "tradingDate": item.trading_date.isoformat(),
                    "open": item.open,
                    "high": item.high,
                    "low": item.low,
                    "close": item.close,
                    "volume": item.volume,
                    "turnover": item.turnover,
                    "source": item.source,
                    "sourceRevision": item.source_revision,
                    "checksum": item.checksum,
                    "fetchedAt": item.fetched_at.isoformat(),
                    "quality": item.quality,
                    "warnings": list(item.warnings),
                }
                for item in rows
            ],
            "pagination": {"page": page, "pageSize": page_size, "total": total},
        }


@dataclass(frozen=True, slots=True)
class GetThsSectorBarCoverageQuery:
    repository: ThsSectorRepository

    def execute(
        self,
        thscode: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        code = normalize_thscode(thscode)
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if start_date is not None and end_date is not None:
            if (end_date - start_date).days > 366 * 5 + 2:
                raise ValueError("K-line query range cannot exceed five years")
        stored = dict(
            self.repository.sector_bar_coverage(
                code, start_date=start_date, end_date=end_date
            )
        )
        first_date = stored.get("first_date")
        last_date = stored.get("last_date")
        gaps: list[dict[str, str]] = []
        if start_date is not None and (first_date is None or first_date > start_date):
            gap_end = end_date if first_date is None else first_date - timedelta(days=1)
            gaps.append(
                {"kind": "leading", "start": start_date.isoformat(), "end": gap_end.isoformat()}
            )
        if end_date is not None and (last_date is None or last_date < end_date):
            gap_start = start_date if last_date is None else last_date + timedelta(days=1)
            candidate = {"kind": "trailing", "start": gap_start.isoformat(), "end": end_date.isoformat()}
            if not gaps or candidate["start"] > gaps[-1]["end"]:
                gaps.append(candidate)
        return {
            "firstDate": first_date.isoformat() if first_date else None,
            "lastDate": last_date.isoformat() if last_date else None,
            "storedRows": int(stored.get("stored_rows", 0)),
            "okRows": int(stored.get("ok_rows", 0)),
            "gaps": gaps,
            "complete": not gaps and bool(stored.get("stored_rows", 0)),
        }


@dataclass(frozen=True, slots=True)
class GetThsOperationProgressQuery:
    repository: ThsSectorRepository

    def execute(self, run_id: str) -> dict[str, Any]:
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id is required")
        operation = self.repository.get_operation(normalized_run_id)
        if operation is None:
            raise LookupError(f"THS operation not found: {normalized_run_id}")
        checkpoints = (
            self.repository.list_backfill_checkpoints(normalized_run_id)
            if operation.kind == "turnover-backfill"
            else ()
        )
        status_counts: dict[str, int] = {}
        for item in checkpoints:
            status_counts[item.status] = status_counts.get(item.status, 0) + 1
        return {
            "runId": operation.run_id,
            "operation": operation.kind,
            "status": operation.status,
            "capabilityRevision": operation.capability_revision,
            "request": dict(operation.request_metadata),
            "progress": dict(operation.progress),
            "result": dict(operation.result),
            "requestBudget": operation.request_budget,
            "requestsUsed": operation.requests_used,
            "warning": operation.warning,
            "requestedAt": operation.requested_at.isoformat(),
            "startedAt": operation.started_at.isoformat() if operation.started_at else None,
            "completedAt": operation.completed_at.isoformat() if operation.completed_at else None,
            "summary": {
                "totalItems": operation.total_items,
                "completedItems": operation.completed_items,
                "failedItems": operation.failed_items,
                "conflictItems": operation.conflict_items,
                "totalCheckpoints": len(checkpoints),
                "statusCounts": status_counts,
                "rowsWritten": sum(item.rows_written for item in checkpoints),
                "rowsSkipped": sum(item.rows_skipped for item in checkpoints),
                "conflicts": sum(item.conflicts for item in checkpoints),
            },
            "checkpoints": [
                {
                    "thscode": item.thscode,
                    "windowStart": item.window_start.isoformat(),
                    "windowEnd": item.window_end.isoformat(),
                    "status": item.status,
                    "sourceRevision": item.source_revision,
                    "rowsWritten": item.rows_written,
                    "rowsSkipped": item.rows_skipped,
                    "conflicts": item.conflicts,
                    "warning": item.warning,
                }
                for item in checkpoints
            ],
        }


__all__ = [
    "GetThsOperationProgressQuery",
    "GetThsSectorBarCoverageQuery",
    "GetThsSectorBarsQuery",
    "ListThsCatalogQuery",
]
