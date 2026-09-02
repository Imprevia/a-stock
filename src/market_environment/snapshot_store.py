"""Durable, exact-date storage for market environment dataset snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_SOFT_TTL_SECONDS = 30
CacheState = Literal["fresh", "stale", "missing"]


class SnapshotIntegrityError(RuntimeError):
    """Raised when a stored payload no longer matches its checksum."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_snapshot_path() -> Path:
    configured = os.getenv("MARKET_ENVIRONMENT_SNAPSHOT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return root / ".artifacts" / "market-environment" / "snapshots.sqlite3"


def persistent_cache_enabled() -> bool:
    return os.getenv("MARKET_ENVIRONMENT_PERSISTENT_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SnapshotRecord:
    dataset: str
    as_of: date
    payload: dict[str, Any]
    source: str
    status: str
    observations: int
    warnings: tuple[str, ...]
    fetched_at: datetime
    settled: bool = False
    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    checksum: str = ""
    refresh_warning: str | None = None

    def normalized(self) -> "SnapshotRecord":
        fetched_at = self.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        else:
            fetched_at = fetched_at.astimezone(timezone.utc)
        checksum = self.checksum or payload_checksum(self.payload)
        return replace(self, fetched_at=fetched_at, checksum=checksum)


class SnapshotStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_snapshot_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshot_entries (
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observations INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    settled INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    refresh_warning TEXT,
                    PRIMARY KEY (dataset, as_of)
                );

                CREATE TABLE IF NOT EXISTS refresh_leases (
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (dataset, as_of)
                );

                CREATE TABLE IF NOT EXISTS refresh_runs (
                    run_id TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, dataset)
                );
                """
            )

    def put(self, record: SnapshotRecord) -> SnapshotRecord:
        value = record.normalized()
        if value.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported snapshot schema version: {value.schema_version}")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO snapshot_entries (
                    dataset, as_of, payload_json, source, status, observations,
                    warnings_json, fetched_at, settled, schema_version, checksum,
                    refresh_warning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    status = excluded.status,
                    observations = excluded.observations,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at,
                    settled = excluded.settled,
                    schema_version = excluded.schema_version,
                    checksum = excluded.checksum,
                    refresh_warning = excluded.refresh_warning
                """,
                (
                    value.dataset,
                    value.as_of.isoformat(),
                    canonical_json(value.payload),
                    value.source,
                    value.status,
                    value.observations,
                    canonical_json(list(value.warnings)),
                    value.fetched_at.isoformat(),
                    int(value.settled),
                    value.schema_version,
                    value.checksum,
                    value.refresh_warning,
                ),
            )
        return value

    def get(self, dataset: str, as_of: date) -> SnapshotRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM snapshot_entries WHERE dataset = ? AND as_of = ?",
                (dataset, as_of.isoformat()),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        checksum = payload_checksum(payload)
        if checksum != row["checksum"]:
            raise SnapshotIntegrityError(f"snapshot checksum mismatch: {dataset}/{as_of.isoformat()}")
        return SnapshotRecord(
            dataset=row["dataset"],
            as_of=date.fromisoformat(row["as_of"]),
            payload=payload,
            source=row["source"],
            status=row["status"],
            observations=int(row["observations"]),
            warnings=tuple(json.loads(row["warnings_json"])),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            settled=bool(row["settled"]),
            schema_version=int(row["schema_version"]),
            checksum=row["checksum"],
            refresh_warning=row["refresh_warning"],
        )

    def set_refresh_warning(self, dataset: str, as_of: date, warning: str | None) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE snapshot_entries SET refresh_warning = ? WHERE dataset = ? AND as_of = ?",
                (warning, dataset, as_of.isoformat()),
            )
        return cursor.rowcount > 0

    def acquire_lease(
        self,
        dataset: str,
        as_of: date,
        owner: str,
        *,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        current = (now or utc_now()).astimezone(timezone.utc)
        expires_at = current + timedelta(seconds=lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner, expires_at FROM refresh_leases WHERE dataset = ? AND as_of = ?",
                (dataset, as_of.isoformat()),
            ).fetchone()
            if row is not None:
                existing_expiry = datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc)
                if existing_expiry > current and row["owner"] != owner:
                    connection.rollback()
                    return False
            connection.execute(
                """
                INSERT INTO refresh_leases (dataset, as_of, owner, acquired_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    owner = excluded.owner,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                """,
                (dataset, as_of.isoformat(), owner, current.isoformat(), expires_at.isoformat()),
            )
            connection.commit()
            return True
        finally:
            connection.close()

    def release_lease(self, dataset: str, as_of: date, owner: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM refresh_leases WHERE dataset = ? AND as_of = ? AND owner = ?",
                (dataset, as_of.isoformat(), owner),
            )
        return cursor.rowcount > 0

    def has_active_lease(self, dataset: str, as_of: date, *, now: datetime | None = None) -> bool:
        current = (now or utc_now()).astimezone(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at FROM refresh_leases WHERE dataset = ? AND as_of = ?",
                (dataset, as_of.isoformat()),
            ).fetchone()
        return row is not None and datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc) > current

    def prune(self, before: date, *, now: datetime | None = None) -> int:
        current = (now or utc_now()).astimezone(timezone.utc)
        with self._connect() as connection:
            connection.execute("DELETE FROM refresh_leases WHERE expires_at <= ?", (current.isoformat(),))
            cursor = connection.execute(
                """
                DELETE FROM snapshot_entries
                WHERE as_of < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM refresh_leases
                      WHERE refresh_leases.dataset = snapshot_entries.dataset
                        AND refresh_leases.as_of = snapshot_entries.as_of
                        AND refresh_leases.expires_at > ?
                  )
                """,
                (before.isoformat(), current.isoformat()),
            )
        return cursor.rowcount

    def record_refresh_result(
        self,
        run_id: str,
        dataset: str,
        as_of: date,
        result: dict[str, Any],
        *,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = (created_at or utc_now()).astimezone(timezone.utc)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO refresh_runs (run_id, dataset, as_of, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, dataset, as_of.isoformat(), canonical_json(result), timestamp.isoformat()),
            )


def cache_state(
    record: SnapshotRecord | None,
    *,
    now: datetime | None = None,
    soft_ttl_seconds: float = DEFAULT_SOFT_TTL_SECONDS,
) -> CacheState:
    if record is None:
        return "missing"
    if record.settled:
        return "fresh"
    current = (now or utc_now()).astimezone(timezone.utc)
    fetched_at = record.fetched_at.astimezone(timezone.utc)
    return "fresh" if (current - fetched_at).total_seconds() < soft_ttl_seconds else "stale"
