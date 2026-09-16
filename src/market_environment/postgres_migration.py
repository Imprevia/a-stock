"""Controlled SQLite-to-PostgreSQL import helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .database import DatabaseSettings, create_database_engine
from .postgres_schema import create_schema

IMPORT_TABLES = (
    "snapshot_entries",
    "refresh_runs",
    "collection_runs",
    "collection_tasks",
    "core_index_results",
    "materialized_market_environment",
    "date_relabel_audits",
    "trading_sessions",
    "limit_security_datasets",
    "limit_security_facts",
    "materialization_component_versions",
    "refresh_lease_fences",
    "lease_fence_events",
    "timezone_preferences",
    "timezone_preference_audit",
)
SKIP_TABLES = {"refresh_leases"}
REQUIRED_IMPORT_TABLES = frozenset({
    "snapshot_entries", "refresh_runs", "collection_runs", "collection_tasks",
    "core_index_results", "materialized_market_environment", "trading_sessions",
    "limit_security_datasets", "limit_security_facts", "refresh_lease_fences",
})


def sqlite_fingerprint(path: Path) -> dict[str, Any]:
    """Validate and summarize a source SQLite file without mutating it."""

    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise ValueError(f"SQLite quick_check failed: {quick_check}")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {}
        details = {}
        for table in sorted(tables):
            if table.startswith("sqlite_"):
                continue
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
            primary_keys = [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})") if row[5]
            ]
            details[table] = _table_details(rows, columns, primary_keys=primary_keys)
            counts[table] = len(rows)
    return {"path": str(path), "sha256": digest, "quickCheck": quick_check, "tables": counts, "tableDetails": details}


def backup_sqlite(source: Path, destination: Path) -> dict[str, Any]:
    """Create an online-consistent SQLite backup without overwriting output."""

    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Validate before opening the source for backup.  The read-only URI also
    # prevents SQLite from creating or mutating a missing/invalid source.
    sqlite_fingerprint(source)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    return sqlite_fingerprint(destination)


def import_sqlite(
    source: Path,
    *,
    database_url: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Import durable SQLite history into PostgreSQL, idempotently."""

    fingerprint = sqlite_fingerprint(source)
    missing = sorted(REQUIRED_IMPORT_TABLES - set(fingerprint["tables"]))
    if missing:
        raise ValueError(f"SQLite source is missing required tables: {', '.join(missing)}")
    if not apply:
        return {
            "status": "dry-run",
            "source": fingerprint,
            "skippedTables": sorted(SKIP_TABLES),
            "tables": {table: {"source": count} for table, count in fingerprint["tables"].items()},
            "tableDetails": fingerprint.get("tableDetails", {}),
            "leaseConversion": {
                "activeRowsSkipped": _table_count(fingerprint, "refresh_leases"),
                "fenceRowsImported": _table_count(fingerprint, "refresh_lease_fences"),
            },
        }
    engine = create_database_engine(DatabaseSettings(url=database_url))
    create_schema(engine)
    result: dict[str, Any] = {
        "status": "applied" if apply else "dry-run",
        "source": fingerprint,
        "skippedTables": sorted(SKIP_TABLES),
        "tables": {},
        "tableDetails": fingerprint.get("tableDetails", {}),
        "leaseConversion": {"activeRowsSkipped": 0, "fenceRowsImported": 0},
    }
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as sqlite_connection:
            sqlite_connection.row_factory = sqlite3.Row
            with engine.begin() as target:
                # Active ownership is intentionally never imported.  Count it
                # for the operator so the resulting report records the
                # lease-expiry conversion explicitly.
                lease_rows = sqlite_connection.execute(
                    "SELECT * FROM refresh_leases"
                ).fetchall() if "refresh_leases" in fingerprint["tables"] else []
                result["leaseConversion"]["activeRowsSkipped"] = len(lease_rows)

                for table in IMPORT_TABLES:
                    available = {
                        row[0]
                        for row in sqlite_connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
                        )
                    }
                    if not available:
                        result["tables"][table] = {
                            "source": 0,
                            "target": 0,
                            "status": "absent-optional",
                        }
                        continue
                    rows = sqlite_connection.execute(f"SELECT * FROM {table}").fetchall()
                    if not rows:
                        result["tables"][table] = {"source": 0, "imported": 0}
                        continue
                    columns = [
                        column for column in rows[0].keys() if column not in {"event_id", "id"}
                    ]
                    assignments = ", ".join(f":{column}" for column in columns)
                    names = ", ".join(columns)
                    statement = text(
                        f"INSERT INTO {table} ({names}) VALUES ({assignments}) ON CONFLICT DO NOTHING"
                    )
                    # Identity-backed audit/event tables do not have a stable
                    # primary key in the SQLite source (the source ``id`` is
                    # intentionally omitted above).  ``ON CONFLICT DO
                    # NOTHING`` therefore cannot make a retry idempotent: a
                    # second import would append the same logical event with a
                    # fresh PostgreSQL identity.  Read existing logical rows
                    # and only insert source rows that are not already present.
                    existing_rows = target.execute(
                        text(f"SELECT {names} FROM {table}")
                    ).mappings().all()
                    existing_keys = Counter(_row_key(row, columns) for row in existing_rows)
                    payload = []
                    for row in rows:
                        key = _row_key(row, columns)
                        if existing_keys[key]:
                            existing_keys[key] -= 1
                            continue
                        payload.append({column: row[column] for column in columns})
                    if payload:
                        target.execute(statement, payload)
                    count = target.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                    source_checksum = _rows_checksum(rows, columns)
                    target_rows = target.execute(
                        text(f"SELECT {names} FROM {table}")
                    ).mappings().all()
                    target_checksum = _rows_checksum(target_rows, columns)
                    target_count = int(count)
                    # Verification is deliberately a multiset-subset check.
                    # A retry may have audit rows created by the previous
                    # import (or unrelated newer rows), but every source row
                    # must still be present byte-for-byte after normalization.
                    verified = _rows_subset(rows, target_rows, columns)
                    result["tables"][table] = {
                        "source": len(rows),
                        "target": target_count,
                        "sourceChecksum": source_checksum,
                        "targetChecksum": target_checksum,
                        "verified": verified,
                    }
                    if not verified:
                        raise ValueError(
                            f"import verification failed for table {table}: checksum mismatch"
                        )
                    if table == "refresh_lease_fences":
                        result["leaseConversion"]["fenceRowsImported"] = len(rows)
                    # A checksum mismatch already implies a content mismatch,
                    # but retain explicit count/range/date checks in the report
                    # for operator-facing verification and easier diagnostics.
                    source_detail = fingerprint.get("tableDetails", {}).get(table, {})
                    comparable_keys = [
                        key for key in source_detail.get("primaryKey", []) if key in columns
                    ]
                    target_detail = _table_details(
                        target_rows,
                        columns,
                        primary_keys=comparable_keys,
                    )
                    result["tables"][table]["targetDetails"] = target_detail
                    # Keep strict range/coverage checks for a first import into
                    # an empty table.  On retries, target-only audit rows are
                    # expected and exact target metadata would reject a safe,
                    # idempotent operation; the subset checksum above remains
                    # the authoritative content check.
                    if target_count == len(rows):
                        expected_ranges = {
                            key: source_detail.get("primaryKeyRange", {}).get(key)
                            for key in comparable_keys
                        }
                        if target_detail.get("primaryKeyRange", {}) != expected_ranges:
                            raise ValueError(
                                f"import verification failed for table {table}: primaryKeyRange mismatch"
                            )
                        if target_detail.get("dateCoverage", {}) != source_detail.get("dateCoverage", {}):
                            raise ValueError(
                                f"import verification failed for table {table}: dateCoverage mismatch"
                            )
                # Preserve an auditable fencing event for every active SQLite
                # owner without carrying ownership into PostgreSQL.  The
                # operation key makes retries idempotent.
                for lease in lease_rows:
                    exists = target.execute(
                        text(
                            "SELECT 1 FROM lease_fence_events WHERE dataset=:dataset "
                            "AND as_of=:as_of AND generation=:generation "
                            "AND operation='sqlite-import-expire' LIMIT 1"
                        ),
                        {
                            "dataset": lease["dataset"],
                            "as_of": lease["as_of"],
                            "generation": int(lease["generation"] or 0),
                        },
                    ).first()
                    if exists:
                        continue
                    target.execute(
                        text(
                            "INSERT INTO lease_fence_events"
                            "(dataset, as_of, owner, generation, token, operation, reason, created_at)"
                            " VALUES (:dataset, :as_of, :owner, :generation, :token,"
                            " 'sqlite-import-expire', :reason, CURRENT_TIMESTAMP)"
                        ),
                        {
                            "dataset": lease["dataset"],
                            "as_of": lease["as_of"],
                            "owner": lease["owner"],
                            "generation": int(lease["generation"] or 0),
                            "token": "[redacted]",
                            "reason": "active SQLite lease expired during PostgreSQL import",
                        },
                    )
    finally:
        engine.dispose()
    return result


