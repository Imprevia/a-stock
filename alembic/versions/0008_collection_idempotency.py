"""Add durable full-collection idempotency and structured task failures."""

from alembic import op


revision = "0008_collection_idempotency"
down_revision = "0007_ths_catalog_identity"
branch_labels = None
depends_on = None


UPGRADE_STATEMENTS = (
    """
    ALTER TABLE collection_tasks
    ADD COLUMN IF NOT EXISTS failure_json JSONB
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_idempotency_bindings (
        operation_scope TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        semantic_fingerprint TEXT NOT NULL,
        resolved_as_of DATE NOT NULL,
        operation_version TEXT NOT NULL,
        dataset_fingerprint TEXT NOT NULL,
        run_id TEXT NOT NULL UNIQUE REFERENCES collection_runs(run_id),
        submission_state TEXT NOT NULL DEFAULT 'reserved',
        submission_attempts INTEGER NOT NULL DEFAULT 0,
        submission_owner TEXT,
        submission_lease_expires_at TIMESTAMPTZ,
        submission_error_json JSONB,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        submitted_at TIMESTAMPTZ,
        PRIMARY KEY (operation_scope, idempotency_key),
        CHECK (char_length(operation_scope) > 0),
        CHECK (char_length(idempotency_key) > 0),
        CHECK (char_length(semantic_fingerprint) = 64),
        CHECK (char_length(dataset_fingerprint) = 64),
        CHECK (submission_attempts >= 0),
        CHECK (submission_state IN ('reserved', 'submitting', 'submitted', 'submission-failed'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS collection_idempotency_bindings_run_idx
    ON collection_idempotency_bindings(run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS collection_idempotency_bindings_submission_idx
    ON collection_idempotency_bindings(submission_state, submission_lease_expires_at)
    """,
    """
    INSERT INTO schema_migrations(version, name, applied_at, checksum)
    VALUES (11, 'collection-idempotency-and-failures', CURRENT_TIMESTAMP,
            'collection-idempotency-and-failures')
    ON CONFLICT(version) DO NOTHING
    """,
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Idempotency bindings and classified failures are operational evidence.
    # Roll back the application feature gate instead of deleting history.
    pass
