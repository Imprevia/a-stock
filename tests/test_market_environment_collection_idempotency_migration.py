from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

from src.market_environment.infrastructure.persistence.postgres import (
    MINIMUM_SCHEMA_VERSION,
    REQUIRED_RUNTIME_TABLES,
)
from src.market_environment.postgres_schema import SCHEMA_STATEMENTS, create_schema


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    ROOT / "alembic" / "versions" / "0008_collection_idempotency.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "collection_idempotency_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).lower()


def _fresh_statement(prefix: str) -> str:
    return next(
        statement
        for statement in SCHEMA_STATEMENTS
        if _normalize_sql(statement).startswith(prefix)
    )


def _sqlite_sql(statement: str) -> str:
    value = re.sub(r"::jsonb\b", "", statement, flags=re.IGNORECASE)
    value = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", value, flags=re.IGNORECASE)
    value = re.sub(r"\bJSONB\b", "TEXT", value, flags=re.IGNORECASE)
    value = re.sub(r"char_length\(([^)]+)\)", r"length(\1)", value, flags=re.IGNORECASE)
    return value


def _create_v10_fixture(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL,
            applied_at TEXT NOT NULL, checksum TEXT NOT NULL
        );
        CREATE TABLE collection_runs (
            run_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, status TEXT NOT NULL,
            requested_datasets_json TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT, completed_at TEXT
        );
        CREATE TABLE collection_tasks (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
            dataset TEXT NOT NULL, as_of TEXT NOT NULL, status TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'none', observations INTEGER NOT NULL DEFAULT 0,
            warning TEXT, timings_json TEXT NOT NULL DEFAULT '{}', queued_at TEXT,
            started_at TEXT, completed_at TEXT, duration_ms REAL,
            settled INTEGER NOT NULL DEFAULT 0,
            UNIQUE(run_id, dataset)
        );
        INSERT INTO schema_migrations VALUES
            (10, 'ths-catalog-revision-identity', '2026-10-15T00:00:00Z',
             'ths-catalog-revision-identity');
        INSERT INTO collection_runs VALUES
            ('run-existing', '2026-10-14', 'partial',
             '["core","breadth"]', '2026-10-14T08:30:00Z',
             '2026-10-14T08:30:01Z', '2026-10-14T08:31:00Z');
        INSERT INTO collection_tasks VALUES
            ('task-existing', 'run-existing', 'core', '2026-10-14',
             'failed-retained', 'eastmoney', 0, 'historical warning', '{}',
             '2026-10-14T08:30:00Z', '2026-10-14T08:30:01Z',
             '2026-10-14T08:31:00Z', 59000, 1);
        """
    )


def _apply_migration_to_sqlite(connection: sqlite3.Connection) -> None:
    migration = _load_migration()
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(collection_tasks)")
    }
    if "failure_json" not in columns:
        connection.execute("ALTER TABLE collection_tasks ADD COLUMN failure_json TEXT")
    for statement in migration.UPGRADE_STATEMENTS[1:-1]:
        connection.execute(_sqlite_sql(statement))
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, checksum)
        VALUES (11, 'collection-idempotency-and-failures', CURRENT_TIMESTAMP,
                'collection-idempotency-and-failures')
        """
    )


def test_0008_is_additive_and_matches_fresh_schema_contract() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0008_collection_idempotency"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "0007_ths_catalog_identity"
    normalized = tuple(map(_normalize_sql, operations.statements))
    assert normalized[0].startswith(
        "alter table collection_tasks add column if not exists failure_json jsonb"
    )
    assert normalized[1] == _normalize_sql(
        _fresh_statement("create table if not exists collection_idempotency_bindings")
    )
    assert normalized[2] == _normalize_sql(
        _fresh_statement(
            "create index if not exists collection_idempotency_bindings_run_idx"
        )
    )
    assert normalized[3] == _normalize_sql(
        _fresh_statement(
            "create index if not exists collection_idempotency_bindings_submission_idx"
        )
    )
    assert "values (11, 'collection-idempotency-and-failures'" in normalized[4]
    assert "on conflict(version) do nothing" in normalized[4]
    assert not re.search(
        r"\b(drop\s+table|delete\s+from|truncate)\b",
        "\n".join(normalized),
    )
    assert MINIMUM_SCHEMA_VERSION == 11
    assert "collection_idempotency_bindings" in REQUIRED_RUNTIME_TABLES


def test_v10_upgrade_and_isolated_backup_restore_preserve_collection_history() -> None:
    connection = sqlite3.connect(":memory:")
    _create_v10_fixture(connection)
    expected_run = connection.execute(
        "SELECT * FROM collection_runs WHERE run_id='run-existing'"
    ).fetchone()
    expected_task = connection.execute(
        "SELECT * FROM collection_tasks WHERE task_id='task-existing'"
    ).fetchone()

    before_image = sqlite3.connect(":memory:")
    connection.backup(before_image)
    assert before_image.execute(
        "SELECT * FROM collection_runs WHERE run_id='run-existing'"
    ).fetchone() == expected_run

    _apply_migration_to_sqlite(connection)
    _apply_migration_to_sqlite(connection)
    connection.commit()

    assert connection.execute(
        "SELECT * FROM collection_runs WHERE run_id='run-existing'"
    ).fetchone() == expected_run
    migrated_task = connection.execute(
        """
        SELECT task_id, run_id, dataset, as_of, status, source, observations,
               warning, timings_json, queued_at, started_at, completed_at,
               duration_ms, settled
        FROM collection_tasks WHERE task_id='task-existing'
        """
    ).fetchone()
    assert migrated_task == expected_task
    assert connection.execute(
        "SELECT failure_json FROM collection_tasks WHERE task_id='task-existing'"
    ).fetchone() == (None,)
    assert connection.execute(
        "SELECT COUNT(*) FROM collection_idempotency_bindings"
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=11"
    ).fetchone() == (1,)

    restored = sqlite3.connect(":memory:")
    connection.backup(restored)
    assert restored.execute(
        "SELECT * FROM collection_runs WHERE run_id='run-existing'"
    ).fetchone() == expected_run
    assert restored.execute(
        "SELECT failure_json FROM collection_tasks WHERE task_id='task-existing'"
    ).fetchone() == (None,)
    assert restored.execute(
        "SELECT COUNT(*) FROM collection_idempotency_bindings"
    ).fetchone() == (0,)

    restored.close()
    before_image.close()
    connection.close()


def test_0008_downgrade_and_fresh_bootstrap_are_non_destructive() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert operations.statements == []
    source = Path(create_schema.__code__.co_filename).read_text(encoding="utf-8")
    assert "VALUES (11, 'collection-idempotency-and-failures'" in source
