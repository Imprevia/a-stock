from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from src.market_environment.domain.policies.limit_facts import (
    INVALID_MEMBERSHIP_REASONS,
    LIMIT_FACT_SCHEMA_VERSION,
    LimitSecurityFactRecord,
)
from src.market_environment.interfaces.http.schemas.models import PROMOTION_RULE_VERSION
from src.market_environment.limit_ecosystem import _detail_row
from src.market_environment.snapshot_store import LIMIT_DETAIL_CHECKSUM_KEY, SnapshotIntegrityError
from src.market_environment.infrastructure.persistence.postgres import v2_market_data as postgres_reads

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
        self.statements = []

    def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(statement)
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
        self.statements.append(statement)
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
    assert params == {
        "as_of": AS_OF,
        "limit": 3,
        "membership_invalid_reasons": sorted(INVALID_MEMBERSHIP_REASONS),
    }
    assert connection.statements[0]._bindparams["membership_invalid_reasons"].expanding is True


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


def test_postgres_breadth_history_omits_absent_optional_date_predicates() -> None:
    connection = EmptyHistoryConnection()
    adapter = BoundedAdapter(connection)

    page = adapter.breadth_history(
        AS_OF,
        start_date=None,
        end_date=None,
        after=None,
        limit=20,
    )

    statement, params = connection.calls[0]
    normalized = " ".join(statement.split()).upper()
    assert page is not None
    assert "START_DATE" not in normalized
    assert "END_DATE" not in normalized
    assert "AFTER_DATE" not in normalized
    assert params == {"dataset": "breadth", "as_of": AS_OF, "limit": 21}


def test_postgres_breadth_history_binds_only_present_typed_dates() -> None:
    connection = EmptyHistoryConnection()
    adapter = BoundedAdapter(connection)
    start = date(2026, 9, 1)
    end = date(2026, 9, 22)

    adapter.breadth_history(
        AS_OF,
        start_date=start,
        end_date=end,
        after=("2026-09-10",),
        limit=20,
    )

    statement, params = connection.calls[0]
    normalized = " ".join(statement.split()).upper()
    assert "AS_OF>=:START_DATE" in normalized
    assert "AS_OF<=:END_DATE" in normalized
    assert "AS_OF>:AFTER_DATE" in normalized
    assert params["start_date"] == start
    assert params["end_date"] == end
    assert params["after_date"] == date(2026, 9, 10)
    assert all(value is not None for key, value in params.items() if key.endswith("_date"))
    for name in ("as_of", "start_date", "end_date", "after_date"):
        assert connection.statements[0]._bindparams[name].type.python_type is date


def test_postgres_limits_history_uses_same_present_date_predicate_contract() -> None:
    connection = EmptyHistoryConnection()
    adapter = BoundedAdapter(connection)

    adapter.limits_history(
        AS_OF,
        start_date=date(2026, 9, 1),
        end_date=None,
        after=None,
        limit=20,
    )

    statement, params = connection.calls[0]
    normalized = " ".join(statement.split()).upper()
    assert "SNAPSHOT.AS_OF>=:START_DATE" in normalized
    assert "END_DATE" not in normalized
    assert "AFTER_DATE" not in normalized
    assert params["start_date"] == date(2026, 9, 1)
    assert "end_date" not in params and "after_date" not in params
    assert connection.statements[0]._bindparams["as_of"].type.python_type is date
    assert connection.statements[0]._bindparams["start_date"].type.python_type is date


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
    assert "session.is_session=1" in limits_source
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


@pytest.mark.parametrize("pool_type", ["limit_up", "limit_down", "failed_limit_up"])
def test_pool_membership_predicates_precede_pagination_and_bind_domain_reasons(pool_type) -> None:
    connection = RecordingConnection()
    BoundedAdapter(connection).limits_pool(AS_OF, pool_type, after=None, limit=2)

    sql, params = connection.calls[0]
    normalized = " ".join(sql.split())
    for identity in ("security_id", "code", "exchange"):
        assert f"current.{identity} <> ''" in normalized
    assert "current.actual_as_of=current.as_of" in normalized
    assert "current.invalid_reason IS NULL OR current.invalid_reason NOT IN" in normalized
    assert normalized.index("current.invalid_reason NOT IN") < normalized.index("ORDER BY")
    assert normalized.index("ORDER BY") < normalized.index("LIMIT")
    assert params["membership_invalid_reasons"] == sorted(INVALID_MEMBERSHIP_REASONS)
    assert not any(reason in sql for reason in INVALID_MEMBERSHIP_REASONS)
    assert "eligible" not in normalized


@pytest.mark.parametrize("eligible,row_quality", [(False, None), (True, None), (False, "degraded")])
@pytest.mark.parametrize("warnings", [[], ["missing-board"], ["provider-warning"]])
def test_postgres_limit_row_matches_detail_quality_and_warning_projection(eligible, row_quality, warnings) -> None:
    fact = LimitSecurityFactRecord(
        as_of=AS_OF, actual_as_of=AS_OF, security_id="SSE:600001",
        code="600001", exchange="SSE", pool_type="limit_up",
        eligible=eligible, invalid_reason="missing-board", row_quality=row_quality,
        row_warnings=tuple(warnings), streak_days=None,
    )
    row = {**fact.__dict__, "row_warnings_json": warnings}
    projected = PostgresV2MarketDataReadAdapter._limit_row(row)
    expected = _detail_row(fact)
    assert projected == {key: expected[key] for key in projected}
    assert projected["warnings"].count("missing-board") == 1
    assert projected["streakDays"] is None


