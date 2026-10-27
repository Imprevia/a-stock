"""Real PostgreSQL pool predicates and HTTP contracts over synthetic evidence only.

Only MARKET_ENVIRONMENT_TEST_DATABASE_URL opts into database access. Every table
is temporary, every transaction rolls back, and pg_temp is the sole search path.
The pure build_pool_evidence helper also supports offline consumer tests.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from src.market_environment.application.queries import V2MarketDataQueries
from src.market_environment.domain.policies.limit_facts import (
    LimitSecurityFactRecord,
    normalize_limit_pools,
)
from src.market_environment.infrastructure.persistence.postgres.limit_repository import (
    PostgresLimitDetailRepository,
)
from src.market_environment.infrastructure.persistence.postgres.repositories import (
    PostgresTradingSessionRepository,
)
from src.market_environment.infrastructure.persistence.postgres.v2_market_data import (
    PostgresV2MarketDataReadAdapter,
)
from src.market_environment.infrastructure.v2_market_data_compat import (
    CompatibilityV2MarketDataReadAdapter,
)
from src.market_environment.limit_ecosystem import build_limit_ecosystem
from src.market_environment.postgres_schema import SCHEMA_STATEMENTS
from src.market_environment.schemas import PROMOTION_RULE_VERSION
from src.market_environment.snapshot_store import (
    LIMIT_DETAIL_CHECKSUM_KEY,
    SnapshotRecord,
    TradingSessionRecord,
    payload_checksum,
)
from tests.market_environment_api_support import build_test_app


PREVIOUS = date(2026, 10, 14)
CURRENT = date(2026, 10, 15)
FETCHED_AT = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
POOL_KEYS = {
    "limit_up": "limitUp",
    "limit_down": "limitDown",
    "failed_limit_up": "failedLimitUp",
    "promoted": "promoted",
}
INVALID_MEMBERSHIP_REASONS = (
    "malformed-row", "malformed-identity", "ambiguous-identity",
    "identity-code-mismatch", "identity-exchange-mismatch",
    "invalid-provider-row-date", "provider-row-date-mismatch",
    "missing-actual-session-date", "provider-date-mismatch",
    "duplicate-security", "conflicting-pool-membership",
)
_TEMP_TABLES = frozenset({
    "snapshot_entries", "trading_sessions", "limit_security_datasets",
    "limit_security_facts", "materialized_market_environment",
    "materialization_component_versions",
})


class PoolEvidenceStore:
    """Minimal local store consumed by the real legacy ecosystem calculation."""

    def __init__(self):
        self.manifests = {}
        self.facts_by_date = {}
        self.snapshots = {}
        self.sessions = {}

    def get_limit_security_dataset(self, as_of):
        return self.manifests.get(as_of)

    def get_limit_security_facts(self, as_of):
        return self.facts_by_date.get(as_of, ())

    def get(self, dataset, as_of):
        return self.snapshots.get((dataset, as_of))

    def get_trading_session(self, as_of):
        return self.sessions.get(as_of)


@dataclass
class PoolEvidence:
    store: PoolEvidenceStore
    aggregates: dict
    normalizations: dict
    current: date = CURRENT
    previous: date = PREVIOUS

    @property
    def facts_by_date(self):
        return self.store.facts_by_date


def build_pool_evidence(*, missing_streak=False, empty_previous=False):
    """Return two exact-session synthetic aggregates and their bound evidence.

    Previous high/middle/low samples each contain four members. Current outcomes
    are respectively limit-up, failed-limit-up, limit-down, and absent in each
    tier. Two previous failed samples repair to limit-up / remain limit-down.
    Optional enrichment is missing throughout; missing_streak adds one visible
    previous limit-up member whose streak remains null.
    """
    def row(code, streak=None):
        result = {"code": code, "exchange": "SSE", "name": f"合成{code}",
                  "source": "synthetic-pools", "row_quality": "degraded",
                  "row_warnings": ["synthetic enrichment unavailable"]}
        if streak is not None:
            result["streak_days"] = streak
        return result

    previous_pools = {"limit_up": [], "failed_limit_up": [], "limit_down": []}
    current_pools = {"limit_up": [], "failed_limit_up": [], "limit_down": []}
    for tier, streak in enumerate((4, 2, 1), start=1):
        for outcome in range(4):
            code = f"600{tier}{outcome:02d}"
            previous_pools["limit_up"].append(row(code, streak))
            if outcome < 3:
                pool = ("limit_up", "failed_limit_up", "limit_down")[outcome]
                current_pools[pool].append(row(code, streak + 1 if outcome == 0 else None))
    previous_pools["failed_limit_up"] = [row("601001"), row("601002")]
    previous_pools["limit_down"] = [row("601003")]
    current_pools["limit_up"].append(row("601001", 1))
    current_pools["limit_down"].append(row("601002"))
    if missing_streak:
        previous_pools["limit_up"].append(row("609999"))
        current_pools["limit_up"].append(row("609999"))
    if empty_previous:
        previous_pools = {pool: [] for pool in previous_pools}

    store = PoolEvidenceStore()
    normalizations = {}
    for as_of, previous_as_of, pools in (
        (PREVIOUS, None, previous_pools), (CURRENT, PREVIOUS, current_pools),
    ):
        store.sessions[as_of] = TradingSessionRecord(
            as_of, previous_as_of, True, "synthetic-sessions",
            actual_as_of=as_of, fetched_at=FETCHED_AT,
        ).normalized()
        pool_quality = {
            pool: {"status": "degraded", "source": "synthetic-pools",
                   "observations": len(rows), "membershipComplete": True,
                   "warnings": ["synthetic enrichment unavailable"]}
            for pool, rows in pools.items()
        }
        normalized = normalize_limit_pools(
            pools, as_of=as_of, actual_as_of=as_of, source="synthetic-pools",
            source_revision="synthetic-pools-r1", rule_version=PROMOTION_RULE_VERSION,
            membership_complete=True, streak_complete=not missing_streak,
            pool_quality=pool_quality, fetched_at=FETCHED_AT,
        )
        normalizations[as_of] = normalized
        store.facts_by_date[as_of] = normalized.rows
        store.manifests[as_of] = {
            "as_of": as_of, "actual_as_of": as_of, "source": normalized.source,
            "source_revision": normalized.source_revision,
            "rule_version": normalized.rule_version, "schema_version": 2,
            "complete": normalized.complete, "membership_complete": True,
            "streak_complete": not missing_streak, "pool_quality": pool_quality,
            "excluded": sum(not fact.eligible for fact in normalized.rows),
            "warnings": normalized.warnings, "dataset_checksum": normalized.dataset_checksum,
            "fetched_at": FETCHED_AT,
        }
        payload = {
            "asOf": as_of.isoformat(), "limitUpCount": len(pools["limit_up"]),
            "limitDownCount": len(pools["limit_down"]),
            "failedLimitUpCount": len(pools["failed_limit_up"]),
            "failedLimitUpRatio": round(len(pools["failed_limit_up"]) / max(1, len(pools["limit_up"]) + len(pools["failed_limit_up"])), 4),
            "maxStreak": max((fact.streak_days or 0 for fact in normalized.rows), default=0) or None,
            "quality": {"status": "degraded", "source": "synthetic-pools",
                        "asOf": as_of.isoformat(), "observations": len(normalized.rows),
                        "warnings": ["synthetic enrichment unavailable"],
                        LIMIT_DETAIL_CHECKSUM_KEY: normalized.dataset_checksum},
        }
        store.snapshots[("limits", as_of)] = SnapshotRecord(
            "limits", as_of, payload, normalized.source, "degraded",
            len(normalized.rows), ("synthetic enrichment unavailable",), FETCHED_AT, True,
        )
    aggregates = {
        as_of: {
            "asOf": as_of.isoformat(), "generatedAt": FETCHED_AT.isoformat(),
            "chapter01": {"limits": build_limit_ecosystem(store, as_of, store.get("limits", as_of).payload)},
        }
        for as_of in (PREVIOUS, CURRENT)
    }
    return PoolEvidence(store, aggregates, normalizations)


def pool_http_client(adapter):
    """Build a real v2 router client with only local query dependencies."""
    return TestClient(build_test_app(
        v2_queries=V2MarketDataQueries(adapter), effective_date=CURRENT,
    ))


@pytest.fixture(autouse=True)
def forbid_pool_provider_access(monkeypatch):
    from requests import Session
    from src.market_environment.infrastructure.providers.runtime import CollectorProviderRuntime

    calls = []

    def forbidden(*args, **kwargs):
        calls.append("provider/network")
        raise AssertionError("pool GET must not construct or call a provider")

    monkeypatch.setattr(CollectorProviderRuntime, "__init__", forbidden)
    for name in vars(CollectorProviderRuntime):
        if name.startswith("fetch_"):
            monkeypatch.setattr(CollectorProviderRuntime, name, forbidden)
    monkeypatch.setattr(Session, "request", forbidden)
    yield calls
    assert calls == []


@pytest.fixture
def postgres_pool_connection():
    url = os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set MARKET_ENVIRONMENT_TEST_DATABASE_URL to an isolated PostgreSQL database; real pool SQL not validated")
    assert make_url(url).get_backend_name() == "postgresql", "pool integration tests require PostgreSQL"
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL search_path TO pg_temp"))
                created = set()
                for statement in SCHEMA_STATEMENTS:
                    match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement)
                    if match and match[1] in _TEMP_TABLES:
                        sql = statement.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE", 1)
                        connection.execute(text(sql + " ON COMMIT DROP"))
                        created.add(match[1])
                assert created == _TEMP_TABLES
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def seed_postgres_pool_evidence(connection, evidence):
    """Write synthetic fixture setup only; callers start GET monitoring afterwards."""
    details = PostgresLimitDetailRepository(connection)
    sessions = PostgresTradingSessionRepository(connection)
    for as_of in (evidence.previous, evidence.current):
        sessions.put_session(evidence.store.sessions[as_of])
        details.put_limit_detail(as_of, evidence.store.manifests[as_of], evidence.facts_by_date[as_of])
        snapshot = evidence.store.get("limits", as_of)
        connection.execute(text("""
            INSERT INTO snapshot_entries(dataset,as_of,payload_json,source,status,
                observations,warnings_json,fetched_at,settled,schema_version,checksum,refresh_warning)
            VALUES ('limits',:as_of,CAST(:payload AS JSONB),:source,:status,
                :observations,CAST(:warnings AS JSONB),:fetched_at,1,1,:checksum,:refresh_warning)
        """), {"as_of": as_of, "payload": json.dumps(snapshot.payload),
               "source": snapshot.source, "status": snapshot.status,
               "observations": snapshot.observations, "warnings": json.dumps(snapshot.warnings),
               "fetched_at": FETCHED_AT, "checksum": payload_checksum(snapshot.payload),
               "refresh_warning": snapshot.refresh_warning})
        aggregate = evidence.aggregates[as_of]
        connection.execute(text("""
            INSERT INTO materialized_market_environment(as_of,payload_json,generated_at,checksum)
            VALUES (:as_of,CAST(:payload AS JSONB),:generated_at,:checksum)
        """), {"as_of": as_of, "payload": json.dumps(aggregate),
               "generated_at": FETCHED_AT, "checksum": payload_checksum(aggregate)})
        for kind in ("snapshot", "trading_session", "limit_dataset", "limit_facts"):
            connection.execute(text("""
                INSERT INTO materialization_component_versions(component_kind,dataset,as_of,revision)
                VALUES (:kind,:dataset,:as_of,1)
            """), {"kind": kind, "dataset": "limits" if kind == "snapshot" else "", "as_of": as_of})
    return PostgresV2MarketDataReadAdapter(connection)


@contextmanager
def pool_reads_only(connection, monkeypatch):
    """Observe real SQL, reject writes/full fact materialization during GET reads."""
    statements = []

    def observe(_conn, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))
        assert re.match(r"\s*(SELECT|WITH)\b", statement, re.I), statement
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|COPY)\b", statement, re.I), statement

    def forbid_full_facts(*args, **kwargs):
        raise AssertionError("bounded pool GET must not load all facts")

    with monkeypatch.context() as scoped:
        scoped.setattr(PostgresLimitDetailRepository, "get_facts", forbid_full_facts)
        event.listen(connection, "before_cursor_execute", observe)
        try:
            yield statements
        finally:
            event.remove(connection, "before_cursor_execute", observe)


def read_pool_pages(adapter, pool_type, *, as_of=CURRENT, limit=2):
    rows, pages, after = [], [], None
    for _ in range(100):
        page = adapter.limits_pool(as_of, pool_type, after=after, limit=limit)
        assert page is not None
        items = list(page.resource.data)
        assert len(items) <= limit
        pages.append(page)
        rows.extend(items)
        if page.next_sort_key is None:
            keys = [(row["exchange"], row["code"], row["securityId"]) for row in rows]
            assert keys == sorted(keys)
            assert len(keys) == len(set(keys))
            return rows, pages
        assert len(items) == limit, "filtering after LIMIT prematurely shortened a page"
        assert page.next_sort_key != after
        after = page.next_sort_key
    pytest.fail("pool cursor did not terminate")


def _matrix_facts(pool_type):
    facts = []
    reasons = (None, *INVALID_MEMBERSHIP_REASONS,
               "missing-board", "missing-st-status", "missing-listing-window",
               "missing-limit-regime", "missing-close", "missing-close-limit-status",
               "st-regime-identity-mismatch", "ipo-window", "st-security", "not-v1-pool")
    for index, reason in enumerate(reasons):
        code = f"608{index * 2:03d}"
        facts.append(LimitSecurityFactRecord(
            CURRENT, f"SSE:{code}", pool_type, code, "SSE", actual_as_of=CURRENT,
            invalid_reason=reason, closed_limit_up=pool_type == "limit_up",
            row_warnings=(reason,) if index % 2 and reason else (),
            row_quality=None, streak_days=None if index % 2 else 2,
            source="synthetic-matrix", fetched_at=FETCHED_AT,
        ).normalized())
        if reason in INVALID_MEMBERSHIP_REASONS:
            code = f"608{index * 2 + 1:03d}"
            facts.append(replace(facts[-1], security_id=f"SSE:{code}", code=code,
                                 invalid_reason="missing-board", row_checksum="").normalized())
    for index, patch in enumerate((
        {"security_id": ""}, {"code": ""}, {"exchange": ""},
        {"actual_as_of": None}, {"actual_as_of": PREVIOUS},
    )):
        code = f"609{index:03d}"
        fields = {"security_id": f"SSE:{code}", "code": code, **patch}
        facts.append(replace(facts[0], **fields, row_checksum="").normalized())
    return tuple(facts)


@pytest.mark.integration
@pytest.mark.parametrize("pool_type", ("limit_up", "limit_down", "failed_limit_up"))
def test_real_postgres_three_pool_membership_matches_domain_before_paging(
    postgres_pool_connection, monkeypatch, pool_type,
):
    connection = postgres_pool_connection
    adapter = seed_postgres_pool_evidence(connection, build_pool_evidence())
    connection.execute(text("DELETE FROM limit_security_facts WHERE as_of=:as_of"), {"as_of": CURRENT})
    facts = _matrix_facts(pool_type)
    repository = PostgresLimitDetailRepository(connection)
    for fact in facts:
        repository._upsert_fact(fact)
    expected = sorted((fact.exchange, fact.code, fact.security_id) for fact in facts if fact.membership_valid)
    assert all(not fact.membership_valid for fact in facts if fact.invalid_reason in INVALID_MEMBERSHIP_REASONS)
    assert any(fact.membership_valid and fact.invalid_reason is None for fact in facts)
    with pool_reads_only(connection, monkeypatch) as statements:
        rows, pages = read_pool_pages(adapter, pool_type)
    assert [(row["exchange"], row["code"], row["securityId"]) for row in rows] == expected
    assert len(pages) > 2
    for row in rows:
        fact = next(item for item in facts if item.security_id == row["securityId"])
        expected_warnings = list(fact.row_warnings)
        if fact.invalid_reason and fact.invalid_reason not in expected_warnings:
            expected_warnings.append(fact.invalid_reason)
        assert row["warnings"] == expected_warnings
        assert row["rowQuality"] == "insufficient"
        assert row["streakDays"] == fact.streak_days
    pool_queries = [(sql, params) for sql, params in statements if "SELECT current.*" in sql]
    assert len(pool_queries) == len(pages)
    assert all("LIMIT" in sql and params["limit"] == 3 for sql, params in pool_queries)


@pytest.mark.integration
@pytest.mark.parametrize("missing_streak", (False, True))
def test_real_postgres_legal_evidence_matches_legacy_and_compatibility(
    postgres_pool_connection, monkeypatch, missing_streak,
):
    evidence = build_pool_evidence(missing_streak=missing_streak)
    adapter = seed_postgres_pool_evidence(postgres_pool_connection, evidence)
    compat = CompatibilityV2MarketDataReadAdapter(evidence.aggregates)
    with pool_reads_only(postgres_pool_connection, monkeypatch):
        for pool_type, group in POOL_KEYS.items():
            rows, _ = read_pool_pages(adapter, pool_type)
            legacy_rows = evidence.aggregates[CURRENT]["chapter01"]["limits"]["securityDetails"][group]["rows"]
            compatible_rows, _ = read_pool_pages(compat, pool_type)
            assert [row["securityId"] for row in rows] == [row["securityId"] for row in legacy_rows]
            assert compatible_rows == legacy_rows
            for actual, expected in zip(rows, legacy_rows, strict=True):
                assert actual == {key: value for key, value in expected.items() if key in actual}
    assert all(not fact.eligible for fact in evidence.facts_by_date[CURRENT])
    if missing_streak:
        rows, _ = read_pool_pages(adapter, "limit_up", as_of=PREVIOUS)
        assert next(row for row in rows if row["code"] == "609999")["streakDays"] is None


@pytest.mark.integration
def test_real_postgres_promoted_pages_equal_same_revision_aggregate_numerator(
    postgres_pool_connection, monkeypatch,
):
    evidence = build_pool_evidence()
    adapter = seed_postgres_pool_evidence(postgres_pool_connection, evidence)
    with pool_reads_only(postgres_pool_connection, monkeypatch):
        rows, pages = read_pool_pages(adapter, "promoted", limit=1)
        summary = adapter.limits(CURRENT)
    assert summary is not None
    assert len(rows) == summary.data["todayPromoted"] == 3
    assert summary.data["yesterdayLimitUpEligible"] == 12
    assert summary.data["promotionRatio"] == 0.25
    assert {page.resource.component_revision for page in pages} == {summary.component_revision}
    assert all(row["warnings"] for row in rows)


@pytest.mark.integration
@pytest.mark.parametrize("as_of", (PREVIOUS, CURRENT))
@pytest.mark.parametrize("case", (*INVALID_MEMBERSHIP_REASONS, "empty-security-id", "empty-code", "empty-exchange", "wrong-date", "missing-date", "not-closed"))
def test_real_postgres_invalid_dated_row_cannot_establish_promotion(
    postgres_pool_connection, monkeypatch, as_of, case,
):
    connection = postgres_pool_connection
    evidence = build_pool_evidence()
    adapter = seed_postgres_pool_evidence(connection, evidence)
    field, value = {
        "empty-security-id": ("security_id", ""),
        "empty-code": ("code", ""),
        "empty-exchange": ("exchange", ""),
        "wrong-date": ("actual_as_of", date(2026, 10, 13)),
        "missing-date": ("actual_as_of", None),
        "not-closed": ("closed_limit_up", 0),
    }.get(case, ("invalid_reason", case))
    connection.execute(text(f"UPDATE limit_security_facts SET {field}=:value WHERE as_of=:as_of AND security_id='SSE:600100'"),
                       {"value": value, "as_of": as_of})
    with pool_reads_only(connection, monkeypatch):
        rows, _ = read_pool_pages(adapter, "promoted", limit=1)
    assert {row["securityId"] for row in rows} == {"SSE:600200", "SSE:600300"}


@pytest.mark.integration
@pytest.mark.parametrize("as_of", (PREVIOUS, CURRENT))
@pytest.mark.parametrize("case", ("missing-manifest", "incomplete", "unknown-completeness", "unsupported-rule", "missing-actual-date", "missing-snapshot", "unbound-snapshot", "missing-session"))
def test_real_postgres_promoted_requires_both_adjacent_session_prerequisites(
    postgres_pool_connection, monkeypatch, as_of, case,
):
    connection = postgres_pool_connection
    adapter = seed_postgres_pool_evidence(connection, build_pool_evidence())
    if case in {"missing-manifest", "missing-snapshot", "missing-session"}:
        table = {"missing-manifest": "limit_security_datasets", "missing-snapshot": "snapshot_entries", "missing-session": "trading_sessions"}[case]
        connection.execute(text(f"DELETE FROM {table} WHERE as_of=:as_of"), {"as_of": as_of})
    elif case == "unbound-snapshot":
        _replace_snapshot_payload(connection, as_of, lambda payload: payload["quality"].pop(LIMIT_DETAIL_CHECKSUM_KEY))
    else:
        column, value = {
            "incomplete": ("membership_complete", 0),
            "unknown-completeness": ("membership_complete", None),
            "unsupported-rule": ("rule_version", "unsupported-fixture-rule"),
            "missing-actual-date": ("actual_as_of", None),
        }[case]
        connection.execute(text(f"UPDATE limit_security_datasets SET {column}=:value WHERE as_of=:as_of"), {"value": value, "as_of": as_of})
    with pool_reads_only(connection, monkeypatch):
        rows, pages = read_pool_pages(adapter, "promoted")
    assert rows == []
    assert pages[0].resource.quality["status"] in {"missing", "insufficient"}


@pytest.mark.integration
@pytest.mark.parametrize("case", (
    "missing-pointer", "future-pointer", "unavailable-pointer",
    "current-not-session", "previous-not-session", "missing-current-date", "missing-previous-date",
))
def test_real_postgres_promoted_does_not_guess_previous_trading_session(
    postgres_pool_connection, monkeypatch, case,
):
    connection = postgres_pool_connection
    evidence = build_pool_evidence()
    adapter = seed_postgres_pool_evidence(connection, evidence)
    target = PREVIOUS if case in {"previous-not-session", "missing-previous-date"} else CURRENT
    patch = {
        "missing-pointer": {"previous_as_of": None},
        "future-pointer": {"previous_as_of": CURRENT},
        "unavailable-pointer": {"previous_as_of": date(2026, 10, 13)},
        "current-not-session": {"is_session": False},
        "previous-not-session": {"is_session": False},
        "missing-current-date": {"actual_as_of": None},
        "missing-previous-date": {"actual_as_of": None},
    }[case]
    session = replace(evidence.store.sessions[target], **patch, checksum="")
    PostgresTradingSessionRepository(connection).put_session(session)
    with pool_reads_only(connection, monkeypatch):
        rows, pages = read_pool_pages(adapter, "promoted")
    assert rows == []
    assert pages[0].resource.quality["status"] == "insufficient"
    assert pages[0].resource.quality["reason"]


@pytest.mark.integration
@pytest.mark.parametrize("pool_type", ("limit_up", "limit_down", "failed_limit_up"))
def test_real_postgres_complete_empty_pools_keep_their_stored_quality(
    postgres_pool_connection, monkeypatch, pool_type,
):
    evidence = build_pool_evidence(empty_previous=True)
    adapter = seed_postgres_pool_evidence(postgres_pool_connection, evidence)
    with pool_reads_only(postgres_pool_connection, monkeypatch):
        rows, pages = read_pool_pages(adapter, pool_type, as_of=PREVIOUS)
    assert rows == []
    assert len(pages) == 1
    assert pages[0].resource.as_of == PREVIOUS
    assert pages[0].resource.quality["status"] == "degraded"
    assert pages[0].resource.quality["observations"] == 0


@pytest.mark.integration
def test_real_postgres_complete_empty_previous_membership_preserves_zero_denominator(
    postgres_pool_connection, monkeypatch,
):
    adapter = seed_postgres_pool_evidence(postgres_pool_connection, build_pool_evidence(empty_previous=True))
    with pool_reads_only(postgres_pool_connection, monkeypatch):
        rows, pages = read_pool_pages(adapter, "promoted")
        summary = adapter.limits(CURRENT)
    assert rows == []
    assert summary.data["todayPromoted"] == summary.data["yesterdayLimitUpEligible"] == 0
    assert summary.data["promotionRatio"] is None
    assert pages[0].resource.quality["status"] == "insufficient"
    assert pages[0].resource.quality["reason"] == "zero-denominator"


def _replace_snapshot_payload(connection, as_of, mutate):
    payload = connection.execute(text("SELECT payload_json FROM snapshot_entries WHERE dataset='limits' AND as_of=:as_of"), {"as_of": as_of}).scalar_one()
    mutate(payload)
    connection.execute(text("UPDATE snapshot_entries SET payload_json=CAST(:payload AS JSONB),checksum=:checksum WHERE dataset='limits' AND as_of=:as_of"),
                       {"as_of": as_of, "payload": json.dumps(payload), "checksum": payload_checksum(payload)})


@pytest.mark.integration
@pytest.mark.parametrize("as_of", (PREVIOUS, CURRENT))
@pytest.mark.parametrize("case", ("snapshot-checksum", "detail-binding", "snapshot-date", "session-checksum", "manifest-date"))
def test_real_postgres_http_stored_integrity_errors_remain_stable_and_read_only(
    postgres_pool_connection, monkeypatch, as_of, case,
):
    connection = postgres_pool_connection
    adapter = seed_postgres_pool_evidence(connection, build_pool_evidence())
    if case == "snapshot-checksum":
        connection.execute(text("UPDATE snapshot_entries SET checksum='corrupt' WHERE as_of=:as_of"), {"as_of": as_of})
    elif case == "detail-binding":
        _replace_snapshot_payload(connection, as_of, lambda payload: payload["quality"].update({LIMIT_DETAIL_CHECKSUM_KEY: "different-detail-checksum"}))
    elif case == "snapshot-date":
        _replace_snapshot_payload(connection, as_of, lambda payload: payload.update({"asOf": "2026-10-13"}))
    elif case == "session-checksum":
        connection.execute(text("UPDATE trading_sessions SET checksum='corrupt' WHERE as_of=:as_of"), {"as_of": as_of})
    else:
        connection.execute(text("UPDATE limit_security_datasets SET actual_as_of='2026-10-13' WHERE as_of=:as_of"), {"as_of": as_of})
    client = pool_http_client(adapter)
    with pool_reads_only(connection, monkeypatch):
        response = client.get(f"/api/v2/market-environment/{CURRENT}/limits/pools/promoted")
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "snapshot_integrity_error"
    assert "corrupt" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize("revision_day", (PREVIOUS, CURRENT))
def test_real_postgres_http_pool_retained_dates_revision_cursor_and_conflicts(
    postgres_pool_connection, monkeypatch, forbid_pool_provider_access, revision_day,
):
    connection = postgres_pool_connection
    evidence = build_pool_evidence()
    adapter = seed_postgres_pool_evidence(connection, evidence)
    connection.execute(text("UPDATE snapshot_entries SET status='failed-retained',refresh_warning='synthetic refresh failed; retained exact date' WHERE dataset='limits' AND as_of=:as_of"), {"as_of": CURRENT})
    client = pool_http_client(adapter)
    path = f"/api/v2/market-environment/{CURRENT}/limits/pools/limit_up"
    with pool_reads_only(connection, monkeypatch) as statements:
        first = client.get(path, params={"limit": 2})
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["asOf"] == CURRENT.isoformat()
        assert body["quality"]["actualDate"] == CURRENT.isoformat()
        assert body["quality"]["status"] == "failed-retained"
        assert "synthetic refresh failed; retained exact date" in body["quality"]["warnings"]
        assert body["quality"]["observations"] != body["pagination"]["returned"]
        assert body["pagination"]["returned"] == 2
        cursor, revision = body["pagination"]["nextCursor"], body["snapshotRevision"]
        assert cursor
        second = client.get(path, params={"limit": 2, "cursor": cursor, "revision": revision})
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["snapshotRevision"] == revision
        ids = [row["securityId"] for response_body in (body, second_body) for row in response_body["data"]["items"]]
        assert len(ids) == len(set(ids)) == 4
        assert second_body["pagination"]["nextCursor"] is None
        summary = client.get(f"/api/v2/market-environment/{CURRENT}/limits", params={"revision": revision})
        assert summary.status_code == 200
        previous = client.get(f"/api/v2/market-environment/{PREVIOUS}/limits/pools/limit_up")
        assert previous.status_code == 200
        assert previous.json()["asOf"] == PREVIOUS.isoformat()
        assert previous.json()["quality"]["status"] == "degraded"
        missing = client.get("/api/v2/market-environment/2026-10-13/limits/pools/limit_up")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "resource_not_found"
        cross_pool = client.get(path.replace("limit_up", "limit_down"), params={"limit": 2, "cursor": cursor})
        assert cross_pool.status_code == 422
    connection.execute(text("UPDATE materialization_component_versions SET revision=revision+1 WHERE component_kind='limit_facts' AND as_of=:as_of"), {"as_of": revision_day})
    with pool_reads_only(connection, monkeypatch):
        for params in ({"revision": revision}, {"limit": 2, "cursor": cursor}, {"limit": 2, "cursor": cursor, "revision": revision}):
            stale = client.get(path, params=params)
            assert stale.status_code == 409, stale.text
            assert stale.json()["error"]["code"] == "snapshot_revision_conflict"
    assert any("FROM limit_security_facts current" in sql for sql, _ in statements)
    assert forbid_pool_provider_access == []
