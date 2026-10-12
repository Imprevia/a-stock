from __future__ import annotations

import importlib.util
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.market_environment.application.ports import SectorContinuityRepository
from src.market_environment.domain.models import (
    IndustryIdentity,
    Lineage,
    MembershipInterval,
    SecurityDailyFact,
    TaxonomyRevision,
)
from src.market_environment.infrastructure.persistence.postgres import (
    MINIMUM_SCHEMA_VERSION,
    REQUIRED_RUNTIME_TABLES,
    PostgresSectorContinuityRepository,
)


AS_OF = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)
MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/0004_sector_continuity.py"


@pytest.fixture
def connection():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    active = engine.connect()
    statements = (
        """CREATE TABLE sector_taxonomy_revisions (
            taxonomy_version TEXT, taxonomy_family TEXT, taxonomy_level INTEGER,
            source_revision TEXT, effective_from DATE, effective_to DATE,
            checksum TEXT, imported_at TEXT,
            PRIMARY KEY(taxonomy_version, source_revision, checksum))""",
        """CREATE TABLE sector_industries (
            industry_id TEXT, display_name TEXT, taxonomy_version TEXT,
            source_revision TEXT, taxonomy_checksum TEXT,
            PRIMARY KEY(industry_id,taxonomy_version,source_revision,taxonomy_checksum))""",
        """CREATE TABLE sector_membership_intervals (
            security_id TEXT, industry_id TEXT, taxonomy_version TEXT,
            valid_from DATE, valid_to DATE, source_revision TEXT, evidence_checksum TEXT,
            PRIMARY KEY(security_id,industry_id,taxonomy_version,valid_from,source_revision,evidence_checksum))""",
        """CREATE TABLE sector_security_daily_facts (
            security_id TEXT, as_of DATE, market TEXT, original_close REAL,
            original_open REAL, original_high REAL, original_low REAL,
            previous_close REAL, adjusted_close REAL, adjusted_previous_close REAL,
            amount REAL, volume INTEGER, change_pct REAL, eligible INTEGER,
            exclusion_reason TEXT, requested_as_of DATE, actual_as_of DATE,
            source TEXT, source_revision TEXT, schema_version INTEGER, checksum TEXT,
            data_version TEXT, classification_version TEXT, membership_version TEXT,
            universe_version TEXT, adjustment_version TEXT, benchmark_version TEXT,
            calculation_version TEXT, fetched_at TEXT, warnings_json TEXT,
            quality_status TEXT, observation_count INTEGER,
            field_availability_json TEXT, evidence_references_json TEXT,
            PRIMARY KEY(security_id,as_of,source_revision,checksum))""",
        """CREATE TABLE sector_benchmark_facts (
            benchmark_id TEXT, as_of DATE, return_value REAL, eligible_count INTEGER,
            excluded_count INTEGER, session_dates_json TEXT, requested_as_of DATE,
            actual_as_of DATE, source TEXT, source_revision TEXT, schema_version INTEGER,
            checksum TEXT, data_version TEXT, classification_version TEXT,
            membership_version TEXT, universe_version TEXT, adjustment_version TEXT,
            benchmark_version TEXT, calculation_version TEXT, fetched_at TEXT,
            warnings_json TEXT, quality_status TEXT, observation_count INTEGER,
            field_availability_json TEXT, evidence_references_json TEXT,
            PRIMARY KEY(benchmark_id,as_of,source_revision,checksum))""",
        """CREATE TABLE sector_industry_aggregates (
            industry_id TEXT, as_of DATE, member_count INTEGER,
            eligible_return_count INTEGER, eligible_amount_count INTEGER,
            eligible_ma20_count INTEGER, industry_return REAL, original_amount REAL,
            breadth_ratio REAL, advance_count INTEGER, decline_count INTEGER,
            flat_count INTEGER, limit_up_count INTEGER, limit_down_count INTEGER,
            excluded_reasons_json TEXT, input_checksum TEXT, requested_as_of DATE, actual_as_of DATE,
            source TEXT, source_revision TEXT, schema_version INTEGER, checksum TEXT,
            data_version TEXT, classification_version TEXT, membership_version TEXT,
            universe_version TEXT, adjustment_version TEXT, benchmark_version TEXT,
            calculation_version TEXT, fetched_at TEXT, warnings_json TEXT,
            quality_status TEXT, observation_count INTEGER,
            field_availability_json TEXT, evidence_references_json TEXT,
            PRIMARY KEY(industry_id,as_of,calculation_version,source_revision,checksum))""",
        """CREATE TABLE sector_continuity_results (
            as_of DATE, status TEXT, confidence TEXT, coverage REAL, result_json TEXT,
            requested_as_of DATE, actual_as_of DATE, source TEXT, source_revision TEXT,
            schema_version INTEGER, checksum TEXT, data_version TEXT,
            classification_version TEXT, membership_version TEXT, universe_version TEXT,
            adjustment_version TEXT, benchmark_version TEXT, calculation_version TEXT,
            fetched_at TEXT, warnings_json TEXT, quality_status TEXT,
            observation_count INTEGER, field_availability_json TEXT,
            evidence_references_json TEXT,
            PRIMARY KEY(as_of,calculation_version,source_revision,checksum))""",
        """CREATE TABLE sector_backfill_runs (
            run_id TEXT PRIMARY KEY, as_of DATE, session_dates_json TEXT,
            source_revisions_json TEXT, calculation_version TEXT, status TEXT,
            requested_at TEXT, completed_at TEXT, warnings_json TEXT)""",
        """CREATE TABLE sector_backfill_attempts (
            run_id TEXT, as_of DATE, status TEXT, requested_at TEXT, completed_at TEXT,
            retry_eligible INTEGER, warning TEXT, compatible_result_checksum TEXT,
            PRIMARY KEY(run_id,as_of))""",
    )
    for statement in statements:
        active.exec_driver_sql(statement)
    active.commit()
    try:
        yield active
    finally:
        active.close()
        engine.dispose()