@pytest.fixture
def promotion_evidence(monkeypatch):
    previous = date(2026, 9, 22)
    calls = []
    manifests = {
        day: {
            "as_of": day, "actual_as_of": day, "membership_complete": True,
            "rule_version": PROMOTION_RULE_VERSION,
            "schema_version": LIMIT_FACT_SCHEMA_VERSION,
            "dataset_checksum": day.isoformat(), "warnings": (),
        }
        for day in (previous, AS_OF)
    }
    snapshots = {
        day: SimpleNamespace(payload={"quality": {LIMIT_DETAIL_CHECKSUM_KEY: day.isoformat()}})
        for day in (previous, AS_OF)
    }
    sessions = {
        day: SimpleNamespace(
            as_of=day, actual_as_of=day, is_session=True,
            previous_as_of=previous if day == AS_OF else None,
        )
        for day in (previous, AS_OF)
    }

    class Details:
        def __init__(self, connection): pass
        def get_manifest(self, day):
            calls.append(("manifest", day))
            return manifests.get(day)
        def get_facts(self, day):
            raise AssertionError("promoted reads must never materialize all facts")

    class Snapshots:
        def __init__(self, connection): pass
        def get(self, identity):
            assert identity.dataset == "limits"
            calls.append(("snapshot", identity.as_of))
            return snapshots.get(identity.as_of)

    class Sessions:
        def __init__(self, connection): pass
        def get_session(self, day):
            calls.append(("session", day))
            return sessions.get(day)

    monkeypatch.setattr(postgres_reads, "PostgresLimitDetailRepository", Details)
    monkeypatch.setattr(postgres_reads, "PostgresSnapshotRepository", Snapshots)
    monkeypatch.setattr(postgres_reads, "PostgresTradingSessionRepository", Sessions)
    return SimpleNamespace(
        previous=previous, calls=calls, manifests=manifests, snapshots=snapshots, sessions=sessions,
    )


def test_promoted_uses_proven_adjacent_dates_and_identical_member_predicates(promotion_evidence) -> None:
    connection = RecordingConnection()
    page = BoundedAdapter(connection).limits_pool(AS_OF, "promoted", after=None, limit=2)

    assert page is not None and len(page.resource.data) == 2
    sql, params = connection.calls[0]
    assert params["previous_as_of"] == promotion_evidence.previous
    for alias in ("current", "previous"):
        for identity in ("security_id", "code", "exchange"):
            assert f"{alias}.{identity} <> ''" in sql
        assert f"{alias}.actual_as_of={alias}.as_of" in sql
        assert f"{alias}.invalid_reason NOT IN" in sql
        assert f"{alias}.closed_limit_up = 1" in sql
    assert "eligible" not in sql
    assert promotion_evidence.calls == [
        ("session", AS_OF), ("session", promotion_evidence.previous),
        ("manifest", promotion_evidence.previous), ("manifest", AS_OF),
        ("snapshot", promotion_evidence.previous), ("snapshot", AS_OF),
    ]


@pytest.mark.parametrize("day_key", ["previous", "current"])
@pytest.mark.parametrize("problem", ["missing-manifest", "incomplete", "unknown-completeness", "missing-date", "unsupported-rule", "missing-snapshot", "missing-binding"])
def test_promoted_missing_prerequisites_stop_before_fact_query(promotion_evidence, day_key, problem) -> None:
    day = promotion_evidence.previous if day_key == "previous" else AS_OF
    manifest = promotion_evidence.manifests[day]
    if problem == "missing-manifest":
        del promotion_evidence.manifests[day]
    elif problem in {"incomplete", "unknown-completeness"}:
        manifest["membership_complete"] = False if problem == "incomplete" else None
    elif problem == "missing-date":
        manifest["actual_as_of"] = None
    elif problem == "unsupported-rule":
        manifest["rule_version"] = "unsupported"
    elif problem == "missing-snapshot":
        del promotion_evidence.snapshots[day]
    else:
        promotion_evidence.snapshots[day].payload["quality"].clear()
    connection = RecordingConnection()
    page = BoundedAdapter(connection).limits_pool(AS_OF, "promoted", after=None, limit=2)
    assert page.resource.quality["status"] == "insufficient"
    assert page.resource.data == [] and page.next_sort_key is None
    assert connection.calls == []


