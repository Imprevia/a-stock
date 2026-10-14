"""Remove the non-date uniqueness shortcut from THS catalog observations.

``revision_id`` is the immutable observation identity.  The historical
``(provider, capability_revision, checksum, fetched_at)`` unique constraint
was only a fetch-level deduplication shortcut and omitted the trading date
embedded in the revision id.  It can therefore reject two valid observations
when an offline replay uses the same fetch timestamp on different dates.

The migration removes only that redundant constraint.  No catalog rows or
dependent evidence are rewritten, and downgrade remains non-destructive.
"""

from alembic import op


revision = "0007_ths_catalog_identity"
down_revision = "0006_ths_rank_null_pct"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    DO $$
    DECLARE
        constraint_name TEXT;
    BEGIN
        SELECT c.conname
          INTO constraint_name
          FROM pg_constraint AS c
          JOIN pg_class AS t ON t.oid = c.conrelid
          JOIN pg_namespace AS n ON n.oid = t.relnamespace
         WHERE n.nspname = current_schema()
           AND t.relname = 'ths_catalog_revisions'
           AND c.contype = 'u'
           AND pg_get_constraintdef(c.oid) =
               'UNIQUE (provider, capability_revision, checksum, fetched_at)';

        IF constraint_name IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE %I DROP CONSTRAINT %I',
                'ths_catalog_revisions',
                constraint_name
            );
        END IF;
    END
    $$
    """,
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (10, 'ths-catalog-revision-identity', CURRENT_TIMESTAMP,
            'ths-catalog-revision-identity')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Recreating the old constraint could reject valid cross-date observations;
    # retain evidence and use the feature gate as the rollback path.
    pass