def _table_count(fingerprint: dict[str, Any], table: str) -> int:
    value = fingerprint.get("tables", {}).get(table, 0)
    return int(value.get("count", 0) if isinstance(value, dict) else value)


def _rows_checksum(rows: Any, columns: list[str]) -> str:
    """Stable checksum over imported columns, independent of DB row ordering."""
    values = []
    for row in rows:
        values.append({column: _normalize_cell(column, row[column]) for column in columns})
    # PostgreSQL does not guarantee row order unless an ORDER BY is supplied;
    # sorting canonical JSON rows keeps source/target checksums deterministic.
    values.sort(key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")))
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_key(row: Any, columns: list[str]) -> str:
    """Canonical logical-row key used to deduplicate identity-backed tables."""

    value = {
        column: _normalize_cell(column, row[column])
        for column in columns
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _rows_subset(source_rows: Any, target_rows: Any, columns: list[str]) -> bool:
    """Return whether every source logical row exists in the target multiset."""

    available = Counter(_row_key(row, columns) for row in target_rows)
    for row in source_rows:
        key = _row_key(row, columns)
        if not available[key]:
            return False
        available[key] -= 1
    return True


def _table_details(rows: Any, columns: list[str], *, primary_keys: list[str]) -> dict[str, Any]:
    """Return operator-facing count, key-range and date coverage metadata."""
    date_columns = [
        column
        for column in columns
        if column in {"as_of", "actual_as_of", "source_as_of", "target_as_of"}
    ]
    primary_key_range = {}
    for column in primary_keys:
        values = [row[column] for row in rows if row[column] is not None]
        if values:
            try:
                lower, upper = min(values), max(values)
            except TypeError:
                normalized = [str(value) for value in values]
                lower, upper = min(normalized), max(normalized)
            primary_key_range[column] = [str(lower), str(upper)]
    return {
        "count": len(rows),
        "primaryKey": list(primary_keys),
        "primaryKeyRange": primary_key_range,
        "dateCoverage": {
            column: sorted({str(row[column]) for row in rows if row[column] is not None})
            for column in date_columns
        },
        "checksum": _rows_checksum(rows, columns),
    }


def _normalize_cell(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column.endswith("_json") or column in {"plan_json", "before_image_json", "result_json", "payload_json"}:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
    if column in {"settled", "is_session", "complete", "eligible", "is_st", "touched_limit_up", "closed_limit_up", "failed_limit_up"}:
        return bool(value)
    if column in {"as_of", "actual_as_of", "source_as_of", "target_as_of", "listing_date"}:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
    if column.endswith("_at") or column in {"created_at", "updated_at", "changed_at", "fetched_at"}:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        try:
            return datetime.fromisoformat(str(value)).isoformat()
        except ValueError:
            return str(value)
    return str(value) if not isinstance(value, (str, int, float, bool, list, dict)) else value
