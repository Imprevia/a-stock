from __future__ import annotations

import inspect
from datetime import date

from src.market_environment.application.ports.v2_market_data import V2Resource
from src.market_environment.infrastructure.persistence.postgres.v2_market_data import (
    PostgresV2MarketDataReadAdapter,
)
from src.market_environment.infrastructure.v2_market_data_compat import (
    CompatibilityV2MarketDataReadAdapter,
)


AS_OF = date(2026, 9, 23)


class _Mappings:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class RecordingConnection:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "limit_security_facts current" in sql:
            return _Mappings(
                [
                    {
                        "security_id": f"SSE:60000{index}",
                        "code": f"60000{index}",
                        "exchange": "SSE",
                        "name": f"row-{index}",
                        "pool_type": "limit_up",
                        "row_warnings_json": "[]",
                    }
                    for index in range(params["limit"])
                ]
            )
        if "ths_industry_rankings" in sql:
            return _Mappings(
                [
                    {
                        "tag": "industry",
                        "rank": index + 1,
                        "thscode": f"88500{index}.TI",
                        "display_name": f"sector-{index}",
                        "change_pct": 1.0,
                        "volume": 2.0,
                        "turnover": 3.0,
                        "catalog_revision_id": "catalog-r1",
                        "quality_status": "ok",
                        "warnings_json": "[]",
                    }
                    for index in range(params["limit"])
                ]
            )
        if "ths_backfill_checkpoints" in sql:
            return _Mappings(
                [
                    {
                        "thscode": f"88500{index}.TI",
                        "window_start": AS_OF,
                        "window_end": AS_OF,
                        "status": "success",
                        "source_revision": "history-r1",
                        "rows_written": 1,
                        "rows_skipped": 0,
                        "conflicts": 0,
                        "warning": None,
                    }
                    for index in range(params["limit"])
                ]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class EmptyHistoryConnection(RecordingConnection):
    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        return _Mappings([])


class BoundedAdapter(PostgresV2MarketDataReadAdapter):
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _metadata(dataset: str) -> V2Resource:
        return V2Resource(AS_OF, "2026-09-23T16:00:00+08:00", "private-r1", {"dataset": dataset, "status": "ok"}, {})

    def limits(self, as_of): return self._metadata("market-limits")
    def _chapter_resource(self, as_of, key, dataset): return self._metadata(dataset)
    def _list_metadata(self, as_of, *, snapshot_dataset, public_dataset): return self._metadata(public_dataset)
    def _limits_pool_metadata(self, as_of, pool_type): return self._metadata("market-limits-pool")
    def operation_summary(self, run_id): return self._metadata("ths-operation")


def test_postgres_variable_lists_bind_filter_order_and_limit_before_materializing() -> None:
    connection = RecordingConnection()
    adapter = BoundedAdapter(connection)

    pool = adapter.limits_pool(AS_OF, "limit_up", after=("SSE", "600001", "SSE:600001"), limit=2)
    rankings = adapter.sector_rankings(AS_OF, tag="industry", after=("industry", "1", "885001.TI"), limit=3)
    checkpoints = adapter.operation_checkpoints("run-1", after=("885001.TI", AS_OF.isoformat(), AS_OF.isoformat()), limit=4)

    assert len(pool.resource.data) == 2 and pool.next_sort_key is not None
    assert len(rankings.resource.data) == 3 and rankings.next_sort_key is not None
    assert len(checkpoints.resource.data) == 4 and checkpoints.next_sort_key is not None
    assert [params["limit"] for _, params in connection.calls] == [3, 4, 5]
    for sql, _params in connection.calls:
        normalized = " ".join(sql.split()).upper()
        assert " ORDER BY " in normalized
        assert " LIMIT " in normalized
    assert "CURRENT.AS_OF=:AS_OF" in " ".join(connection.calls[0][0].split()).upper()
    assert "(:TAG IS NULL OR TAG=:TAG)" in " ".join(connection.calls[1][0].split()).upper()
    assert "RUN_ID=:RUN_ID" in " ".join(connection.calls[2][0].split()).upper()


def test_postgres_limits_pool_omits_cursor_sql_and_null_binds_on_first_page() -> None:
    connection = RecordingConnection()
    adapter = BoundedAdapter(connection)

    page = adapter.limits_pool(AS_OF, "limit_up", after=None, limit=2)

    sql, params = connection.calls[0]
    normalized = " ".join(sql.split()).upper()
    assert len(page.resource.data) == 2 and page.next_sort_key is not None
    assert "AFTER_EXCHANGE" not in normalized
    assert "AFTER_CODE" not in normalized
    assert "AFTER_SECURITY_ID" not in normalized
    assert params == {"as_of": AS_OF, "limit": 3}


def test_postgres_limits_pool_binds_non_null_cursor_only_on_later_pages() -> None:
    connection = RecordingConnection()
    adapter = BoundedAdapter(connection)
    cursor = ("SSE", "600001", "SSE:600001")

    page = adapter.limits_pool(AS_OF, "limit_up", after=cursor, limit=2)

    sql, params = connection.calls[0]
    normalized = " ".join(sql.split()).upper()
    assert len(page.resource.data) == 2 and page.next_sort_key is not None
    assert "(CURRENT.EXCHANGE,CURRENT.CODE,CURRENT.SECURITY_ID)>" in normalized
    assert params["after_exchange"] == cursor[0]
    assert params["after_code"] == cursor[1]
    assert params["after_security_id"] == cursor[2]
    assert all(value is not None for key, value in params.items() if key.startswith("after_"))


def test_postgres_index_history_casts_optional_dates_before_null_checks() -> None:
    connection = EmptyHistoryConnection()
    adapter = BoundedAdapter(connection)

    page = adapter.index_history(
        AS_OF,
        "sh000001",
        start_date=None,
        end_date=None,
        after=None,
        limit=20,
    )

    sql, params = connection.calls[0]
    normalized = " ".join(sql.split()).upper()
    assert page is not None
    assert "CAST(:START_DATE AS DATE) IS NULL" in normalized
    assert "CAST(:END_DATE AS DATE) IS NULL" in normalized
    assert "CAST(:AFTER_DATE AS DATE) IS NULL" in normalized
    assert params["start_date"] is None
    assert params["end_date"] is None
    assert params["after_date"] is None


def test_all_postgres_variable_list_paths_are_bounded_before_materialization() -> None:
    direct_sql_methods = (
        "index_history",
        "limits_pool",
        "sector_rankings",
        "sector_turnover",
        "sector_breadth",
        "active_direction",
        "events",
        "limits_history",
        "operation_checkpoints",
    )
    for name in direct_sql_methods:
        source = inspect.getsource(getattr(PostgresV2MarketDataReadAdapter, name))
        assert "LIMIT :limit" in source, name
        assert "limit + 1" in source, name
        assert "self._aggregate(" not in source, name

    history_source = inspect.getsource(PostgresV2MarketDataReadAdapter._snapshot_history)
    assert "ORDER BY as_of" in history_source
    assert "LIMIT :limit" in history_source
    assert "limit + 1" in history_source
    breadth_source = inspect.getsource(PostgresV2MarketDataReadAdapter.breadth_history)
    assert "self._snapshot_history(" in breadth_source
    assert "self._aggregate(" not in breadth_source
    limits_source = inspect.getsource(PostgresV2MarketDataReadAdapter.limits_history)
    assert "JOIN trading_sessions" in limits_source
    assert "session.is_session=TRUE" in limits_source
    assert "self._aggregate(" not in limits_source


def test_compatibility_adapter_projects_isolated_bounded_fixture_resources() -> None:
    aggregate = {
        "asOf": AS_OF.isoformat(),
        "generatedAt": "2026-09-23T16:00:00+08:00",
        "indices": [
            {"code": "sh000001", "close": 100.0, "history": [{"date": "2026-09-22"}]}
        ],
        "summary": {"synchronization": "fixture"},
        "chapter01": {
            "status": "partial",
            "limits": {
                "quality": {"status": "ok"},
                "limitUpCount": 2,
                "history": {"points": [{"asOf": "2026-09-22"}]},
                "securityDetails": {
                    "limitUp": {
                        "rows": [
                            {"securityId": "SSE:600002", "exchange": "SSE", "code": "600002"},
                            {"securityId": "SSE:600001", "exchange": "SSE", "code": "600001"},
                        ]
                    }
                },
            },
        },
    }
    adapter = CompatibilityV2MarketDataReadAdapter({AS_OF: aggregate})

    indices = adapter.indices(AS_OF)
    summary = adapter.limits(AS_OF)
    pool = adapter.limits_pool(AS_OF, "limit_up", after=None, limit=1)

    assert "history" not in indices.data[0]
    assert "securityDetails" not in summary.data
    assert "history" not in summary.data
    assert [item["securityId"] for item in pool.resource.data] == ["SSE:600001"]
    assert pool.next_sort_key == ("SSE", "600001", "SSE:600001")


def test_compatibility_pool_preserves_empty_partial_and_failed_retained_quality() -> None:
    def pool_quality(*, parent_status: str, group_status: str, warning: str | None = None):
        parent_quality = {"status": parent_status, "warnings": []}
        if warning:
            parent_quality["refreshWarning"] = warning
        aggregate = {
            "asOf": AS_OF.isoformat(),
            "generatedAt": "2026-09-23T16:00:00+08:00",
            "chapter01": {
                "limits": {
                    "quality": parent_quality,
                    "securityDetails": {
                        "limitUp": {
                            "total": 0,
                            "rows": [],
                            "quality": {"status": group_status, "warnings": []},
                        }
                    },
                }
            },
        }
        page = CompatibilityV2MarketDataReadAdapter({AS_OF: aggregate}).limits_pool(
            AS_OF,
            "limit_up",
            after=None,
            limit=20,
        )
        assert page is not None
        return page.resource.quality

    assert pool_quality(parent_status="ok", group_status="insufficient")["status"] == "insufficient"
    assert pool_quality(parent_status="ok", group_status="partial")["status"] == "partial"
    retained = pool_quality(
        parent_status="failed-retained",
        group_status="ok",
        warning="保留同日旧数据",
    )
    assert retained["status"] == "failed-retained"
    assert retained["warnings"] == ["保留同日旧数据"]


def test_compatibility_empty_history_first_page_is_insufficient() -> None:
    aggregate = {
        "asOf": AS_OF.isoformat(),
        "generatedAt": "2026-09-23T16:00:00+08:00",
        "indices": [{"code": "sh000001", "history": [], "dataQuality": {"status": "ok"}}],
        "chapter01": {
            "breadth": {"quality": {"status": "ok"}, "history": {"points": []}},
            "limits": {"quality": {"status": "ok"}, "history": {"points": []}},
        },
    }
    adapter = CompatibilityV2MarketDataReadAdapter({AS_OF: aggregate})

    pages = (
        adapter.index_history(AS_OF, "sh000001", start_date=None, end_date=None, after=None, limit=60),
        adapter.breadth_history(AS_OF, start_date=None, end_date=None, after=None, limit=60),
        adapter.limits_history(AS_OF, start_date=None, end_date=None, after=None, limit=60),
    )

    assert all(page is not None for page in pages)
    assert [page.resource.quality["status"] for page in pages if page is not None] == [
        "insufficient",
        "insufficient",
        "insufficient",
    ]
