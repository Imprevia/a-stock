from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.market_environment.application.queries.ths_sector import (
    GetThsOperationProgressQuery,
    GetThsSectorBarCoverageQuery,
    GetThsSectorBarsQuery,
    ListThsCatalogQuery,
)
from src.market_environment.domain.models.ths_sector import (
    ThsBackfillCheckpoint,
    ThsCatalogRelation,
    ThsCatalogRevision,
    ThsOperation,
    ThsSectorBar,
)


NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


class LocalThsRepository:
    def __init__(self) -> None:
        self.provider_calls = 0
        self.revision = ThsCatalogRevision(
            revision_id="catalog-r1",
            capability_revision="catalog-cap-r1",
            provider_timestamp=NOW,
            fetched_at=NOW,
            tag_counts={"industry": 2, "cn_concept": 1, "region": 1, "tszs": 1},
            checksum="catalog-checksum",
        )
        self.relations = (
            ThsCatalogRelation("catalog-r1", "industry", "885001.TI", "行业甲"),
            ThsCatalogRelation("catalog-r1", "industry", "885002.TI", "行业乙"),
            ThsCatalogRelation("catalog-r1", "cn_concept", "885001.TI", "概念甲"),
            ThsCatalogRelation("catalog-r1", "region", "885003.TI", "区域甲"),
            ThsCatalogRelation("catalog-r1", "tszs", "885004.TI", "特色甲"),
        )
        self.bars = (
            self._bar(date(2026, 10, 9), 10.0),
            self._bar(date(2026, 10, 10), 11.0),
        )
        self.operation = ThsOperation(
            run_id="run-1",
            kind="turnover-backfill",
            status="partial",
            capability_revision="history-cap-r1",
            request_checksum="request-checksum",
            request_metadata={"codes": ["885001.TI"], "start": "2026-10-08"},
            progress={"currentCode": "885001.TI"},
            result={"storedRows": 2},
            total_items=2,
            completed_items=1,
            failed_items=1,
            conflict_items=0,
            request_budget=2,
            requests_used=2,
            requested_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            warning="one window failed",
        )
        self.checkpoints = (
            ThsBackfillCheckpoint(
                "run-1", "885001.TI", date(2026, 10, 8), date(2026, 10, 9),
                "success", "history-r1", rows_written=2,
            ),
            ThsBackfillCheckpoint(
                "run-1", "885001.TI", date(2026, 10, 10), date(2026, 10, 10),
                "failed", "history-r1", warning="provider unavailable",
            ),
        )

    @staticmethod
    def _bar(as_of: date, close: float) -> ThsSectorBar:
        return ThsSectorBar(
            thscode="885001.TI",
            trading_date=as_of,
            open=close - 0.2,
            high=close + 0.3,
            low=close - 0.4,
            close=close,
            volume=100.0,
            turnover=200.0,
            source="fuyao",
            source_revision="history-r1",
            checksum=f"bar-{as_of.isoformat()}",
            fetched_at=NOW,
        )

    def latest_catalog_revision(self):
        return self.revision

    def get_catalog_revision(self, revision_id):
        return self.revision if revision_id == self.revision.revision_id else None

    def list_catalog(self, *, tag=None, search=None, revision_id=None, offset=0, limit=100):
        rows = [item for item in self.relations if tag is None or item.tag == tag]
        if search:
            term = search.lower()
            rows = [item for item in rows if term in item.thscode.lower() or term in item.name.lower()]
        return tuple(rows[offset : offset + limit])

    def count_catalog(self, *, tag=None, search=None, revision_id=None):
        return len(self.list_catalog(tag=tag, search=search, revision_id=revision_id, limit=1000))

    def list_sector_bars(self, thscode, *, start_date=None, end_date=None, offset=0, limit=500):
        rows = [
            item for item in self.bars
            if (start_date is None or item.trading_date >= start_date)
            and (end_date is None or item.trading_date <= end_date)
        ]
        return tuple(rows[offset : offset + limit])

    def count_sector_bars(self, thscode, *, start_date=None, end_date=None):
        return len(self.list_sector_bars(thscode, start_date=start_date, end_date=end_date))

    def sector_bar_coverage(self, thscode, *, start_date=None, end_date=None):
        rows = self.list_sector_bars(thscode, start_date=start_date, end_date=end_date)
        return {
            "first_date": rows[0].trading_date if rows else None,
            "last_date": rows[-1].trading_date if rows else None,
            "stored_rows": len(rows),
            "ok_rows": sum(item.quality == "ok" for item in rows),
        }

    def get_operation(self, run_id):
        return self.operation if run_id == self.operation.run_id else None

    def list_backfill_checkpoints(self, run_id):
        return self.checkpoints if run_id == self.operation.run_id else ()


