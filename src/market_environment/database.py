"""Database configuration and PostgreSQL engine construction."""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event, text


class DatabaseConfigurationError(RuntimeError):
    """Raised when the runtime database configuration is missing or invalid."""


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout: int = 10
    statement_timeout_ms: int = 30000

    def __post_init__(self) -> None:
        # Keep direct callers (CLI ``--database-url`` and migration helpers)
        # subject to the same fail-closed backend contract as environment
        # loading. Without this guard a typo such as ``sqlite:///...`` would
        # reach SQLAlchemy and fail later with an opaque PostgreSQL DDL error.
        if not self.url.strip().startswith(("postgresql://", "postgresql+psycopg://")):
            raise DatabaseConfigurationError("database URL must use PostgreSQL/psycopg")

    @classmethod
    def from_environment(cls, *, required: bool = True) -> "DatabaseSettings | None":
        value = os.getenv("MARKET_ENVIRONMENT_DATABASE_URL", "").strip()
        if not value:
            if required:
                raise DatabaseConfigurationError(
                    "MARKET_ENVIRONMENT_DATABASE_URL is required; SQLite runtime fallback is disabled"
                )
            return None
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise DatabaseConfigurationError("database URL must use PostgreSQL/psycopg")
        return cls(
            url=value,
            pool_size=_int_env("MARKET_ENVIRONMENT_DB_POOL_SIZE", 5, minimum=1),
            max_overflow=_int_env("MARKET_ENVIRONMENT_DB_MAX_OVERFLOW", 5, minimum=0),
            pool_timeout=_int_env("MARKET_ENVIRONMENT_DB_POOL_TIMEOUT", 10, minimum=1),
            statement_timeout_ms=_int_env(
                "MARKET_ENVIRONMENT_DB_STATEMENT_TIMEOUT_MS", 30000, minimum=100
            ),
        )


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise DatabaseConfigurationError(f"{name} must be >= {minimum}")
    return value


def create_database_engine(settings: DatabaseSettings | None = None) -> Engine:
    """Create a pooled PostgreSQL engine with bounded transaction statements."""

    settings = settings or DatabaseSettings.from_environment(required=True)
    assert settings is not None
    engine = create_engine(
        settings.url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout,
        pool_pre_ping=True,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection, _connection_record) -> None:
        # psycopg accepts the parameterized statement; this runs once per pool
        # connection and avoids leaving long-running collection transactions
        # unbounded.
        cursor = dbapi_connection.cursor()
        try:
            # PostgreSQL does not accept bind parameters in a SET assignment;
            # set_config is equivalent and remains safely parameterized.
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (f"{settings.statement_timeout_ms}ms",),
            )
        finally:
            cursor.close()

    return engine


def check_database(engine: Engine) -> None:
    """Fail closed unless the configured PostgreSQL endpoint answers."""

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
