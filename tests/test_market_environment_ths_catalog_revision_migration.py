from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

from src.market_environment.postgres_schema import SCHEMA_STATEMENTS


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0007_ths_catalog_revision_identity.py"


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "ths_catalog_revision_identity_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).lower()


def _sqlite_sql(statement: str) -> str:
    value = re.sub(r"::jsonb\b", "", statement, flags=re.IGNORECASE)
    value = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", value, flags=re.IGNORECASE)
    value = re.sub(r"\bJSONB\b", "TEXT", value, flags=re.IGNORECASE)
    return value


def _fresh_catalog_table_sql() -> str:
    return next(
        statement
        for statement in SCHEMA_STATEMENTS
        if _normalize_sql(statement).startswith(
            "create table if not exists ths_catalog_revisions"
        )
    )


def test_0007_removes_only_the_non_date_catalog_unique_and_records_version_10() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0007_ths_catalog_identity"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "0006_ths_rank_null_pct"
    assert len(operations.statements) == 2

    drop_sql = _normalize_sql(operations.statements[0])
    assert "drop constraint" in drop_sql
    assert "ths_catalog_revisions" in drop_sql
    assert "pg_get_constraintdef" in drop_sql
    assert "unique (provider, capability_revision, checksum, fetched_at)" in drop_sql
    assert not re.search(r"\b(drop\s+table|delete|update|truncate)\b", drop_sql)

    ledger_sql = _normalize_sql(operations.statements[1])
    assert "values (10, 'ths-catalog-revision-identity'" in ledger_sql
    assert "on conflict(version) do nothing" in ledger_sql


def test_0007_downgrade_is_non_destructive() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert operations.statements == []


def test_fresh_schema_allows_same_catalog_content_and_fetch_time_on_two_dates() -> None:
    table_sql = _fresh_catalog_table_sql()
    normalized = _normalize_sql(table_sql)
    assert "unique (provider, capability_revision, checksum, fetched_at)" not in normalized

    connection = sqlite3.connect(":memory:")
    connection.execute(_sqlite_sql(table_sql))
    rows = (
        (
            "fuyao:cap-v1:2026-10-13:sha256:same",
            "fuyao",
            "cap-v1",
            "2026-10-13T08:00:00+00:00",
            "2026-10-14T08:00:00+00:00",
            1,
            '{"industry":1}',
            '{"industry":"same"}',
            "same-checksum",
        ),
        (
            "fuyao:cap-v1:2026-10-14:sha256:same",
            "fuyao",
            "cap-v1",
            "2026-10-14T08:00:00+00:00",
            "2026-10-14T08:00:00+00:00",
            1,
            '{"industry":1}',
            '{"industry":"same"}',
            "same-checksum",
        ),
    )
    connection.executemany(
        """
        INSERT INTO ths_catalog_revisions(
            revision_id, provider, capability_revision, provider_timestamp,
            fetched_at, row_count, tag_counts_json, tag_checksums_json, checksum
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    assert connection.execute(
        "SELECT revision_id FROM ths_catalog_revisions ORDER BY revision_id"
    ).fetchall() == [
        ("fuyao:cap-v1:2026-10-13:sha256:same",),
        ("fuyao:cap-v1:2026-10-14:sha256:same",),
    ]
    connection.close()
