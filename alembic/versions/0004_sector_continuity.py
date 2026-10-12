"""Add immutable point-in-time sector continuity facts and results.

This migration is deliberately additive.  Existing five-dataset tables are
not altered or rewritten; the new tables are keyed by source/calculation
revisions so re-imports are idempotent while a changed checksum remains
auditable as a separate evidence version.
"""

from alembic import op


revision = "0004_sector_continuity"
down_revision = "0003_provider_capability_reports"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sector_taxonomy_revisions (
        taxonomy_version TEXT NOT NULL,
        taxonomy_family TEXT NOT NULL,
        taxonomy_level INTEGER NOT NULL,
        source_revision TEXT NOT NULL,
        effective_from DATE NOT NULL,
        effective_to DATE,
        checksum TEXT NOT NULL,
        imported_at TIMESTAMPTZ,
        PRIMARY KEY (taxonomy_version, source_revision, checksum),
        CHECK (taxonomy_family = 'shenwan'),
        CHECK (taxonomy_level = 1),
        CHECK (effective_to IS NULL OR effective_to > effective_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_industries (
        industry_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        taxonomy_checksum TEXT NOT NULL,
        PRIMARY KEY (industry_id, taxonomy_version, source_revision, taxonomy_checksum),
        FOREIGN KEY (taxonomy_version, source_revision, taxonomy_checksum)
            REFERENCES sector_taxonomy_revisions(taxonomy_version, source_revision, checksum)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_membership_intervals (
        security_id TEXT NOT NULL,
        industry_id TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL,
        valid_from DATE NOT NULL,
        valid_to DATE,
        source_revision TEXT NOT NULL,
        evidence_checksum TEXT NOT NULL,
        PRIMARY KEY (security_id, industry_id, taxonomy_version, valid_from, source_revision, evidence_checksum),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_security_daily_facts (
        security_id TEXT NOT NULL,
        as_of DATE NOT NULL,
        market TEXT NOT NULL,
        original_close DOUBLE PRECISION,
        original_open DOUBLE PRECISION,
        original_high DOUBLE PRECISION,
        original_low DOUBLE PRECISION,
        previous_close DOUBLE PRECISION,
        adjusted_close DOUBLE PRECISION,
        adjusted_previous_close DOUBLE PRECISION,
        amount DOUBLE PRECISION,
        volume BIGINT,
        change_pct DOUBLE PRECISION,
        eligible INTEGER NOT NULL,
        exclusion_reason TEXT,
        requested_as_of DATE NOT NULL,
        actual_as_of DATE,
        source TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        checksum TEXT NOT NULL,
        data_version TEXT,
        classification_version TEXT,
        membership_version TEXT,
        universe_version TEXT,
        adjustment_version TEXT,
        benchmark_version TEXT,
        calculation_version TEXT,
        fetched_at TIMESTAMPTZ,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        quality_status TEXT NOT NULL,
        observation_count INTEGER NOT NULL DEFAULT 0,
        field_availability_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (security_id, as_of, source_revision, checksum),
        CHECK (market IN ('sh', 'sz', 'bj')),
        CHECK (eligible IN (0, 1)),
        CHECK (amount IS NULL OR amount >= 0),
        CHECK (volume IS NULL OR volume >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_benchmark_facts (
        benchmark_id TEXT NOT NULL,
        as_of DATE NOT NULL,
        return_value DOUBLE PRECISION,
        eligible_count INTEGER NOT NULL,
        excluded_count INTEGER NOT NULL,
        session_dates_json JSONB NOT NULL,
        requested_as_of DATE NOT NULL,
        actual_as_of DATE,
        source TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        checksum TEXT NOT NULL,
        data_version TEXT,
        classification_version TEXT,
        membership_version TEXT,
        universe_version TEXT,
        adjustment_version TEXT,
        benchmark_version TEXT,
        calculation_version TEXT,
        fetched_at TIMESTAMPTZ,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        quality_status TEXT NOT NULL,
        observation_count INTEGER NOT NULL DEFAULT 0,
        field_availability_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (benchmark_id, as_of, source_revision, checksum),
        CHECK (benchmark_id = 'ordinary-a-share-equal-weight-v1'),
        CHECK (eligible_count >= 0),
        CHECK (excluded_count >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_industry_aggregates (
        industry_id TEXT NOT NULL,
        as_of DATE NOT NULL,
        member_count INTEGER NOT NULL,
        eligible_return_count INTEGER NOT NULL,
        eligible_amount_count INTEGER NOT NULL,
        eligible_ma20_count INTEGER NOT NULL,
        industry_return DOUBLE PRECISION,
        original_amount DOUBLE PRECISION,
        breadth_ratio DOUBLE PRECISION,
        advance_count INTEGER,
        decline_count INTEGER,
        flat_count INTEGER,
        limit_up_count INTEGER,
        limit_down_count INTEGER,
        excluded_reasons_json JSONB NOT NULL,
        input_checksum TEXT NOT NULL,
        requested_as_of DATE NOT NULL,
        actual_as_of DATE,
        source TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        checksum TEXT NOT NULL,
        data_version TEXT,
        classification_version TEXT,
        membership_version TEXT,
        universe_version TEXT,
        adjustment_version TEXT,
        benchmark_version TEXT,
        calculation_version TEXT,
        fetched_at TIMESTAMPTZ,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        quality_status TEXT NOT NULL,
        observation_count INTEGER NOT NULL DEFAULT 0,
        field_availability_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (industry_id, as_of, calculation_version, source_revision, checksum),
        CHECK (member_count >= 0),
        CHECK (eligible_return_count >= 0),
        CHECK (eligible_amount_count >= 0),
        CHECK (eligible_ma20_count >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_continuity_results (
        as_of DATE NOT NULL,
        status TEXT NOT NULL,
        confidence TEXT NOT NULL,
        coverage DOUBLE PRECISION,
        result_json JSONB NOT NULL,
        requested_as_of DATE NOT NULL,
        actual_as_of DATE,
        source TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        checksum TEXT NOT NULL,
        data_version TEXT,
        classification_version TEXT,
        membership_version TEXT,
        universe_version TEXT,
        adjustment_version TEXT,
        benchmark_version TEXT,
        calculation_version TEXT NOT NULL,
        fetched_at TIMESTAMPTZ,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        quality_status TEXT NOT NULL,
        observation_count INTEGER NOT NULL DEFAULT 0,
        field_availability_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (as_of, calculation_version, source_revision, checksum)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_backfill_runs (
        run_id TEXT PRIMARY KEY,
        as_of DATE NOT NULL,
        session_dates_json JSONB NOT NULL,
        source_revisions_json JSONB NOT NULL,
        calculation_version TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_backfill_attempts (
        run_id TEXT NOT NULL REFERENCES sector_backfill_runs(run_id),
        as_of DATE NOT NULL,
        status TEXT NOT NULL,
        requested_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        retry_eligible INTEGER NOT NULL DEFAULT 1,
        warning TEXT,
        compatible_result_checksum TEXT,
        PRIMARY KEY (run_id, as_of)
    )
    """,
    "CREATE INDEX IF NOT EXISTS sector_membership_lookup_idx ON sector_membership_intervals(security_id, valid_from, valid_to)",
    "CREATE INDEX IF NOT EXISTS sector_security_facts_date_idx ON sector_security_daily_facts(as_of, security_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS sector_security_fact_identity_idx ON sector_security_daily_facts(security_id, as_of, source_revision, COALESCE(adjustment_version, ''), checksum)",
    "CREATE INDEX IF NOT EXISTS sector_benchmark_facts_date_idx ON sector_benchmark_facts(as_of, benchmark_id)",
    "CREATE INDEX IF NOT EXISTS sector_industry_aggregates_date_idx ON sector_industry_aggregates(as_of, industry_id)",
    "CREATE INDEX IF NOT EXISTS sector_continuity_results_date_idx ON sector_continuity_results(as_of, calculation_version)",
    "CREATE INDEX IF NOT EXISTS sector_backfill_attempts_date_idx ON sector_backfill_attempts(as_of, status)",
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (7, 'add-sector-continuity-facts', CURRENT_TIMESTAMP,
            'add-sector-continuity-facts')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Evidence is retained on rollback; disabling the feature gate is the
    # non-destructive rollback path.
    pass