def test_catalog_query_filters_revision_search_and_pagination_without_provider() -> None:
    repository = LocalThsRepository()
    query = ListThsCatalogQuery(repository)

    result = query.execute(tag="industry", search="行业", revision_id="catalog-r1", page=2, page_size=1)

    assert result["revision"]["id"] == "catalog-r1"
    assert result["items"] == [
        {"tag": "industry", "thscode": "885002.TI", "name": "行业乙", "revisionId": "catalog-r1"}
    ]
    assert result["pagination"] == {"page": 2, "pageSize": 1, "total": 2}
    assert repository.provider_calls == 0
    with pytest.raises(LookupError, match="not found"):
        query.execute(revision_id="missing")


def test_one_code_bars_query_reports_local_coverage_gaps_and_pagination() -> None:
    repository = LocalThsRepository()
    result = GetThsSectorBarsQuery(repository).execute(
        "885001.ti",
        start_date=date(2026, 10, 8),
        end_date=date(2026, 10, 11),
        page=1,
        page_size=1,
    )

    assert result["thscode"] == "885001.TI"
    assert result["pagination"] == {"page": 1, "pageSize": 1, "total": 2}
    assert result["coverage"] == {
        "firstDate": "2026-10-09",
        "lastDate": "2026-10-10",
        "storedRows": 2,
        "okRows": 2,
        "gaps": [
            {"kind": "leading", "start": "2026-10-08", "end": "2026-10-08"},
            {"kind": "trailing", "start": "2026-10-11", "end": "2026-10-11"},
        ],
        "complete": False,
    }
    assert len(result["items"]) == 1
    assert repository.provider_calls == 0
    with pytest.raises(ValueError, match="five years"):
        GetThsSectorBarsQuery(repository).execute(
            "885001.TI", start_date=date(2020, 1, 1), end_date=date(2026, 10, 1)
        )


def test_coverage_query_is_available_without_loading_bar_pages() -> None:
    repository = LocalThsRepository()
    result = GetThsSectorBarCoverageQuery(repository).execute(
        "885001.TI", start_date=date(2026, 10, 9), end_date=date(2026, 10, 10)
    )

    assert result["complete"] is True
    assert result["storedRows"] == 2
    assert result["gaps"] == []
    assert repository.provider_calls == 0


def test_operation_progress_is_local_and_supports_backfill_checkpoints() -> None:
    repository = LocalThsRepository()
    result = GetThsOperationProgressQuery(repository).execute("run-1")

    assert result["operation"] == "turnover-backfill"
    assert result["request"] == {"codes": ["885001.TI"], "start": "2026-10-08"}
    assert result["summary"] == {
        "totalItems": 2,
        "completedItems": 1,
        "failedItems": 1,
        "conflictItems": 0,
        "totalCheckpoints": 2,
        "statusCounts": {"success": 1, "failed": 1},
        "rowsWritten": 2,
        "rowsSkipped": 0,
        "conflicts": 0,
    }
    assert len(result["checkpoints"]) == 2
    assert repository.provider_calls == 0
    with pytest.raises(LookupError, match="not found"):
        GetThsOperationProgressQuery(repository).execute("missing")


def test_operation_rejects_sensitive_request_metadata() -> None:
    safe = LocalThsRepository().operation
    assert replace(safe, request_metadata={"localPath": "/data/import.parquet"})
    with pytest.raises(ValueError, match="sensitive key"):
        replace(safe, request_metadata={"api_key": "secret"})
    with pytest.raises(ValueError, match="cannot contain a URL"):
        replace(safe, request_metadata={"source": "https://signed.example/file"})
