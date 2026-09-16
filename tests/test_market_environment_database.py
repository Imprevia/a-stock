from datetime import date, datetime, timezone

import pytest
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

from src.market_environment.database import DatabaseConfigurationError, DatabaseSettings
from src.market_environment.postgres_migration import backup_sqlite, import_sqlite, sqlite_fingerprint
from src.market_environment.postgres_compat import _translate_sql
from src.market_environment.snapshot_store import SnapshotRecord, SnapshotStore


def _postgres_url() -> str | None:
    return os.getenv("MARKET_ENVIRONMENT_TEST_DATABASE_URL") or os.getenv("MARKET_ENVIRONMENT_DATABASE_URL")


def test_database_settings_fail_closed_without_url(monkeypatch):
    monkeypatch.delenv("MARKET_ENVIRONMENT_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_environment()


def test_database_settings_reject_non_postgresql(monkeypatch):
    monkeypatch.setenv("MARKET_ENVIRONMENT_DATABASE_URL", "sqlite:///tmp/test.db")
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_environment()


def test_sqlite_fingerprint_is_read_only_and_reports_counts(tmp_path):
    store = SnapshotStore(tmp_path / "source.sqlite3")
    value = SnapshotRecord(
        dataset="breadth",
        as_of=date(2026, 9, 16),
        payload={"up": 1},
        source="fixture",
        status="success",
        observations=1,
        warnings=(),
        fetched_at=datetime.now(timezone.utc),
    )
    store.put(value)
    fingerprint = sqlite_fingerprint(store.path)
    assert fingerprint["quickCheck"] == "ok"
    assert fingerprint["tables"]["snapshot_entries"] == 1
    assert store.get("breadth", value.as_of) == value.normalized()


def test_sqlite_backup_is_non_overwriting_and_import_dry_run_reports_lease(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "before.sqlite3"
    store = SnapshotStore(source)
    as_of = date(2026, 9, 16)
    store.acquire_lease("core", as_of, "old-worker", lease_seconds=300)
    first = backup_sqlite(source, backup)
    assert first["quickCheck"] == "ok"
    with pytest.raises(FileExistsError):
        backup_sqlite(source, backup)
    report = import_sqlite(source, database_url="postgresql://unused", apply=False)
    assert report["status"] == "dry-run"
    assert report["leaseConversion"]["activeRowsSkipped"] == 1
    assert report["source"]["tables"] == first["tables"]


def test_sqlite_import_dry_run_rejects_missing_required_tables(tmp_path):
    import sqlite3

    source = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE snapshot_entries (dataset TEXT)")
    with pytest.raises(ValueError, match="missing required tables"):
        import_sqlite(source, database_url="postgresql://unused", apply=False)


def test_sqlite_fingerprint_rejects_corrupt_source(tmp_path):
    source = tmp_path / "corrupt.sqlite3"
    source.write_bytes(b"not a sqlite database")
    with pytest.raises(Exception):
        sqlite_fingerprint(source)


def test_postgres_sql_translation_handles_existing_store_dialects():
    translated = _translate_sql(
        "INSERT OR REPLACE INTO refresh_runs (run_id, dataset, as_of, result_json, created_at) VALUES (?, ?, ?, ?, ?)"
    )
    assert translated is not None
    assert "%s" in translated
    assert "ON CONFLICT (run_id, dataset)" in translated
    assert _translate_sql("PRAGMA user_version") is None


@pytest.mark.integration
def test_postgres_schema_and_concurrent_lease_round_trip():
    url = _postgres_url()
    if not url:
        pytest.skip("set MARKET_ENVIRONMENT_TEST_DATABASE_URL to run PostgreSQL integration tests")
    first = SnapshotStore(database_url=url)
    second = SnapshotStore(database_url=url)
    as_of = date(2099, 1, 2)
    first.prune(as_of, now=datetime(2100, 1, 1, tzinfo=timezone.utc))
    first.put(SnapshotRecord("breadth", as_of, {"up": 1}, "fixture", "success", 1, (), datetime.now(timezone.utc)))
    assert second.get("breadth", as_of) is not None

    def acquire(store: SnapshotStore):
        return store.acquire_lease("core", as_of, "integration", lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(acquire, (first, second)))
    assert sum(lease is not None for lease in leases) == 1
    first.engine.dispose()  # type: ignore[union-attr]
    second.engine.dispose()  # type: ignore[union-attr]


@pytest.mark.integration
def test_postgres_schema_uses_native_date_timestamptz_jsonb():
    url = _postgres_url()
    if not url:
        pytest.skip("set MARKET_ENVIRONMENT_TEST_DATABASE_URL to run PostgreSQL integration tests")
    store = SnapshotStore(database_url=url)
    from sqlalchemy import text

    with store.engine.connect() as connection:  # type: ignore[union-attr]
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_name IN ('snapshot_entries','refresh_leases') "
                "AND column_name IN ('as_of','payload_json','fetched_at','expires_at')"
            )
        ).all()
    types = {(row[0], row[1]): row[2] for row in rows}
    assert types[("snapshot_entries", "as_of")] == "date"
    assert types[("snapshot_entries", "payload_json")] == "jsonb"
    assert types[("snapshot_entries", "fetched_at")] == "timestamp with time zone"
    assert types[("refresh_leases", "expires_at")] == "timestamp with time zone"
    store.engine.dispose()  # type: ignore[union-attr]


@pytest.mark.integration
def test_postgres_import_retry_deduplicates_identity_audits_and_expired_lease_event(tmp_path):
    """A retry must not append identity-backed audit rows or fail on conversion events."""

    url = _postgres_url()
    if not url:
        pytest.skip("set MARKET_ENVIRONMENT_TEST_DATABASE_URL to run PostgreSQL integration tests")

    source = tmp_path / "import-retry.sqlite3"
    owner = f"import-retry-{uuid.uuid4().hex}"
    as_of = date(2099, 12, 31)
    source_store = SnapshotStore(source)
    source_store.acquire_lease("core", as_of, owner, lease_seconds=300)
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO lease_fence_events"
            "(dataset, as_of, owner, generation, token, operation, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("core", as_of.isoformat(), owner, 1, "fixture-token", "fixture", "fixture", NOW.isoformat()),
        )

    first = import_sqlite(source, database_url=url, apply=True)
    second = import_sqlite(source, database_url=url, apply=True)
    assert first["status"] == second["status"] == "applied"

    from sqlalchemy import text

    verifier = SnapshotStore(database_url=url)
    with verifier.engine.connect() as connection:  # type: ignore[union-attr]
        count = connection.execute(
            text(
                "SELECT COUNT(*) FROM lease_fence_events "
                "WHERE dataset='core' AND as_of=:as_of AND owner=:owner AND operation='fixture'"
            ),
            {"as_of": as_of, "owner": owner},
        ).scalar_one()
    assert count == 1
    verifier.engine.dispose()  # type: ignore[union-attr]
