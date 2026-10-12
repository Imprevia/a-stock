from __future__ import annotations

import importlib.util
import inspect
import re
import sqlite3
from pathlib import Path

from src.market_environment.postgres_schema import SCHEMA_STATEMENTS, create_schema


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0005_ths_sector_datasets.py"

THS_TABLES = (
    "ths_catalog_revisions",
    "ths_sector_identities",
    "ths_catalog_relations",
    "ths_industry_rankings",
    "ths_sector_daily_bars",
    "ths_sector_memberships",
    "ths_member_daily_facts",
    "ths_operations",
    "ths_backfill_runs",
    "ths_backfill_checkpoints",
    "ths_sector_breadth_evidence",
)

THS_INDEXES = (
    "ths_catalog_revisions_latest_idx",
    "ths_catalog_relations_tag_name_idx",
    "ths_catalog_relations_code_idx",
    "ths_industry_rankings_date_rank_idx",
    "ths_industry_rankings_code_date_idx",
    "ths_sector_daily_bars_code_date_idx",
    "ths_sector_daily_bars_date_quality_idx",
    "ths_sector_memberships_sector_date_idx",
    "ths_sector_memberships_member_date_idx",
    "ths_member_daily_facts_security_date_idx",
    "ths_member_daily_facts_date_quality_idx",
    "ths_operations_status_idx",
    "ths_backfill_checkpoints_run_status_idx",
    "ths_backfill_checkpoints_code_window_idx",
    "ths_sector_breadth_date_quality_idx",
    "ths_sector_breadth_code_date_idx",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "test_0005_ths_sector_datasets",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).lower()


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


class SqliteOperations(RecordingOperations):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.connection = connection

    def execute(self, statement: str) -> None:
        super().execute(statement)
        translated = re.sub(r"::jsonb\b", "", statement, flags=re.IGNORECASE)
        translated = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", translated, flags=re.IGNORECASE)
        translated = re.sub(r"\bJSONB\b", "TEXT", translated, flags=re.IGNORECASE)
        self.connection.execute(translated)


def _runtime_ths_statements() -> tuple[str, ...]:
    prefixes = tuple(
        [f"create table if not exists {table}" for table in THS_TABLES]
        + [f"create index if not exists {index}" for index in THS_INDEXES]
    )
    return tuple(
        statement
        for statement in SCHEMA_STATEMENTS
        if _normalize_sql(statement).startswith(prefixes)
    )


def test_0005_revision_is_additive_and_matches_runtime_schema_contract() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0005_ths_sector_datasets"
    assert migration.down_revision == "0004_sector_continuity"
    assert tuple(map(_normalize_sql, operations.statements[:-1])) == tuple(
        map(_normalize_sql, _runtime_ths_statements())
    )
    assert "values (8, 'add-ths-sector-datasets'" in _normalize_sql(
        operations.statements[-1]
    )
    assert "on conflict(version) do nothing" in _normalize_sql(
        operations.statements[-1]
    )
    destructive = re.compile(r"\b(alter|drop|update|delete|truncate)\b", re.IGNORECASE)
    assert all(destructive.search(statement) is None for statement in operations.statements)


def test_0005_business_keys_columns_and_query_indexes_are_explicit() -> None:
    migration = _load_migration()
    sql = "\n".join(map(_normalize_sql, migration.UPGRADE_STATEMENTS))

    for table in THS_TABLES:
        assert f"create table if not exists {table}" in sql
    for index in THS_INDEXES:
        assert f"create index if not exists {index}" in sql

    expected_fragments = (
        "primary key (provider, thscode)",
        "primary key (catalog_revision_id, tag, thscode)",
        "primary key (provider, as_of, catalog_revision_id, tag, thscode)",
        "primary key (provider, thscode, trading_date, source_revision)",
        "primary key (provider, thscode, member_security_id, membership_as_of, source_revision)",
        "primary key (security_id, trading_date, source_revision)",
        "primary key (run_id, thscode, window_start, window_end)",
        "primary key (provider, thscode, as_of, catalog_revision_id, calculation_revision)",
        "tag_checksums_json jsonb not null",
        "field_quality_json jsonb not null",
        "field_lineage_json jsonb not null",
        "kind text not null",
        "request_json jsonb not null",
        "progress_json jsonb not null",
        "result_json jsonb not null",
        "catalog_revision_id text not null",
        "calculation_revision text not null",
        "checksum text not null",
        "fetched_at timestamptz not null",
    )
    for fragment in expected_fragments:
        assert fragment in sql


def test_0005_upgrade_rollback_and_migrate_again_preserve_legacy_sectors_rows() -> None:
    migration = _load_migration()
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL,
            applied_at TEXT NOT NULL, checksum TEXT NOT NULL
        );
        CREATE TABLE snapshot_entries (
            dataset TEXT NOT NULL, as_of TEXT NOT NULL, payload_json TEXT NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL, checksum TEXT NOT NULL,
            PRIMARY KEY (dataset, as_of)
        );
        CREATE TABLE collection_tasks (
            task_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, as_of TEXT NOT NULL,
            status TEXT NOT NULL, warning TEXT
        );
        CREATE TABLE provider_capability_reports (
            provider TEXT NOT NULL, dataset TEXT NOT NULL, revision TEXT NOT NULL,
            status TEXT NOT NULL, checksum TEXT NOT NULL,
            PRIMARY KEY (provider, dataset, revision)
        );
        CREATE TABLE materialized_market_environment (
            as_of TEXT PRIMARY KEY, payload_json TEXT NOT NULL, checksum TEXT NOT NULL
        );
        INSERT INTO snapshot_entries VALUES
            ('sectors', '2026-10-09', '{"rows":[{"code":"885001.TI"}]}',
             'fuyao', 'fallback', 'legacy-snapshot');
        INSERT INTO collection_tasks VALUES
            ('legacy-sector-task', 'sectors', '2026-10-09', 'success', 'legacy-warning');
        INSERT INTO provider_capability_reports VALUES
            ('fuyao', 'sectors', 'fuyao-market-v2', 'eligible', 'legacy-capability');
        INSERT INTO materialized_market_environment VALUES
            ('2026-10-09', '{"chapter01":{"sectors":{"state":"fallback"}}}',
             'legacy-aggregate');
        """
    )
    expected = {
        table: connection.execute(f"SELECT * FROM {table}").fetchall()
        for table in (
            "snapshot_entries",
            "collection_tasks",
            "provider_capability_reports",
            "materialized_market_environment",
        )
    }
    operations = SqliteOperations(connection)
    migration.op = operations

    migration.upgrade()
    migration.upgrade()
    migration.downgrade()
    migration.upgrade()
    connection.commit()

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert set(THS_TABLES) <= tables
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=8"
    ).fetchone() == (1,)
    for table, rows in expected.items():
        assert connection.execute(f"SELECT * FROM {table}").fetchall() == rows
    connection.close()


def test_0005_downgrade_is_non_destructive_and_bootstrap_records_version_8() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert operations.statements == []
    source = inspect.getsource(create_schema)
    assert "VALUES (8, 'add-ths-sector-datasets'" in source
