"""make provider capability schema explicit in Alembic"""

from alembic import op


revision = "0003_provider_capability_reports"
down_revision = "0002_limit_membership_details"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS provider_capability_reports (
        provider TEXT NOT NULL,
        dataset TEXT NOT NULL,
        revision TEXT NOT NULL,
        status TEXT NOT NULL,
        endpoint TEXT,
        field_coverage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        date_evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        history_window_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        pagination_evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        permission_evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        rate_limit_evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        sample_count INTEGER NOT NULL DEFAULT 0,
        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        missing_evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        checked_at TIMESTAMPTZ NOT NULL,
        schema_version INTEGER NOT NULL,
        checksum TEXT NOT NULL,
        PRIMARY KEY(provider, dataset, revision)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS provider_capability_reports_dataset_idx
    ON provider_capability_reports(dataset, checked_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS provider_capability_reports_status_idx
    ON provider_capability_reports(dataset, status)
    """,
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (6, 'add-provider-capability-reports', CURRENT_TIMESTAMP,
            'add-provider-capability-reports')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Capability reports are retained as audit evidence during app rollback.
    pass