def _taxonomy(checksum: str = "taxonomy-a") -> TaxonomyRevision:
    return TaxonomyRevision(
        "sw-v1", "shenwan", 1, "operator-v1",
        date(2026, 1, 1), None, checksum, NOW,
    )


def _lineage(checksum: str, adjustment_version: str | None = None) -> Lineage:
    return Lineage(
        requested_as_of=AS_OF, actual_as_of=AS_OF, source="fixture",
        source_revision="facts-v1", schema_version=1, checksum=checksum,
        data_version="data-v1", universe_version="ordinary-a-share-v1",
        adjustment_version=adjustment_version, fetched_at=NOW,
        quality_status="partial", observation_count=1,
        field_availability={"amount": True, "adjustedClose": adjustment_version is not None},
    )


def _fact(checksum: str, adjustment_version: str | None = None) -> SecurityDailyFact:
    return SecurityDailyFact(
        security_id="sh.600000", as_of=AS_OF, market="sh",
        original_close=10, previous_close=9, adjusted_close=10 if adjustment_version else None,
        adjusted_previous_close=9 if adjustment_version else None,
        amount=1000, volume=100, change_pct=1.0, eligible=True,
        lineage=_lineage(checksum, adjustment_version),
        original_open=9.5, original_high=10.2, original_low=9.4,
    )


def test_repository_is_port_and_taxonomy_is_idempotent_but_conflict_is_explicit(connection):
    repository = PostgresSectorContinuityRepository(connection)
    assert isinstance(repository, SectorContinuityRepository)
    revision = _taxonomy()
    repository.put_taxonomy(revision)
    repository.put_taxonomy(revision)
    repository.put_industry(IndustryIdentity("801010", "农林牧渔", revision))
    assert connection.execute(text("SELECT COUNT(*) FROM sector_taxonomy_revisions")).scalar_one() == 1
    assert repository.get_taxonomy_revision("sw-v1", "operator-v1") == revision
    assert repository.list_industries("sw-v1") == (
        IndustryIdentity("801010", "农林牧渔", revision),
    )
    with pytest.raises(ValueError, match="conflicting taxonomy"):
        repository.put_taxonomy(_taxonomy("taxonomy-b"))


def test_repository_membership_exact_date_and_overlap_conflict(connection):
    repository = PostgresSectorContinuityRepository(connection)
    old = MembershipInterval(
        "sh.600000", "A", "sw-v1", date(2026, 1, 1), AS_OF,
        "operator-v1", "membership-a",
    )
    current = MembershipInterval(
        "sh.600000", "B", "sw-v1", AS_OF, None,
        "operator-v1", "membership-b",
    )
    repository.put_membership(old)
    repository.put_membership(current)
    assert [item.industry_id for item in repository.list_memberships(AS_OF)] == ["B"]
    with pytest.raises(ValueError, match="overlapping membership"):
        repository.put_membership(
            MembershipInterval(
                "sh.600000", "C", "sw-v1", AS_OF, None,
                "operator-v1", "membership-c",
            )
        )


def test_security_fact_versions_coexist_but_same_revision_checksum_conflicts(connection):
    repository = PostgresSectorContinuityRepository(connection)
    raw = _fact("raw-a")
    adjusted = _fact("adjusted-a", "qfq-v1")
    repository.put_security_fact(raw)
    repository.put_security_fact(raw)
    repository.put_security_fact(adjusted)
    assert len(repository.list_security_facts(AS_OF)) == 2
    assert {item.amount for item in repository.list_security_facts(AS_OF)} == {1000}
    with pytest.raises(ValueError, match="conflicting security"):
        repository.put_security_fact(_fact("adjusted-b", "qfq-v1"))


def test_repository_write_participates_in_caller_transaction_rollback(connection):
    transaction = connection.begin()
    PostgresSectorContinuityRepository(connection).put_security_fact(_fact("raw-a"))
    transaction.rollback()
    assert connection.execute(text("SELECT COUNT(*) FROM sector_security_daily_facts")).scalar_one() == 0


class RecordingOperations:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, statement: str):
        self.statements.append(statement)


def test_0004_migration_is_additive_idempotent_after_runtime_schema_advances():
    spec = importlib.util.spec_from_file_location("test_0004_sector_continuity", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = RecordingOperations()
    migration.op = operations
    migration.upgrade()
    migration.upgrade()

    assert migration.down_revision == "0003_provider_capability_reports"
    assert MINIMUM_SCHEMA_VERSION == 8
    for table in (
        "sector_taxonomy_revisions", "sector_industries", "sector_membership_intervals",
        "sector_security_daily_facts", "sector_benchmark_facts",
        "sector_industry_aggregates", "sector_continuity_results",
        "sector_backfill_runs", "sector_backfill_attempts",
    ):
        assert table in REQUIRED_RUNTIME_TABLES
        assert any(f"create table if not exists {table}" in " ".join(item.lower().split()) for item in operations.statements)
    destructive = re.compile(r"\b(drop|delete|truncate|alter)\b", re.IGNORECASE)
    assert not any(destructive.search(item) for item in operations.statements)
    assert operations.statements[: len(migration.UPGRADE_STATEMENTS)] == list(migration.UPGRADE_STATEMENTS)
