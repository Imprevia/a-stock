"""bootstrap the PostgreSQL runtime schema"""

from alembic import op

from src.market_environment.database import create_database_engine
from src.market_environment.postgres_schema import create_schema

revision = "0001_postgresql_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # The schema helper is idempotent and is also used by local bootstrap.
    create_schema(bind.engine)


def downgrade() -> None:
    # Runtime downgrade is intentionally non-destructive. Restore from a
    # reviewed PostgreSQL backup instead of dropping historical market facts.
    pass
