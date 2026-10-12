"""Add normalized Fuyao THS catalog, market, and breadth evidence.

This migration is deliberately additive.  Legacy ``sectors`` snapshots,
collection tasks, capability reports, and materialized aggregates are not
updated, copied, relabeled, or deleted.  The non-destructive rollback path is
to disable the new feature gates while retaining collected evidence.
"""

from alembic import op


revision = "0005_ths_sector_datasets"
down_revision = "0004_sector_continuity"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS ths_catalog_revisions (
        revision_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        capability_revision TEXT NOT NULL,
        provider_timestamp TIMESTAMPTZ NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL,
        row_count INTEGER NOT NULL,
        tag_counts_json JSONB NOT NULL,
        tag_checksums_json JSONB NOT NULL,
        checksum TEXT NOT NULL,
        UNIQUE (revision_id, provider),
        UNIQUE (provider, capability_revision, checksum, fetched_at),
        CHECK (row_count > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_sector_identities (
        provider TEXT NOT NULL,
        thscode TEXT NOT NULL,
        first_seen_revision_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (provider, thscode),
        FOREIGN KEY (first_seen_revision_id, provider)
            REFERENCES ths_catalog_revisions(revision_id, provider)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_catalog_relations (
        catalog_revision_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        tag TEXT NOT NULL,
        thscode TEXT NOT NULL,
        display_name TEXT NOT NULL,
        relation_checksum TEXT NOT NULL,
        PRIMARY KEY (catalog_revision_id, tag, thscode),
        FOREIGN KEY (catalog_revision_id, provider)
            REFERENCES ths_catalog_revisions(revision_id, provider),
        FOREIGN KEY (provider, thscode)
            REFERENCES ths_sector_identities(provider, thscode),
        CHECK (tag IN ('industry', 'cn_concept', 'region', 'tszs'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_industry_rankings (
        provider TEXT NOT NULL,
        as_of DATE NOT NULL,
        catalog_revision_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        thscode TEXT NOT NULL,
        rank INTEGER NOT NULL,
        display_name TEXT NOT NULL,
        change_pct DOUBLE PRECISION NOT NULL,
        volume DOUBLE PRECISION,
        turnover DOUBLE PRECISION,
        source_revision TEXT NOT NULL,
        provider_timestamp TIMESTAMPTZ NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL,
        checksum TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (provider, as_of, catalog_revision_id, tag, thscode),
        FOREIGN KEY (catalog_revision_id, provider)
            REFERENCES ths_catalog_revisions(revision_id, provider),
        FOREIGN KEY (catalog_revision_id, tag, thscode)
            REFERENCES ths_catalog_relations(catalog_revision_id, tag, thscode),
        CHECK (tag IN ('industry', 'cn_concept', 'region', 'tszs')),
        CHECK (rank > 0),
        CHECK (volume IS NULL OR volume >= 0),
        CHECK (turnover IS NULL OR turnover >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_sector_daily_bars (
        provider TEXT NOT NULL,
        thscode TEXT NOT NULL,
        trading_date DATE NOT NULL,
        open DOUBLE PRECISION,
        high DOUBLE PRECISION,
        low DOUBLE PRECISION,
        close DOUBLE PRECISION,
        volume DOUBLE PRECISION,
        turnover DOUBLE PRECISION,
        source_revision TEXT NOT NULL,
        checksum TEXT NOT NULL,
        provider_timestamp TIMESTAMPTZ,
        fetched_at TIMESTAMPTZ NOT NULL,
        quality_status TEXT NOT NULL,
        field_quality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (provider, thscode, trading_date, source_revision),
        FOREIGN KEY (provider, thscode)
            REFERENCES ths_sector_identities(provider, thscode),
        CHECK (open IS NULL OR open >= 0),
        CHECK (high IS NULL OR high >= 0),
        CHECK (low IS NULL OR low >= 0),
        CHECK (close IS NULL OR close >= 0),
        CHECK (volume IS NULL OR volume >= 0),
        CHECK (turnover IS NULL OR turnover >= 0),
        CHECK (open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL OR close IS NOT NULL
               OR volume IS NOT NULL OR turnover IS NOT NULL)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_sector_memberships (
        provider TEXT NOT NULL,
        thscode TEXT NOT NULL,
        member_security_id TEXT NOT NULL,
        membership_as_of DATE NOT NULL,
        source_revision TEXT NOT NULL,
        member_name TEXT,
        provider_timestamp TIMESTAMPTZ NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL,
        checksum TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (provider, thscode, member_security_id, membership_as_of, source_revision),
        FOREIGN KEY (provider, thscode)
            REFERENCES ths_sector_identities(provider, thscode)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_member_daily_facts (
        security_id TEXT NOT NULL,
        trading_date DATE NOT NULL,
        original_open DOUBLE PRECISION,
        original_high DOUBLE PRECISION,
        original_low DOUBLE PRECISION,
        original_close DOUBLE PRECISION,
        adjusted_close DOUBLE PRECISION,
        adjustment_factor DOUBLE PRECISION,
        volume DOUBLE PRECISION,
        turnover DOUBLE PRECISION,
        source TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        checksum TEXT NOT NULL,
        quality_status TEXT NOT NULL,
        field_lineage_json JSONB NOT NULL,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        fetched_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (security_id, trading_date, source_revision),
        CHECK (original_open IS NULL OR original_open >= 0),
        CHECK (original_high IS NULL OR original_high >= 0),
        CHECK (original_low IS NULL OR original_low >= 0),
        CHECK (original_close IS NULL OR original_close >= 0),
        CHECK (adjusted_close IS NULL OR adjusted_close >= 0),
        CHECK (adjustment_factor IS NULL OR adjustment_factor >= 0),
        CHECK (volume IS NULL OR volume >= 0),
        CHECK (turnover IS NULL OR turnover >= 0),
        CHECK (adjusted_close IS NULL OR adjustment_factor IS NOT NULL)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_operations (
        run_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        capability_revision TEXT NOT NULL,
        request_checksum TEXT NOT NULL,
        request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        total_items INTEGER NOT NULL DEFAULT 0,
        completed_items INTEGER NOT NULL DEFAULT 0,
        failed_items INTEGER NOT NULL DEFAULT 0,
        conflict_items INTEGER NOT NULL DEFAULT 0,
        request_budget INTEGER NOT NULL,
        requests_used INTEGER NOT NULL DEFAULT 0,
        requested_at TIMESTAMPTZ NOT NULL,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        warning TEXT,
        CHECK (kind IN ('catalog-sync', 'turnover-backfill', 'member-import')),
        CHECK (status IN ('queued', 'running', 'success', 'partial', 'failed', 'conflict')),
        CHECK (total_items >= 0),
        CHECK (completed_items >= 0),
        CHECK (failed_items >= 0),
        CHECK (conflict_items >= 0),
        CHECK (completed_items + failed_items + conflict_items <= total_items),
        CHECK (request_budget >= 0),
        CHECK (requests_used >= 0 AND requests_used <= request_budget)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_backfill_runs (
        run_id TEXT PRIMARY KEY REFERENCES ths_operations(run_id),
        provider TEXT NOT NULL,
        requested_codes_json JSONB NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        UNIQUE (run_id, provider),
        CHECK (end_date >= start_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_backfill_checkpoints (
        run_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        thscode TEXT NOT NULL,
        window_start DATE NOT NULL,
        window_end DATE NOT NULL,
        status TEXT NOT NULL,
        source_revision TEXT NOT NULL,
        rows_written INTEGER NOT NULL DEFAULT 0,
        rows_skipped INTEGER NOT NULL DEFAULT 0,
        conflicts INTEGER NOT NULL DEFAULT 0,
        result_checksum TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        warning TEXT,
        PRIMARY KEY (run_id, thscode, window_start, window_end),
        FOREIGN KEY (run_id, provider)
            REFERENCES ths_backfill_runs(run_id, provider),
        FOREIGN KEY (provider, thscode)
            REFERENCES ths_sector_identities(provider, thscode),
        CHECK (window_end >= window_start),
        CHECK (rows_written >= 0),
        CHECK (rows_skipped >= 0),
        CHECK (conflicts >= 0),
        CHECK (status IN ('queued', 'running', 'success', 'partial', 'failed', 'conflict'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_sector_breadth_evidence (
        provider TEXT NOT NULL,
        thscode TEXT NOT NULL,
        as_of DATE NOT NULL,
        catalog_revision_id TEXT NOT NULL,
        calculation_revision TEXT NOT NULL,
        selection_reasons_json JSONB NOT NULL,
        member_count INTEGER NOT NULL,
        valid_direction_count INTEGER NOT NULL,
        advance_count INTEGER NOT NULL,
        decline_count INTEGER NOT NULL,
        flat_count INTEGER NOT NULL,
        advance_ratio DOUBLE PRECISION,
        advance_decline_spread_ratio DOUBLE PRECISION,
        median_change_pct DOUBLE PRECISION,
        valid_ma20_count INTEGER NOT NULL,
        close_above_ma20_count INTEGER NOT NULL,
        ma20_breadth DOUBLE PRECISION,
        limit_up_count INTEGER,
        limit_down_count INTEGER,
        top_by_turnover_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        top_by_gain_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        max_member_turnover_contribution DOUBLE PRECISION,
        diffusion_rate DOUBLE PRECISION,
        quality_status TEXT NOT NULL,
        lineage_json JSONB NOT NULL,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        checksum TEXT NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (provider, thscode, as_of, catalog_revision_id, calculation_revision),
        FOREIGN KEY (provider, thscode)
            REFERENCES ths_sector_identities(provider, thscode),
        FOREIGN KEY (catalog_revision_id, provider)
            REFERENCES ths_catalog_revisions(revision_id, provider),
        CHECK (member_count >= 0),
        CHECK (valid_direction_count >= 0 AND valid_direction_count <= member_count),
        CHECK (advance_count >= 0 AND decline_count >= 0 AND flat_count >= 0),
        CHECK (advance_count + decline_count + flat_count = valid_direction_count),
        CHECK (valid_ma20_count >= 0 AND valid_ma20_count <= member_count),
        CHECK (close_above_ma20_count >= 0 AND close_above_ma20_count <= valid_ma20_count),
        CHECK (limit_up_count IS NULL OR limit_up_count >= 0),
        CHECK (limit_down_count IS NULL OR limit_down_count >= 0),
        CHECK (advance_ratio IS NULL OR (advance_ratio >= 0 AND advance_ratio <= 1)),
        CHECK (advance_decline_spread_ratio IS NULL OR
               (advance_decline_spread_ratio >= -1 AND advance_decline_spread_ratio <= 1)),
        CHECK (ma20_breadth IS NULL OR (ma20_breadth >= 0 AND ma20_breadth <= 1)),
        CHECK (max_member_turnover_contribution IS NULL OR
               (max_member_turnover_contribution >= 0 AND max_member_turnover_contribution <= 1)),
        CHECK (diffusion_rate IS NULL OR (diffusion_rate >= 0 AND diffusion_rate <= 1))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ths_catalog_revisions_latest_idx ON ths_catalog_revisions(provider, fetched_at DESC)",
    "CREATE INDEX IF NOT EXISTS ths_catalog_relations_tag_name_idx ON ths_catalog_relations(tag, display_name, thscode)",
    "CREATE INDEX IF NOT EXISTS ths_catalog_relations_code_idx ON ths_catalog_relations(provider, thscode, tag, catalog_revision_id)",
    "CREATE INDEX IF NOT EXISTS ths_industry_rankings_date_rank_idx ON ths_industry_rankings(as_of, tag, rank)",
    "CREATE INDEX IF NOT EXISTS ths_industry_rankings_code_date_idx ON ths_industry_rankings(provider, thscode, as_of DESC)",
    "CREATE INDEX IF NOT EXISTS ths_sector_daily_bars_code_date_idx ON ths_sector_daily_bars(provider, thscode, trading_date DESC)",
    "CREATE INDEX IF NOT EXISTS ths_sector_daily_bars_date_quality_idx ON ths_sector_daily_bars(trading_date, quality_status, provider, thscode)",
    "CREATE INDEX IF NOT EXISTS ths_sector_memberships_sector_date_idx ON ths_sector_memberships(provider, thscode, membership_as_of DESC)",
    "CREATE INDEX IF NOT EXISTS ths_sector_memberships_member_date_idx ON ths_sector_memberships(member_security_id, membership_as_of DESC)",
    "CREATE INDEX IF NOT EXISTS ths_member_daily_facts_security_date_idx ON ths_member_daily_facts(security_id, trading_date DESC)",
    "CREATE INDEX IF NOT EXISTS ths_member_daily_facts_date_quality_idx ON ths_member_daily_facts(trading_date, quality_status, security_id)",
    "CREATE INDEX IF NOT EXISTS ths_operations_status_idx ON ths_operations(kind, status, requested_at DESC)",
    "CREATE INDEX IF NOT EXISTS ths_backfill_checkpoints_run_status_idx ON ths_backfill_checkpoints(run_id, status, thscode, window_start)",
    "CREATE INDEX IF NOT EXISTS ths_backfill_checkpoints_code_window_idx ON ths_backfill_checkpoints(provider, thscode, window_start, window_end)",
    "CREATE INDEX IF NOT EXISTS ths_sector_breadth_date_quality_idx ON ths_sector_breadth_evidence(as_of, quality_status, provider, thscode)",
    "CREATE INDEX IF NOT EXISTS ths_sector_breadth_code_date_idx ON ths_sector_breadth_evidence(provider, thscode, as_of DESC)",
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (8, 'add-ths-sector-datasets', CURRENT_TIMESTAMP,
            'add-ths-sector-datasets')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Retain normalized and legacy evidence; feature gates are the rollback path.
    pass
