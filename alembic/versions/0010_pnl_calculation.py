"""Persist screenshot calculation state and independently sourced events."""

from alembic import op


revision = "0010_pnl_calculation"
down_revision = "0009_trading_pnl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_calculations (
            batch_id TEXT PRIMARY KEY,
            start_date DATE NOT NULL,
            horizon DATE CHECK (horizon >= start_date),
            result JSONB,
            token TEXT,
            expires_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_action_events (
            security TEXT NOT NULL,
            ex_date DATE NOT NULL,
            data JSONB NOT NULL,
            PRIMARY KEY (security, ex_date)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trading_pnl_action_windows (
            security TEXT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL CHECK (end_date >= start_date),
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (security, start_date, end_date)
        )
    """)


def downgrade() -> None:
    # Retain accounting evidence and calculation history during rollback.
    pass
