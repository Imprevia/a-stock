"""PostgreSQL runtime connection factory and read-only compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import Engine, text

from ....database import DatabaseSettings, create_database_engine


MINIMUM_SCHEMA_VERSION = 10
REQUIRED_RUNTIME_TABLES = frozenset(
    {
        "collection_runs",
        "collection_tasks",
        "core_index_results",
        "limit_security_datasets",
        "limit_security_facts",
        "materialization_component_versions",
        "materialized_market_environment",
        "provider_capability_reports",
        "sector_taxonomy_revisions",
        "sector_industries",
        "sector_membership_intervals",
        "sector_security_daily_facts",
        "sector_benchmark_facts",
        "sector_industry_aggregates",
        "sector_continuity_results",
        "sector_backfill_runs",
        "sector_backfill_attempts",
        "refresh_leases",
        "snapshot_entries",
        "timezone_preferences",
        "ths_backfill_checkpoints",
        "ths_backfill_runs",
        "ths_catalog_relations",
        "ths_catalog_revisions",
        "ths_industry_rankings",
        "ths_member_daily_facts",
        "ths_operations",
        "ths_sector_breadth_evidence",
        "ths_sector_daily_bars",
        "ths_sector_identities",
        "ths_sector_memberships",
        "trading_sessions",
    }
)


class DatabaseSchemaCompatibilityError(RuntimeError):
    """Raised when the configured database has not been migrated for runtime use."""


@dataclass(frozen=True, slots=True)
class RuntimeSchemaReport:
    version: int
    tables: frozenset[str]


class PostgresConnectionFactory:
    """Own an engine and open transaction-ready PostgreSQL connections."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @classmethod
    def from_settings(
        cls,
        settings: DatabaseSettings,
        *,
        engine_factory: Callable[[DatabaseSettings], Engine] = create_database_engine,
        validate_runtime: bool = True,
    ) -> "PostgresConnectionFactory":
        factory = cls(engine_factory(settings))
        if validate_runtime:
            try:
                factory.validate_runtime()
            except BaseException:
                factory.dispose()
                raise
        return factory

    def connect(self):
        return self.engine.connect()

    def validate_runtime(self) -> RuntimeSchemaReport:
        """Check connectivity and migrated schema using SELECT statements only."""

        with self.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            tables = frozenset(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()"
                    )
                )
                .scalars()
                .all()
            )
            missing = sorted(REQUIRED_RUNTIME_TABLES - tables)
            if missing:
                raise DatabaseSchemaCompatibilityError(
                    "PostgreSQL runtime schema is missing required tables: "
                    + ", ".join(missing)
                )
            version = connection.execute(
                text("SELECT MAX(version) FROM schema_migrations")
            ).scalar_one_or_none()
            if version is None or int(version) < MINIMUM_SCHEMA_VERSION:
                raise DatabaseSchemaCompatibilityError(
                    "PostgreSQL runtime schema version "
                    f"{version!r} is below required version {MINIMUM_SCHEMA_VERSION}"
                )
        return RuntimeSchemaReport(int(version), tables)

    def dispose(self) -> None:
        self.engine.dispose()


__all__ = [
    "DatabaseSchemaCompatibilityError",
    "MINIMUM_SCHEMA_VERSION",
    "PostgresConnectionFactory",
    "REQUIRED_RUNTIME_TABLES",
    "RuntimeSchemaReport",
]