@pytest.mark.parametrize("problem", ["missing-current", "missing-previous", "missing-previous-pointer", "missing-actual", "invalid-order", "non-session"])
def test_promoted_requires_proven_session_without_older_date_search(promotion_evidence, problem) -> None:
    current = promotion_evidence.sessions[AS_OF]
    if problem == "missing-current":
        del promotion_evidence.sessions[AS_OF]
    elif problem == "missing-previous":
        del promotion_evidence.sessions[promotion_evidence.previous]
    elif problem == "missing-previous-pointer":
        current.previous_as_of = None
    elif problem == "missing-actual":
        current.actual_as_of = None
    elif problem == "invalid-order":
        current.previous_as_of = AS_OF
    else:
        current.is_session = False
    connection = RecordingConnection()
    page = BoundedAdapter(connection).limits_pool(AS_OF, "promoted", after=None, limit=2)
    assert page.resource.quality["status"] == "insufficient"
    assert page.resource.data == []
    assert connection.calls == []
    assert all(kind == "session" for kind, _ in promotion_evidence.calls)


@pytest.mark.parametrize("day_key", ["previous", "current"])
@pytest.mark.parametrize("problem", ["binding", "manifest-key-date", "manifest-actual-date", "manifest-schema", "session-date"])
def test_promoted_stored_integrity_errors_are_not_downgraded(promotion_evidence, day_key, problem) -> None:
    day = promotion_evidence.previous if day_key == "previous" else AS_OF
    manifest = promotion_evidence.manifests[day]
    wrong_date = date(2026, 9, 21)
    if problem == "binding":
        manifest["dataset_checksum"] = "corrupt"
    elif problem == "manifest-key-date":
        manifest["as_of"] = wrong_date
    elif problem == "manifest-actual-date":
        manifest["actual_as_of"] = wrong_date
    elif problem == "manifest-schema":
        manifest["schema_version"] = -1
    else:
        promotion_evidence.sessions[day].actual_as_of = wrong_date
    connection = RecordingConnection()
    with pytest.raises(SnapshotIntegrityError):
        BoundedAdapter(connection).limits_pool(AS_OF, "promoted", after=None, limit=2)
    assert connection.calls == []


def test_promoted_complete_empty_previous_membership_preserves_zero_denominator_quality(promotion_evidence) -> None:
    class EmptyPrevious(RecordingConnection):
        def execute(self, statement, params):
            self.calls.append((str(statement), params))
            return _Mappings([])

    class EmptyMetadata(BoundedAdapter):
        def _limits_pool_metadata(self, as_of, pool_type):
            metadata = self._metadata("market-limits-pool")
            return replace(metadata, quality={
                "status": "insufficient", "reason": "zero-denominator", "observations": 0,
            })

    connection = EmptyPrevious()
    page = EmptyMetadata(connection).limits_pool(AS_OF, "promoted", after=None, limit=2)
    assert page.resource.data == [] and page.next_sort_key is None
    assert page.resource.quality == {
        "status": "insufficient", "reason": "zero-denominator", "observations": 0,
    }
    assert len(connection.calls) == 1


@pytest.mark.parametrize("unavailable", [False, True])
def test_promoted_retained_quality_is_preserved_even_when_prerequisites_are_missing(promotion_evidence, unavailable) -> None:
    class Retained(BoundedAdapter):
        def _limits_pool_metadata(self, as_of, pool_type):
            return replace(self._metadata("market-limits-pool"), quality={
                "status": "failed-retained", "warnings": ["retained same-day snapshot"],
                "refreshWarning": "retained same-day snapshot",
            })

    if unavailable:
        del promotion_evidence.manifests[promotion_evidence.previous]
    page = Retained(RecordingConnection()).limits_pool(AS_OF, "promoted", after=None, limit=2)
    assert page.resource.quality["status"] == "failed-retained"
    assert page.resource.quality["warnings"] == ["retained same-day snapshot"]
    assert page.resource.quality["refreshWarning"] == "retained same-day snapshot"


@pytest.mark.parametrize("snapshot_status,pool_status,expected", [
    ("degraded", "degraded", "degraded"),
    ("failed-retained", "ok", "failed-retained"),
    ("ok", "insufficient", "insufficient"),
])
def test_postgres_pool_metadata_preserves_pool_and_retained_quality(snapshot_status, pool_status, expected) -> None:
    class MetadataConnection:
        def execute(self, statement, params):
            assert params == {"as_of": AS_OF}
            return _Mappings([{
                "generated_at": "2026-09-23T16:00:00+08:00",
                "source": "fixture", "status": snapshot_status, "observations": 9,
                "warnings_json": ["snapshot-warning"],
                "fetched_at": "2026-09-23T16:00:00+08:00",
                "refresh_warning": "retained same-day snapshot",
                "pool_quality_json": {"status": pool_status, "warnings": ["pool-warning"]},
            }])

    adapter = PostgresV2MarketDataReadAdapter(MetadataConnection())
    adapter.aggregates = SimpleNamespace(revision=lambda day: SimpleNamespace(value="private-r1"))
    metadata = adapter._limits_pool_metadata(AS_OF, "limit_up")
    assert metadata.quality["status"] == expected
    assert metadata.quality["observations"] == 9
    assert metadata.quality["warnings"] == [
        "pool-warning", "snapshot-warning", "retained same-day snapshot",
    ]
    assert metadata.quality["refreshWarning"] == "retained same-day snapshot"
