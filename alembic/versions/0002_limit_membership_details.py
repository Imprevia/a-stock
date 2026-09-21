"""add limits membership completeness and security detail fields"""

from alembic import op


revision = "0002_limit_membership_details"
down_revision = "0001_postgresql_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE limit_security_datasets ADD COLUMN IF NOT EXISTS membership_complete INTEGER",
        "ALTER TABLE limit_security_datasets ADD COLUMN IF NOT EXISTS streak_complete INTEGER",
        "ALTER TABLE limit_security_datasets ADD COLUMN IF NOT EXISTS pool_quality_json JSONB",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS is_new INTEGER",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS limit_up_time TEXT",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS limit_up_reason TEXT",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS seal_money DOUBLE PRECISION",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS max_seal_money DOUBLE PRECISION",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS first_limit_time TEXT",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS last_limit_time TEXT",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS open_times INTEGER",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS turnover_ratio_pct DOUBLE PRECISION",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS turnover DOUBLE PRECISION",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS row_quality TEXT",
        "ALTER TABLE limit_security_facts ADD COLUMN IF NOT EXISTS row_warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb",
    ):
        op.execute(statement)
    op.execute(
        """
        INSERT INTO schema_migrations(version, name, applied_at, checksum)
        VALUES (5, 'add-limit-membership-and-detail-fields', CURRENT_TIMESTAMP,
                'add-limit-membership-and-detail-fields')
        ON CONFLICT(version) DO NOTHING
        """
    )


def downgrade() -> None:
    # Historical market facts are retained during application rollback.
    pass
