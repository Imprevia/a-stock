"""Allow THS ranking rows to preserve provider-missing change percentages.

The domain contract accepts a missing daily change percentage on an individual
ranking row.  Keep that missing value as NULL in PostgreSQL instead of forcing
the collector to invent a numeric value or failing the whole collection.
"""

from alembic import op


revision = "0006_ths_rank_null_pct"
down_revision = "0005_ths_sector_datasets"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    "ALTER TABLE ths_industry_rankings ALTER COLUMN change_pct DROP NOT NULL",
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (9, 'ths-ranking-nullable-change-pct', CURRENT_TIMESTAMP,
            'ths-ranking-nullable-change-pct')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Keep the migration non-destructive.  Existing NULL observations must not
    # be invalidated by a rollback; feature gates provide the rollback path.
    pass
