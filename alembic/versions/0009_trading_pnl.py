"""Create the independent personal trading ledger."""

from alembic import op


revision = "0009_trading_pnl"
down_revision = "0008_collection_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_state (
            singleton BOOLEAN PRIMARY KEY CHECK (singleton),
            revision BIGINT NOT NULL DEFAULT 0,
            opening_date DATE,
            opening_positions JSONB NOT NULL DEFAULT '{}'
        )
    """)
    op.execute("INSERT INTO trading_pnl_state(singleton) VALUES (TRUE) ON CONFLICT DO NOTHING")
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_drafts (
            id TEXT PRIMARY KEY,
            images JSONB NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            finished BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_images (
            digest TEXT PRIMARY KEY CHECK (char_length(digest) = 64),
            preview BYTEA,
            rows JSONB,
            hints JSONB,
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS trading_pnl_images_exp ON trading_pnl_images(expires_at) WHERE preview IS NOT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_trades (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trade_date DATE NOT NULL,
            security TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            data JSONB NOT NULL,
            digest TEXT NOT NULL REFERENCES trading_pnl_images(digest),
            row_number INTEGER NOT NULL CHECK (row_number >= 0),
            strong_id TEXT UNIQUE,
            revision BIGINT NOT NULL,
            UNIQUE (digest, row_number)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS trading_pnl_trade_day ON trading_pnl_trades(trade_date, id)")
    op.execute("CREATE INDEX IF NOT EXISTS trading_pnl_trade_match ON trading_pnl_trades(trade_date, security, side)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_operations (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            result JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_audit (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            revision BIGINT NOT NULL,
            data JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_coverage (
            as_of DATE PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('complete', 'no-trades'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_sessions (
            as_of DATE PRIMARY KEY,
            actual_as_of DATE NOT NULL CHECK (actual_as_of = as_of),
            previous_as_of DATE CHECK (previous_as_of < as_of),
            is_session BOOLEAN NOT NULL,
            source TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_valuations (
            as_of DATE NOT NULL,
            security TEXT NOT NULL,
            data JSONB NOT NULL,
            PRIMARY KEY (as_of, security)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_days (
            as_of DATE PRIMARY KEY,
            revision BIGINT NOT NULL,
            data JSONB NOT NULL
        )
    """)


def downgrade() -> None:
    # Retain personal accounting data during an application rollback.
    pass
