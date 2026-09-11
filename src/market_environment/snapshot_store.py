"""Durable, exact-date storage for market environment dataset snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .limit_facts import (
    LIMIT_FACT_SCHEMA_VERSION,
    LimitSecurityFactRecord,
    fact_row_checksum,
    limit_dataset_checksum,
)

SNAPSHOT_SCHEMA_VERSION = 1
TRADING_SESSION_SCHEMA_VERSION = 2
STORAGE_SCHEMA_VERSION = 4
LIMIT_DETAIL_CHECKSUM_KEY = "_detailDatasetChecksum"
MATERIALIZED_COMPONENT_REVISION_KEY = "_componentRevision"
DEFAULT_SOFT_TTL_SECONDS = 30
CacheState = Literal["fresh", "stale", "missing"]
CollectionRunStatus = Literal["queued", "collecting", "success", "partial", "failed"]
CollectionTaskStatus = Literal[
    "queued",
    "collecting",
    "success",
    "partial",
    "failed-retained",
    "failed-missing",
    "busy",
]


class SnapshotIntegrityError(RuntimeError):
    """Raised when a stored payload no longer matches its checksum."""


@dataclass(frozen=True)
class LeaseToken:
    """Opaque fencing credential returned for a dataset/date lease."""

    dataset: str
    as_of: date
    owner: str
    generation: int
    token: str
    expires_at: datetime

    def __bool__(self) -> bool:
        # Preserve the historical ``if acquire_lease(...)`` call contract.
        return True


class LeaseFenceError(RuntimeError):
    """Raised when a write is attempted with a stale or lost lease token."""

    def __init__(self, message: str, *, lease: LeaseToken, operation: str) -> None:
        super().__init__(message)
        self.lease = lease
        self.operation = operation


class MaterializedAggregateConflict(RuntimeError):
    """Raised when aggregate inputs changed after they were read."""


@dataclass(frozen=True)
class TradingSessionRecord:
    """An exact market session and its evidence-backed predecessor."""

    as_of: date
    previous_as_of: date | None
    is_session: bool
    source: str
    schema_version: int = TRADING_SESSION_SCHEMA_VERSION
    checksum: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    actual_as_of: date | None = None
    warnings: tuple[str, ...] = ()

    def logical_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "previous_as_of": self.previous_as_of.isoformat() if self.previous_as_of else None,
            "actual_as_of": self.actual_as_of.isoformat() if self.actual_as_of else None,
            "is_session": self.is_session,
            "source": self.source,
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
        }

    def normalized(self) -> "TradingSessionRecord":
        fetched_at = self.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        else:
            fetched_at = fetched_at.astimezone(timezone.utc)
        value = replace(self, fetched_at=fetched_at)
        checksum = value.checksum or payload_checksum(value.logical_dict())
        return replace(value, checksum=checksum)


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


def lease_token_fingerprint(token: str) -> str:
    """Return a non-reversible identifier suitable for lease audit records."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


@dataclass(frozen=True)
class CollectionRunRecord:
    run_id: str
    as_of: date
    status: CollectionRunStatus
    requested_datasets: tuple[str, ...]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class CollectionTaskRecord:
    task_id: str
    run_id: str
    dataset: str
    as_of: date
    status: CollectionTaskStatus
    source: str = "none"
    observations: int = 0
    warning: str | None = None
    timings: dict[str, float] | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    settled: bool = False


@dataclass(frozen=True)
class CoreIndexResultRecord:
    task_id: str
    code: str
    name: str
    status: CollectionTaskStatus
    source: str = "none"
    observations: int = 0
    warning: str | None = None
    duration_ms: float | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class MaterializedAggregateRecord:
    as_of: date
    payload: dict[str, Any]
    generated_at: datetime
    checksum: str = ""

    def normalized(self) -> "MaterializedAggregateRecord":
        generated_at = self.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        else:
            generated_at = generated_at.astimezone(timezone.utc)
        return replace(
            self,
            generated_at=generated_at,
            checksum=self.checksum or payload_checksum(self.payload),
        )


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
            connection.execute("PRAGMA foreign_keys = ON")
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > STORAGE_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported storage schema version: {current_version} > {STORAGE_SCHEMA_VERSION}"
                )
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    checksum TEXT NOT NULL
                );

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
                    generation INTEGER NOT NULL DEFAULT 0,
                    token TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (dataset, as_of)
                );

                -- Kept independently of the active lease row so a deleted or
                -- expired lease can never reuse an earlier fencing generation.
                CREATE TABLE IF NOT EXISTS refresh_lease_fences (
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset, as_of)
                );

                CREATE TABLE IF NOT EXISTS lease_fence_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS refresh_runs (
                    run_id TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, dataset)
                );

                CREATE INDEX IF NOT EXISTS refresh_runs_dataset_date_idx
                    ON refresh_runs(dataset, as_of);

                CREATE TABLE IF NOT EXISTS collection_runs (
                    run_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_datasets_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS collection_tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'none',
                    observations INTEGER NOT NULL DEFAULT 0,
                    warning TEXT,
                    timings_json TEXT NOT NULL DEFAULT '{}',
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms REAL,
                    settled INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (run_id, dataset),
                    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS collection_tasks_dataset_date_idx
                    ON collection_tasks(dataset, as_of, queued_at DESC);

                CREATE TABLE IF NOT EXISTS core_index_results (
                    task_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'none',
                    observations INTEGER NOT NULL DEFAULT 0,
                    warning TEXT,
                    duration_ms REAL,
                    payload_json TEXT,
                    PRIMARY KEY (task_id, code),
                    FOREIGN KEY (task_id) REFERENCES collection_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS materialized_market_environment (
                    as_of TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    checksum TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_sessions (
                    as_of TEXT PRIMARY KEY,
                    previous_as_of TEXT,
                    actual_as_of TEXT,
                    is_session INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    warnings_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS limit_security_datasets (
                    as_of TEXT PRIMARY KEY,
                    actual_as_of TEXT,
                    source TEXT NOT NULL,
                    source_revision TEXT,
                    rule_version TEXT,
                    schema_version INTEGER NOT NULL,
                    complete INTEGER NOT NULL,
                    excluded INTEGER NOT NULL DEFAULT 0,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    dataset_checksum TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS limit_security_facts (
                    as_of TEXT NOT NULL,
                    actual_as_of TEXT,
                    security_id TEXT NOT NULL,
                    pool_type TEXT NOT NULL,
                    code TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    name TEXT,
                    board TEXT,
                    is_st INTEGER,
                    listing_date TEXT,
                    listing_days INTEGER,
                    limit_regime TEXT,
                    close_price REAL,
                    previous_close REAL,
                    change_pct REAL,
                    touched_limit_up INTEGER,
                    closed_limit_up INTEGER,
                    failed_limit_up INTEGER,
                    streak_days INTEGER,
                    eligible INTEGER NOT NULL,
                    invalid_reason TEXT,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    row_checksum TEXT NOT NULL,
                    dataset_checksum TEXT,
                    PRIMARY KEY (as_of, security_id, pool_type)
                );

                CREATE INDEX IF NOT EXISTS limit_security_facts_date_security_idx
                    ON limit_security_facts(as_of, security_id);
                CREATE INDEX IF NOT EXISTS limit_security_facts_eligible_idx
                    ON limit_security_facts(as_of, eligible, closed_limit_up);
                CREATE INDEX IF NOT EXISTS limit_security_facts_pool_idx
                    ON limit_security_facts(as_of, pool_type);

                CREATE TABLE IF NOT EXISTS materialization_component_versions (
                    component_kind TEXT NOT NULL,
                    dataset TEXT NOT NULL DEFAULT '',
                    as_of TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    PRIMARY KEY (component_kind, dataset, as_of)
                );

                CREATE TRIGGER IF NOT EXISTS snapshot_materialization_version_insert
                AFTER INSERT ON snapshot_entries BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('snapshot', NEW.dataset, NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS snapshot_materialization_version_update
                AFTER UPDATE ON snapshot_entries BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('snapshot', NEW.dataset, NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS snapshot_materialization_version_delete
                AFTER DELETE ON snapshot_entries BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('snapshot', OLD.dataset, OLD.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;

                CREATE TRIGGER IF NOT EXISTS session_materialization_version_insert
                AFTER INSERT ON trading_sessions BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('trading_session', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS session_materialization_version_update
                AFTER UPDATE ON trading_sessions BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('trading_session', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS session_materialization_version_delete
                AFTER DELETE ON trading_sessions BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('trading_session', '', OLD.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;

                CREATE TRIGGER IF NOT EXISTS limit_dataset_materialization_version_insert
                AFTER INSERT ON limit_security_datasets BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_dataset', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS limit_dataset_materialization_version_update
                AFTER UPDATE ON limit_security_datasets BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_dataset', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS limit_dataset_materialization_version_delete
                AFTER DELETE ON limit_security_datasets BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_dataset', '', OLD.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;

                CREATE TRIGGER IF NOT EXISTS limit_facts_materialization_version_insert
                AFTER INSERT ON limit_security_facts BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_facts', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS limit_facts_materialization_version_update
                AFTER UPDATE ON limit_security_facts BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_facts', '', NEW.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                CREATE TRIGGER IF NOT EXISTS limit_facts_materialization_version_delete
                AFTER DELETE ON limit_security_facts BEGIN
                    INSERT INTO materialization_component_versions(component_kind, dataset, as_of, revision)
                    VALUES ('limit_facts', '', OLD.as_of, 1)
                    ON CONFLICT(component_kind, dataset, as_of) DO UPDATE SET revision = revision + 1;
                END;
                COMMIT;
                """
            )
            # Older v2 databases have the original five-column lease table.
            # Additive ALTERs keep those PVCs readable without changing the
            # storage schema version.
            lease_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(refresh_leases)").fetchall()
            }
            if "generation" not in lease_columns:
                connection.execute(
                    "ALTER TABLE refresh_leases ADD COLUMN generation INTEGER NOT NULL DEFAULT 0"
                )
            if "token" not in lease_columns:
                connection.execute(
                    "ALTER TABLE refresh_leases ADD COLUMN token TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO refresh_lease_fences(dataset, as_of, generation, token, updated_at)
                SELECT dataset, as_of, CASE WHEN generation > 0 THEN generation ELSE 1 END,
                       '[redacted]', acquired_at
                FROM refresh_leases
                """
            )
            connection.execute("UPDATE refresh_lease_fences SET token = '[redacted]'")
            connection.execute(
                """
                UPDATE lease_fence_events SET token = '[redacted-legacy]'
                WHERE length(token) != 64 OR token GLOB '*[^0-9a-f]*'
                """
            )
            connection.execute(
                """
                UPDATE refresh_leases
                SET generation = CASE WHEN generation > 0 THEN generation ELSE 1 END,
                    token = CASE WHEN token != '' THEN token ELSE owner END
                WHERE generation = 0 OR token = ''
                """
            )
            now = utc_now().isoformat()
            migration_checksum = payload_checksum(
                {"version": 2, "tables": ["trading_sessions", "limit_security_facts"]}
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (1, "legacy-snapshot-schema", now, payload_checksum({"version": 1, "name": "legacy-snapshot-schema"})),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (2, "add-limit-security-facts", now, migration_checksum),
            )
            fencing_checksum = payload_checksum(
                {
                    "version": 3,
                    "tables": ["refresh_leases", "refresh_lease_fences", "lease_fence_events"],
                }
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (3, "add-refresh-lease-fencing", now, fencing_checksum),
            )
            materialization_checksum = payload_checksum(
                {
                    "version": 4,
                    "tables": ["materialization_component_versions"],
                    "triggers": [
                        "snapshot_materialization_version",
                        "session_materialization_version",
                        "limit_dataset_materialization_version",
                        "limit_facts_materialization_version",
                    ],
                }
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (4, "add-materialization-component-revisions", now, materialization_checksum),
            )
            if current_version != STORAGE_SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version = {STORAGE_SCHEMA_VERSION}")

    @staticmethod
    def _normalized_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _resolve_lease_argument(
        lease: LeaseToken | None,
        lease_token: LeaseToken | None,
    ) -> LeaseToken | None:
        if lease is not None and lease_token is not None and lease != lease_token:
            raise ValueError("lease and lease_token arguments must identify the same token")
        return lease if lease is not None else lease_token

    def _assert_lease(
        self,
        connection: sqlite3.Connection,
        lease: LeaseToken | None,
        *,
        operation: str,
        now: datetime | Callable[[], datetime] | None = None,
        expected_dataset: str | None = None,
        expected_as_of: date | None = None,
    ) -> None:
        if lease is None:
            return
        current_value = now() if callable(now) else now
        current = (current_value or utc_now()).astimezone(timezone.utc)
        if (
            (expected_dataset is not None and lease.dataset != expected_dataset)
            or (expected_as_of is not None and lease.as_of != expected_as_of)
        ):
            raise LeaseFenceError(
                "lease fenced: credential dataset/date does not match the write",
                lease=lease,
                operation=operation,
            )
        row = connection.execute(
            """
            SELECT owner, generation, token, expires_at
            FROM refresh_leases
            WHERE dataset = ? AND as_of = ?
            """,
            (lease.dataset, lease.as_of.isoformat()),
        ).fetchone()
        if (
            row is None
            or row["owner"] != lease.owner
            or int(row["generation"]) != lease.generation
            or row["token"] != lease.token
            or datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc) <= current
        ):
            raise LeaseFenceError(
                "lease fenced: owner/token differs or lease has expired",
                lease=lease,
                operation=operation,
            )

    @staticmethod
    def _materialization_revision(connection: sqlite3.Connection, as_of: date) -> str:
        as_of_value = as_of.isoformat()
        state = {
            "snapshots": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT dataset, as_of, source, status, observations, warnings_json,
                           fetched_at, settled, schema_version, checksum, refresh_warning
                    FROM snapshot_entries
                    WHERE as_of = ?
                       OR (dataset = 'breadth' AND as_of < ?)
                       OR (
                           dataset = 'limits'
                           AND as_of = (
                               SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                           )
                       )
                    ORDER BY dataset, as_of
                    """,
                    (as_of_value, as_of_value, as_of_value),
                ).fetchall()
            ],
            "tradingSessions": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT as_of, previous_as_of, actual_as_of, is_session, source,
                           schema_version, checksum, warnings_json
                    FROM trading_sessions
                    WHERE as_of = ?
                       OR as_of = (
                           SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                       )
                    ORDER BY as_of
                    """,
                    (as_of_value, as_of_value),
                ).fetchall()
            ],
            "limitDatasets": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT as_of, actual_as_of, source, source_revision, rule_version,
                           schema_version, complete, excluded, warnings_json, dataset_checksum
                    FROM limit_security_datasets
                    WHERE as_of = ?
                       OR as_of = (
                           SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                       )
                    ORDER BY as_of
                    """,
                    (as_of_value, as_of_value),
                ).fetchall()
            ],
            "componentVersions": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT component_kind, dataset, as_of, revision
                    FROM materialization_component_versions
                    WHERE (
                            component_kind = 'snapshot'
                            AND (
                                as_of = ?
                                OR (dataset = 'breadth' AND as_of < ?)
                                OR (
                                    dataset = 'limits'
                                    AND as_of = (
                                        SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                                    )
                                )
                            )
                          )
                       OR (
                            component_kind = 'trading_session'
                            AND (
                                as_of = ?
                                OR as_of = (
                                    SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                                )
                            )
                          )
                       OR (
                            component_kind IN ('limit_dataset', 'limit_facts')
                            AND (
                                as_of = ?
                                OR as_of = (
                                    SELECT previous_as_of FROM trading_sessions WHERE as_of = ?
                                )
                            )
                          )
                    ORDER BY component_kind, dataset, as_of
                    """,
                    (
                        as_of_value,
                        as_of_value,
                        as_of_value,
                        as_of_value,
                        as_of_value,
                        as_of_value,
                        as_of_value,
                    ),
                ).fetchall()
            ],
        }
        return payload_checksum(state)

    def materialization_revision(self, as_of: date) -> str:
        """Return a deterministic revision for every persisted aggregate input."""

        with self._connect() as connection:
            connection.execute("BEGIN")
            return self._materialization_revision(connection, as_of)

    def _record_lease_fence_event(self, error: LeaseFenceError) -> None:
        lease = error.lease
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO lease_fence_events(
                    dataset, as_of, owner, generation, token, operation, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.dataset,
                    lease.as_of.isoformat(),
                    lease.owner,
                    lease.generation,
                    lease_token_fingerprint(lease.token),
                    error.operation,
                    str(error),
                    utc_now().isoformat(),
                ),
            )

    def list_lease_fence_events(self, dataset: str | None = None, as_of: date | None = None) -> tuple[dict[str, Any], ...]:
        clauses: list[str] = []
        values: list[Any] = []
        if dataset is not None:
            clauses.append("dataset = ?")
            values.append(dataset)
        if as_of is not None:
            clauses.append("as_of = ?")
            values.append(as_of.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM lease_fence_events {where} ORDER BY event_id",
                values,
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            event = dict(row)
            event["token_fingerprint"] = event.pop("token")
            events.append(event)
        return tuple(events)

    def put(
        self,
        record: SnapshotRecord,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> SnapshotRecord:
        value = record.normalized()
        if value.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported snapshot schema version: {value.schema_version}")
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="snapshot",
                    now=now,
                    expected_dataset=value.dataset,
                    expected_as_of=value.as_of,
                )
                self._write_snapshot(connection, value)
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return value

    @staticmethod
    def _write_snapshot(connection: sqlite3.Connection, value: SnapshotRecord) -> None:
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

    def list_snapshot_dates(self, dataset: str, *, through: date | None = None) -> tuple[date, ...]:
        """Return exact dates with persisted snapshots, never calendar-fill gaps."""
        clauses = ["dataset = ?"]
        values: list[Any] = [dataset]
        if through is not None:
            clauses.append("as_of <= ?")
            values.append(through.isoformat())
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT as_of FROM snapshot_entries WHERE {' AND '.join(clauses)} ORDER BY as_of DESC",
                values,
            ).fetchall()
        return tuple(date.fromisoformat(row["as_of"]) for row in rows)

    def storage_schema_version(self) -> int:
        """Return the additive storage schema version recorded by SQLite."""

        with self._connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def migration_versions(self) -> tuple[int, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return tuple(int(row[0]) for row in rows)

    def put_trading_session(
        self,
        record: TradingSessionRecord,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> TradingSessionRecord:
        value = record.normalized()
        if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported trading session schema version: {value.schema_version}")
        if value.actual_as_of is not None and value.actual_as_of != value.as_of:
            raise ValueError("trading session actual_as_of must match as_of")
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="trading_session",
                    now=now,
                    expected_dataset="core",
                    expected_as_of=value.as_of,
                )
                connection.execute(
                """
                INSERT INTO trading_sessions (
                    as_of, previous_as_of, actual_as_of, is_session, source,
                    schema_version, checksum, fetched_at, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(as_of) DO UPDATE SET
                    previous_as_of = excluded.previous_as_of,
                    actual_as_of = excluded.actual_as_of,
                    is_session = excluded.is_session,
                    source = excluded.source,
                    schema_version = excluded.schema_version,
                    checksum = excluded.checksum,
                    fetched_at = excluded.fetched_at,
                    warnings_json = excluded.warnings_json
                """,
                (
                    value.as_of.isoformat(),
                    value.previous_as_of.isoformat() if value.previous_as_of else None,
                    value.actual_as_of.isoformat() if value.actual_as_of else None,
                    int(value.is_session),
                    value.source,
                    value.schema_version,
                    value.checksum,
                    value.fetched_at.isoformat(),
                    canonical_json(list(value.warnings)),
                ),
                )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return value

    def get_trading_session(self, as_of: date) -> TradingSessionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trading_sessions WHERE as_of = ?", (as_of.isoformat(),)
            ).fetchone()
        if row is None:
            return None
        value = TradingSessionRecord(
            as_of=date.fromisoformat(row["as_of"]),
            previous_as_of=date.fromisoformat(row["previous_as_of"]) if row["previous_as_of"] else None,
            actual_as_of=date.fromisoformat(row["actual_as_of"]) if row["actual_as_of"] else None,
            is_session=bool(row["is_session"]),
            source=row["source"],
            schema_version=int(row["schema_version"]),
            checksum=row["checksum"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            warnings=tuple(json.loads(row["warnings_json"])),
        )
        if value.schema_version != TRADING_SESSION_SCHEMA_VERSION:
            raise SnapshotIntegrityError(f"unsupported trading session schema version: {as_of.isoformat()}")
        if payload_checksum(value.logical_dict()) != value.checksum:
            raise SnapshotIntegrityError(f"trading session checksum mismatch: {as_of.isoformat()}")
        return value

    def list_trading_sessions(self) -> tuple[TradingSessionRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT as_of FROM trading_sessions ORDER BY as_of").fetchall()
        return tuple(self.get_trading_session(date.fromisoformat(row[0])) for row in rows if row is not None)  # type: ignore[misc]

    def put_limit_security_facts(
        self,
        as_of: date,
        facts: tuple[LimitSecurityFactRecord, ...] | list[LimitSecurityFactRecord],
        *,
        actual_as_of: date | None = None,
        source: str | None = None,
        source_revision: str | None = None,
        rule_version: str | None = None,
        complete: bool | None = None,
        warnings: tuple[str, ...] | list[str] = (),
        dataset_checksum: str | None = None,
        fetched_at: datetime | None = None,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> str:
        """Atomically upsert normalized rows and their dataset manifest.

        The composite primary key makes repeated writes idempotent.  Existing
        rows are never removed by this additive write path; a changed set has a
        different manifest checksum and is therefore detectable on read.
        """

        values = tuple(fact.normalized() for fact in facts)
        if actual_as_of is None:
            embedded_dates = {fact.actual_as_of for fact in values if fact.actual_as_of is not None}
            if len(embedded_dates) == 1:
                actual_as_of = next(iter(embedded_dates))
        if actual_as_of is not None:
            values = tuple(
                replace(fact, actual_as_of=actual_as_of, row_checksum="").normalized()
                if fact.actual_as_of is None
                else fact
                for fact in values
            )
        if actual_as_of is not None and actual_as_of != as_of:
            raise ValueError("limit facts actual_as_of must match as_of")
        sources = {fact.source for fact in values}
        if len(sources) > 1:
            raise ValueError("all limit facts must use one manifest source")
        for fact in values:
            if fact.as_of != as_of:
                raise ValueError("all limit facts must use the requested as_of")
            if fact.actual_as_of != actual_as_of:
                raise ValueError("all limit facts must use the manifest actual_as_of")
            if source is not None and fact.source != source:
                raise ValueError("all limit facts must use the manifest source")
            if fact.schema_version != LIMIT_FACT_SCHEMA_VERSION:
                raise ValueError(f"unsupported limit fact schema version: {fact.schema_version}")
            if fact.eligible and (not fact.security_id or not fact.code or not fact.exchange):
                raise ValueError("eligible limit facts require exchange-qualified identity")
            if fact.row_checksum != fact_row_checksum(fact):
                raise ValueError(f"invalid row checksum: {fact.security_id}/{fact.pool_type}")
        effective_warnings = tuple(str(item) for item in warnings)
        # A malformed caller may provide the same primary key twice.  Keep one
        # deterministic quarantined row so the persisted dataset hash cannot
        # describe rows SQLite silently collapsed via ON CONFLICT.
        keyed: dict[tuple[str, str], LimitSecurityFactRecord] = {}
        duplicate_keys: set[tuple[str, str]] = set()
        for fact in values:
            key = (fact.security_id, fact.pool_type)
            if key in keyed:
                duplicate_keys.add(key)
            else:
                keyed[key] = fact
        if duplicate_keys:
            effective_warnings = (*effective_warnings, "duplicate security identities quarantined")
            values = tuple(
                replace(
                    fact,
                    eligible=False,
                    invalid_reason="duplicate-security",
                    row_checksum="",
                ).normalized()
                if (fact.security_id, fact.pool_type) in duplicate_keys
                else fact
                for fact in keyed.values()
            )
        effective_source = source or (values[0].source if values else "unknown")
        effective_complete = True if complete is None else bool(complete)
        if actual_as_of is None:
            effective_complete = False
            effective_warnings = (*effective_warnings, "missing actual session date")
        if duplicate_keys:
            effective_complete = False
        effective_excluded = sum(not fact.eligible for fact in values)
        calculated_checksum = limit_dataset_checksum(
            values,
            as_of=as_of,
            actual_as_of=actual_as_of,
            source=effective_source,
            complete=effective_complete,
            warnings=effective_warnings,
            source_revision=source_revision,
            rule_version=rule_version,
            excluded=effective_excluded,
        )
        if dataset_checksum is not None and dataset_checksum != calculated_checksum:
            raise ValueError("dataset checksum does not match normalized facts")
        fetched = self._normalized_datetime(fetched_at or (values[0].fetched_at if values else utc_now()))
        assert fetched is not None
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="limit_security_facts",
                    now=now,
                    expected_dataset="limits",
                    expected_as_of=as_of,
                )
                manifest = connection.execute(
                    "SELECT source_revision, dataset_checksum, complete FROM limit_security_datasets WHERE as_of = ?",
                    (as_of.isoformat(),),
                ).fetchone()
                replacing_incomplete = manifest is not None and not bool(manifest["complete"])
                if (
                    manifest is not None
                    and not replacing_incomplete
                    and manifest["source_revision"] != source_revision
                ):
                    raise ValueError("limit facts source revision mismatch for exact date")
                if (
                    manifest is not None
                    and not replacing_incomplete
                    and manifest["dataset_checksum"] != calculated_checksum
                ):
                    raise ValueError("limit facts dataset checksum changed for exact date/revision")
                if replacing_incomplete:
                    connection.execute(
                        "DELETE FROM limit_security_facts WHERE as_of = ?",
                        (as_of.isoformat(),),
                    )
                connection.execute(
                    """
                    INSERT INTO limit_security_datasets (
                        as_of, actual_as_of, source, source_revision, rule_version,
                        schema_version, complete, excluded, warnings_json,
                        dataset_checksum, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(as_of) DO UPDATE SET
                        actual_as_of = excluded.actual_as_of,
                        source = excluded.source,
                        source_revision = excluded.source_revision,
                        rule_version = excluded.rule_version,
                        schema_version = excluded.schema_version,
                        complete = excluded.complete,
                        excluded = excluded.excluded,
                        warnings_json = excluded.warnings_json,
                        dataset_checksum = excluded.dataset_checksum,
                        fetched_at = excluded.fetched_at
                    """,
                    (
                        as_of.isoformat(),
                        actual_as_of.isoformat() if actual_as_of else None,
                        effective_source,
                        source_revision,
                        rule_version,
                        LIMIT_FACT_SCHEMA_VERSION,
                        int(effective_complete),
                        effective_excluded,
                        canonical_json(list(effective_warnings)),
                        calculated_checksum,
                        fetched.isoformat(),
                    ),
                )
                for fact in values:
                    value = replace(fact, dataset_checksum=calculated_checksum)
                    connection.execute(
                    """
                    INSERT INTO limit_security_facts (
                        as_of, actual_as_of, security_id, pool_type, code, exchange,
                        name, board, is_st, listing_date, listing_days, limit_regime,
                        close_price, previous_close, change_pct, touched_limit_up,
                        closed_limit_up, failed_limit_up, streak_days, eligible,
                        invalid_reason, source, fetched_at, schema_version,
                        row_checksum, dataset_checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(as_of, security_id, pool_type) DO UPDATE SET
                        actual_as_of = excluded.actual_as_of,
                        code = excluded.code,
                        exchange = excluded.exchange,
                        name = excluded.name,
                        board = excluded.board,
                        is_st = excluded.is_st,
                        listing_date = excluded.listing_date,
                        listing_days = excluded.listing_days,
                        limit_regime = excluded.limit_regime,
                        close_price = excluded.close_price,
                        previous_close = excluded.previous_close,
                        change_pct = excluded.change_pct,
                        touched_limit_up = excluded.touched_limit_up,
                        closed_limit_up = excluded.closed_limit_up,
                        failed_limit_up = excluded.failed_limit_up,
                        streak_days = excluded.streak_days,
                        eligible = excluded.eligible,
                        invalid_reason = excluded.invalid_reason,
                        source = excluded.source,
                        fetched_at = excluded.fetched_at,
                        schema_version = excluded.schema_version,
                        row_checksum = excluded.row_checksum,
                        dataset_checksum = excluded.dataset_checksum
                    """,
                    (
                        value.as_of.isoformat(),
                        value.actual_as_of.isoformat() if value.actual_as_of else None,
                        value.security_id,
                        value.pool_type,
                        value.code,
                        value.exchange,
                        value.name,
                        value.board,
                        int(value.is_st) if value.is_st is not None else None,
                        value.listing_date.isoformat() if value.listing_date else None,
                        value.listing_days,
                        value.limit_regime,
                        value.close_price,
                        value.previous_close,
                        value.change_pct,
                        int(value.touched_limit_up) if value.touched_limit_up is not None else None,
                        int(value.closed_limit_up) if value.closed_limit_up is not None else None,
                        int(value.failed_limit_up) if value.failed_limit_up is not None else None,
                        value.streak_days,
                        int(value.eligible),
                        value.invalid_reason,
                        value.source,
                        value.fetched_at.isoformat(),
                        value.schema_version,
                        value.row_checksum,
                        calculated_checksum,
                        ),
                    )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return calculated_checksum

    def put_limit_collection(
        self,
        snapshot: SnapshotRecord,
        normalization: Any,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> tuple[SnapshotRecord, str]:
        """Commit one validated limits aggregate and its normalized facts together."""

        value = snapshot.normalized()
        if value.dataset != "limits" or value.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("atomic limit collection requires a supported limits snapshot")
        if normalization.as_of != value.as_of or normalization.actual_as_of != value.as_of:
            raise ValueError("atomic limit collection requires an exact actual session date")
        facts = tuple(fact.normalized() for fact in normalization.rows)
        if any(fact.as_of != value.as_of or fact.actual_as_of != value.as_of for fact in facts):
            raise ValueError("all atomic limit facts must use the snapshot date")
        if any(fact.row_checksum != fact_row_checksum(fact) for fact in facts):
            raise ValueError("atomic limit collection contains an invalid row checksum")
        checksum = limit_dataset_checksum(
            facts,
            as_of=value.as_of,
            actual_as_of=normalization.actual_as_of,
            source=normalization.source,
            complete=normalization.complete,
            warnings=normalization.warnings,
            source_revision=normalization.source_revision,
            rule_version=normalization.rule_version,
            excluded=normalization.excluded,
        )
        if normalization.dataset_checksum and normalization.dataset_checksum != checksum:
            raise ValueError("atomic limit collection checksum does not match normalized facts")
        quality = value.payload.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("atomic limit collection requires dataset quality metadata")
        payload = {
            **value.payload,
            "quality": {**quality, LIMIT_DETAIL_CHECKSUM_KEY: checksum},
        }
        value = replace(value, payload=payload, checksum=payload_checksum(payload))
        fetched_at = self._normalized_datetime(
            facts[0].fetched_at if facts else value.fetched_at
        )
        assert fetched_at is not None
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="limit_collection",
                    now=now,
                    expected_dataset="limits",
                    expected_as_of=value.as_of,
                )
                manifest = connection.execute(
                    "SELECT source_revision, dataset_checksum, complete FROM limit_security_datasets WHERE as_of = ?",
                    (value.as_of.isoformat(),),
                ).fetchone()
                replacing_incomplete = manifest is not None and not bool(manifest["complete"])
                if (
                    manifest is not None
                    and not replacing_incomplete
                    and manifest["source_revision"] != normalization.source_revision
                ):
                    raise ValueError("limit facts source revision mismatch for exact date")
                if (
                    manifest is not None
                    and not replacing_incomplete
                    and manifest["dataset_checksum"] != checksum
                ):
                    raise ValueError("limit facts dataset checksum changed for exact date/revision")
                self._write_snapshot(connection, value)
                if replacing_incomplete:
                    connection.execute(
                        "DELETE FROM limit_security_facts WHERE as_of = ?",
                        (value.as_of.isoformat(),),
                    )
                connection.execute(
                    """
                    INSERT INTO limit_security_datasets (
                        as_of, actual_as_of, source, source_revision, rule_version,
                        schema_version, complete, excluded, warnings_json,
                        dataset_checksum, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(as_of) DO UPDATE SET
                        actual_as_of = excluded.actual_as_of,
                        source = excluded.source,
                        source_revision = excluded.source_revision,
                        rule_version = excluded.rule_version,
                        schema_version = excluded.schema_version,
                        complete = excluded.complete,
                        excluded = excluded.excluded,
                        warnings_json = excluded.warnings_json,
                        dataset_checksum = excluded.dataset_checksum,
                        fetched_at = excluded.fetched_at
                    """,
                    (
                        value.as_of.isoformat(),
                        normalization.actual_as_of.isoformat(),
                        normalization.source,
                        normalization.source_revision,
                        normalization.rule_version,
                        LIMIT_FACT_SCHEMA_VERSION,
                        int(normalization.complete),
                        normalization.excluded,
                        canonical_json(list(normalization.warnings)),
                        checksum,
                        fetched_at.isoformat(),
                    ),
                )
                for fact in facts:
                    item = replace(fact, dataset_checksum=checksum)
                    connection.execute(
                    """
                    INSERT INTO limit_security_facts (
                        as_of, actual_as_of, security_id, pool_type, code, exchange,
                        name, board, is_st, listing_date, listing_days, limit_regime,
                        close_price, previous_close, change_pct, touched_limit_up,
                        closed_limit_up, failed_limit_up, streak_days, eligible,
                        invalid_reason, source, fetched_at, schema_version,
                        row_checksum, dataset_checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(as_of, security_id, pool_type) DO UPDATE SET
                        actual_as_of = excluded.actual_as_of,
                        code = excluded.code,
                        exchange = excluded.exchange,
                        name = excluded.name,
                        board = excluded.board,
                        is_st = excluded.is_st,
                        listing_date = excluded.listing_date,
                        listing_days = excluded.listing_days,
                        limit_regime = excluded.limit_regime,
                        close_price = excluded.close_price,
                        previous_close = excluded.previous_close,
                        change_pct = excluded.change_pct,
                        touched_limit_up = excluded.touched_limit_up,
                        closed_limit_up = excluded.closed_limit_up,
                        failed_limit_up = excluded.failed_limit_up,
                        streak_days = excluded.streak_days,
                        eligible = excluded.eligible,
                        invalid_reason = excluded.invalid_reason,
                        source = excluded.source,
                        fetched_at = excluded.fetched_at,
                        schema_version = excluded.schema_version,
                        row_checksum = excluded.row_checksum,
                        dataset_checksum = excluded.dataset_checksum
                    """,
                    (
                        item.as_of.isoformat(),
                        item.actual_as_of.isoformat() if item.actual_as_of else None,
                        item.security_id,
                        item.pool_type,
                        item.code,
                        item.exchange,
                        item.name,
                        item.board,
                        int(item.is_st) if item.is_st is not None else None,
                        item.listing_date.isoformat() if item.listing_date else None,
                        item.listing_days,
                        item.limit_regime,
                        item.close_price,
                        item.previous_close,
                        item.change_pct,
                        int(item.touched_limit_up) if item.touched_limit_up is not None else None,
                        int(item.closed_limit_up) if item.closed_limit_up is not None else None,
                        int(item.failed_limit_up) if item.failed_limit_up is not None else None,
                        item.streak_days,
                        int(item.eligible),
                        item.invalid_reason,
                        item.source,
                        item.fetched_at.isoformat(),
                        item.schema_version,
                        item.row_checksum,
                        checksum,
                        ),
                    )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return value, checksum

    def _read_limit_security_manifest(
        self,
        as_of: date,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if connection is None:
            with self._connect() as owned_connection:
                return self._read_limit_security_manifest(as_of, connection=owned_connection)
        row = connection.execute(
            "SELECT * FROM limit_security_datasets WHERE as_of = ?", (as_of.isoformat(),)
        ).fetchone()
        if row is None:
            return None
        return {
            "as_of": date.fromisoformat(row["as_of"]),
            "actual_as_of": date.fromisoformat(row["actual_as_of"]) if row["actual_as_of"] else None,
            "source": row["source"],
            "source_revision": row["source_revision"],
            "rule_version": row["rule_version"],
            "schema_version": int(row["schema_version"]),
            "complete": bool(row["complete"]),
            "excluded": int(row["excluded"]),
            "warnings": tuple(json.loads(row["warnings_json"])),
            "dataset_checksum": row["dataset_checksum"],
            "fetched_at": datetime.fromisoformat(row["fetched_at"]),
        }

    def _read_limit_security_facts(
        self,
        as_of: date,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[LimitSecurityFactRecord, ...]:
        if connection is None:
            with self._connect() as owned_connection:
                return self._read_limit_security_facts(as_of, connection=owned_connection)
        rows = connection.execute(
            "SELECT * FROM limit_security_facts WHERE as_of = ? ORDER BY security_id, pool_type",
            (as_of.isoformat(),),
        ).fetchall()
        facts: list[LimitSecurityFactRecord] = []
        for row in rows:
            fact = LimitSecurityFactRecord(
                as_of=date.fromisoformat(row["as_of"]),
                actual_as_of=date.fromisoformat(row["actual_as_of"]) if row["actual_as_of"] else None,
                security_id=row["security_id"],
                pool_type=row["pool_type"],
                code=row["code"],
                exchange=row["exchange"],
                name=row["name"],
                board=row["board"],
                is_st=bool(row["is_st"]) if row["is_st"] is not None else None,
                listing_date=date.fromisoformat(row["listing_date"]) if row["listing_date"] else None,
                listing_days=int(row["listing_days"]) if row["listing_days"] is not None else None,
                limit_regime=row["limit_regime"],
                close_price=float(row["close_price"]) if row["close_price"] is not None else None,
                previous_close=float(row["previous_close"]) if row["previous_close"] is not None else None,
                change_pct=float(row["change_pct"]) if row["change_pct"] is not None else None,
                touched_limit_up=bool(row["touched_limit_up"]) if row["touched_limit_up"] is not None else None,
                closed_limit_up=bool(row["closed_limit_up"]) if row["closed_limit_up"] is not None else None,
                failed_limit_up=bool(row["failed_limit_up"]) if row["failed_limit_up"] is not None else None,
                streak_days=int(row["streak_days"]) if row["streak_days"] is not None else None,
                eligible=bool(row["eligible"]),
                invalid_reason=row["invalid_reason"],
                source=row["source"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                schema_version=int(row["schema_version"]),
                row_checksum=row["row_checksum"],
                dataset_checksum=row["dataset_checksum"],
            ).normalized()
            if fact.schema_version != LIMIT_FACT_SCHEMA_VERSION:
                raise SnapshotIntegrityError(
                    f"unsupported limit fact schema version: {as_of.isoformat()}/{row['security_id']}/{row['pool_type']}"
                )
            if fact_row_checksum(fact) != row["row_checksum"]:
                raise SnapshotIntegrityError(
                    f"limit fact checksum mismatch: {as_of.isoformat()}/{row['security_id']}/{row['pool_type']}"
                )
            facts.append(fact)
        return tuple(facts)

    @staticmethod
    def _validate_limit_security_manifest(
        as_of: date,
        manifest: dict[str, Any],
        facts: tuple[LimitSecurityFactRecord, ...],
    ) -> None:
        if manifest["schema_version"] != LIMIT_FACT_SCHEMA_VERSION:
            raise SnapshotIntegrityError(f"unsupported limit dataset schema version: {as_of.isoformat()}")
        if any(fact.dataset_checksum != manifest["dataset_checksum"] for fact in facts):
            raise SnapshotIntegrityError(f"limit fact dataset checksum mismatch: {as_of.isoformat()}")
        if manifest["excluded"] != sum(not fact.eligible for fact in facts):
            raise SnapshotIntegrityError(f"limit dataset exclusion count mismatch: {as_of.isoformat()}")
        actual_as_of = manifest["actual_as_of"]
        expected = limit_dataset_checksum(
            facts,
            as_of=as_of,
            actual_as_of=actual_as_of,
            source=manifest["source"],
            complete=manifest["complete"],
            warnings=manifest["warnings"],
            source_revision=manifest["source_revision"],
            rule_version=manifest["rule_version"],
            excluded=manifest["excluded"],
        )
        if expected != manifest["dataset_checksum"]:
            raise SnapshotIntegrityError(f"limit dataset checksum mismatch: {as_of.isoformat()}")

    def get_limit_security_dataset(self, as_of: date) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute("BEGIN")
            manifest = self._read_limit_security_manifest(as_of, connection=connection)
            facts = self._read_limit_security_facts(as_of, connection=connection)
        if manifest is not None:
            self._validate_limit_security_manifest(as_of, manifest, facts)
        return manifest

    def get_limit_security_facts(self, as_of: date) -> tuple[LimitSecurityFactRecord, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            manifest = self._read_limit_security_manifest(as_of, connection=connection)
            facts = self._read_limit_security_facts(as_of, connection=connection)
        if manifest is not None:
            self._validate_limit_security_manifest(as_of, manifest, facts)
        return facts

    def set_refresh_warning(
        self,
        dataset: str,
        as_of: date,
        warning: str | None,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | Callable[[], datetime] | None = None,
    ) -> bool:
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="refresh_warning",
                    now=now,
                    expected_dataset=dataset,
                    expected_as_of=as_of,
                )
                cursor = connection.execute(
                    "UPDATE snapshot_entries SET refresh_warning = ? WHERE dataset = ? AND as_of = ?",
                    (warning, dataset, as_of.isoformat()),
                )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return cursor.rowcount > 0

    def acquire_lease(
        self,
        dataset: str,
        as_of: date,
        owner: str,
        *,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> LeaseToken | None:
        current = (now or utc_now()).astimezone(timezone.utc)
        expires_at = current + timedelta(seconds=lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner, expires_at, generation, token FROM refresh_leases WHERE dataset = ? AND as_of = ?",
                (dataset, as_of.isoformat()),
            ).fetchone()
            if row is not None:
                existing_expiry = datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc)
                if existing_expiry > current:
                    connection.rollback()
                    return None
            ledger = connection.execute(
                "SELECT generation FROM refresh_lease_fences WHERE dataset = ? AND as_of = ?",
                (dataset, as_of.isoformat()),
            ).fetchone()
            prior_generation = int(ledger["generation"]) if ledger is not None else 0
            if row is not None:
                prior_generation = max(prior_generation, int(row["generation"]))
            generation = prior_generation + 1
            token_value = f"{generation}-{uuid.uuid4().hex}"
            lease = LeaseToken(dataset, as_of, owner, generation, token_value, expires_at)
            connection.execute(
                """
                INSERT INTO refresh_lease_fences(dataset, as_of, generation, token, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    generation = excluded.generation,
                    token = excluded.token,
                    updated_at = excluded.updated_at
                """,
                (dataset, as_of.isoformat(), generation, "[redacted]", current.isoformat()),
            )
            connection.execute(
                """
                INSERT INTO refresh_leases (
                    dataset, as_of, owner, acquired_at, expires_at, generation, token
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, as_of) DO UPDATE SET
                    owner = excluded.owner,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at,
                    generation = excluded.generation,
                    token = excluded.token
                """,
                (
                    dataset,
                    as_of.isoformat(),
                    owner,
                    current.isoformat(),
                    expires_at.isoformat(),
                    generation,
                    token_value,
                ),
            )
            connection.commit()
            return lease
        finally:
            connection.close()

    def get_lease_token(
        self,
        dataset: str,
        as_of: date,
        *,
        owner: str | None = None,
    ) -> LeaseToken | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner, generation, token, expires_at FROM refresh_leases WHERE dataset = ? AND as_of = ?"
                + (" AND owner = ?" if owner is not None else ""),
                (dataset, as_of.isoformat(), owner) if owner is not None else (dataset, as_of.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return LeaseToken(
            dataset,
            as_of,
            row["owner"],
            int(row["generation"]),
            row["token"],
            datetime.fromisoformat(row["expires_at"]).astimezone(timezone.utc),
        )

    def renew_lease(
        self,
        lease: LeaseToken,
        *,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> LeaseToken | None:
        current = (now or utc_now()).astimezone(timezone.utc)
        expires_at = current + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE refresh_leases SET acquired_at = ?, expires_at = ?
                WHERE dataset = ? AND as_of = ? AND owner = ? AND generation = ? AND token = ?
                  AND expires_at > ?
                """,
                (
                    current.isoformat(),
                    expires_at.isoformat(),
                    lease.dataset,
                    lease.as_of.isoformat(),
                    lease.owner,
                    lease.generation,
                    lease.token,
                    current.isoformat(),
                ),
            )
        return replace(lease, expires_at=expires_at) if cursor.rowcount > 0 else None

    def release_lease(
        self,
        dataset: str,
        as_of: date,
        owner: str | LeaseToken | None = None,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
    ) -> bool:
        token = owner if isinstance(owner, LeaseToken) else self._resolve_lease_argument(lease, lease_token)
        if token is None and isinstance(owner, str):
            # Backward-compatible owner-only release for legacy callers. New
            # paths should pass the opaque LeaseToken to preserve fencing.
            token = self.get_lease_token(dataset, as_of, owner=owner)
        if token is None:
            return False
        if token.dataset != dataset or token.as_of != as_of:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM refresh_leases
                WHERE dataset = ? AND as_of = ? AND owner = ? AND generation = ? AND token = ?
                """,
                (
                    dataset,
                    as_of.isoformat(),
                    token.owner,
                    token.generation,
                    token.token,
                ),
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

    def get_completed_refresh_generation(self, dataset: str, as_of: date) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT rowid, result_json FROM refresh_runs WHERE dataset = ? AND as_of = ? ORDER BY rowid DESC",
                (dataset, as_of.isoformat()),
            )
            for row in rows:
                result = json.loads(row["result_json"])
                if result.get("cacheResult") in {"stored", "retained", "missing"}:
                    return int(row["rowid"])
        return 0

    def create_collection_run(
        self,
        run_id: str,
        as_of: date,
        datasets: tuple[str, ...],
        *,
        created_at: datetime | None = None,
    ) -> CollectionRunRecord:
        timestamp = self._normalized_datetime(created_at or utc_now())
        assert timestamp is not None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collection_runs (
                    run_id, as_of, status, requested_datasets_json, created_at
                ) VALUES (?, ?, 'queued', ?, ?)
                """,
                (run_id, as_of.isoformat(), canonical_json(list(datasets)), timestamp.isoformat()),
            )
        return CollectionRunRecord(run_id, as_of, "queued", datasets, timestamp)

    def create_collection_task(
        self,
        task_id: str,
        run_id: str,
        dataset: str,
        as_of: date,
        *,
        queued_at: datetime | None = None,
        status: CollectionTaskStatus = "queued",
    ) -> CollectionTaskRecord:
        timestamp = self._normalized_datetime(queued_at or utc_now())
        assert timestamp is not None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collection_tasks (
                    task_id, run_id, dataset, as_of, status, queued_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, run_id, dataset, as_of.isoformat(), status, timestamp.isoformat()),
            )
        return CollectionTaskRecord(
            task_id=task_id,
            run_id=run_id,
            dataset=dataset,
            as_of=as_of,
            status=status,
            queued_at=timestamp,
        )

    def update_collection_run(
        self,
        run_id: str,
        status: CollectionRunStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> CollectionRunRecord:
        started = self._normalized_datetime(started_at)
        completed = self._normalized_datetime(completed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE collection_runs
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE run_id = ?
                """,
                (
                    status,
                    started.isoformat() if started else None,
                    completed.isoformat() if completed else None,
                    run_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown collection run: {run_id}")
        record = self.get_collection_run(run_id)
        assert record is not None
        return record

    def transition_collection_task(
        self,
        task_id: str,
        status: CollectionTaskStatus,
        *,
        expected_statuses: tuple[CollectionTaskStatus, ...] | None = None,
        source: str | None = None,
        observations: int | None = None,
        warning: str | None = None,
        timings: dict[str, float] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: float | None = None,
        settled: bool | None = None,
    ) -> CollectionTaskRecord:
        started = self._normalized_datetime(started_at)
        completed = self._normalized_datetime(completed_at)
        assignments = ["status = ?"]
        values: list[Any] = [status]
        optional_values = (
            ("source", source),
            ("observations", observations),
            ("warning", warning),
            ("timings_json", canonical_json(timings) if timings is not None else None),
            ("started_at", started.isoformat() if started else None),
            ("completed_at", completed.isoformat() if completed else None),
            ("duration_ms", duration_ms),
            ("settled", int(settled) if settled is not None else None),
        )
        for column, value in optional_values:
            if value is not None:
                assignments.append(f"{column} = ?")
                values.append(value)
        where = "task_id = ?"
        values.append(task_id)
        if expected_statuses:
            placeholders = ", ".join("?" for _ in expected_statuses)
            where += f" AND status IN ({placeholders})"
            values.extend(expected_statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE collection_tasks SET {', '.join(assignments)} WHERE {where}",
                values,
            )
        if cursor.rowcount == 0:
            raise ValueError(f"collection task transition rejected: {task_id} -> {status}")
        record = self.get_collection_task(task_id)
        assert record is not None
        return record

    def get_collection_run(self, run_id: str) -> CollectionRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM collection_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return CollectionRunRecord(
            run_id=row["run_id"],
            as_of=date.fromisoformat(row["as_of"]),
            status=row["status"],
            requested_datasets=tuple(json.loads(row["requested_datasets_json"])),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
        )

    def get_collection_task(self, task_id: str) -> CollectionTaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM collection_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._collection_task_from_row(row) if row is not None else None

    def list_collection_tasks(self, run_id: str) -> tuple[CollectionTaskRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM collection_tasks WHERE run_id = ? ORDER BY queued_at, dataset",
                (run_id,),
            ).fetchall()
        return tuple(self._collection_task_from_row(row) for row in rows)

    def latest_collection_attempt(self, dataset: str, as_of: date) -> CollectionTaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM collection_tasks
                WHERE dataset = ? AND as_of = ?
                ORDER BY queued_at DESC, task_id DESC
                LIMIT 1
                """,
                (dataset, as_of.isoformat()),
            ).fetchone()
        return self._collection_task_from_row(row) if row is not None else None

    def active_collection_task(
        self,
        dataset: str,
        as_of: date,
        *,
        now: datetime | None = None,
    ) -> CollectionTaskRecord | None:
        current = self._normalized_datetime(now or utc_now())
        assert current is not None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT task.*
                FROM collection_tasks AS task
                JOIN refresh_leases AS lease
                  ON lease.dataset = task.dataset AND lease.as_of = task.as_of
                WHERE task.dataset = ? AND task.as_of = ?
                  AND task.status IN ('queued', 'collecting')
                  AND lease.expires_at > ?
                ORDER BY task.queued_at DESC
                LIMIT 1
                """,
                (dataset, as_of.isoformat(), current.isoformat()),
            ).fetchone()
        return self._collection_task_from_row(row) if row is not None else None

    def expire_inactive_collection_tasks(self, *, now: datetime | None = None) -> int:
        current = self._normalized_datetime(now or utc_now())
        assert current is not None
        completed_at = current.isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task.task_id, task.dataset, task.as_of
                FROM collection_tasks AS task
                LEFT JOIN refresh_leases AS lease
                  ON lease.dataset = task.dataset AND lease.as_of = task.as_of
                 AND lease.owner = task.task_id
                 AND lease.expires_at > ?
                WHERE task.status IN ('queued', 'collecting') AND lease.dataset IS NULL
                """,
                (completed_at,),
            ).fetchall()
            for row in rows:
                retained = connection.execute(
                    "SELECT 1 FROM snapshot_entries WHERE dataset = ? AND as_of = ?",
                    (row["dataset"], row["as_of"]),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE collection_tasks
                    SET status = ?, warning = ?, completed_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        "failed-retained" if retained else "failed-missing",
                        "collection worker stopped before completion; task is retryable",
                        completed_at,
                        row["task_id"],
                    ),
                )
        return len(rows)

    @staticmethod
    def _collection_task_from_row(row: sqlite3.Row) -> CollectionTaskRecord:
        return CollectionTaskRecord(
            task_id=row["task_id"],
            run_id=row["run_id"],
            dataset=row["dataset"],
            as_of=date.fromisoformat(row["as_of"]),
            status=row["status"],
            source=row["source"],
            observations=int(row["observations"]),
            warning=row["warning"],
            timings=json.loads(row["timings_json"]),
            queued_at=SnapshotStore._parse_datetime(row["queued_at"]),
            started_at=SnapshotStore._parse_datetime(row["started_at"]),
            completed_at=SnapshotStore._parse_datetime(row["completed_at"]),
            duration_ms=float(row["duration_ms"]) if row["duration_ms"] is not None else None,
            settled=bool(row["settled"]),
        )

    def put_core_index_result(
        self,
        record: CoreIndexResultRecord,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        now: datetime | None = None,
    ) -> CoreIndexResultRecord:
        lease = self._resolve_lease_argument(lease, lease_token)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._assert_lease(
                    connection,
                    lease,
                    operation="core_index_result",
                    now=now,
                    expected_dataset="core",
                )
                connection.execute(
                """
                INSERT INTO core_index_results (
                    task_id, code, name, status, source, observations,
                    warning, duration_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, code) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    source = excluded.source,
                    observations = excluded.observations,
                    warning = excluded.warning,
                    duration_ms = excluded.duration_ms,
                    payload_json = excluded.payload_json
                """,
                (
                    record.task_id,
                    record.code,
                    record.name,
                    record.status,
                    record.source,
                    record.observations,
                    record.warning,
                    record.duration_ms,
                    canonical_json(record.payload) if record.payload is not None else None,
                ),
                )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return record

    def list_core_index_results(self, task_id: str) -> tuple[CoreIndexResultRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM core_index_results WHERE task_id = ? ORDER BY code",
                (task_id,),
            ).fetchall()
        return tuple(
            CoreIndexResultRecord(
                task_id=row["task_id"],
                code=row["code"],
                name=row["name"],
                status=row["status"],
                source=row["source"],
                observations=int(row["observations"]),
                warning=row["warning"],
                duration_ms=float(row["duration_ms"]) if row["duration_ms"] is not None else None,
                payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
            )
            for row in rows
        )

    def put_materialized_aggregate(
        self,
        record: MaterializedAggregateRecord,
        *,
        lease: LeaseToken | None = None,
        lease_token: LeaseToken | None = None,
        expected_revision: str | None = None,
        now: datetime | Callable[[], datetime] | None = None,
    ) -> MaterializedAggregateRecord:
        value = record.normalized()
        lease = self._resolve_lease_argument(lease, lease_token)
        # Legacy callers may write a standalone aggregate without fencing. The
        # collection/refresh paths always provide both lease and revision.
        legacy_unfenced = lease is None and expected_revision is None
        if not legacy_unfenced and lease is None:
            raise ValueError("materialized aggregate writes require a fencing lease")
        if not legacy_unfenced and not expected_revision:
            raise ValueError("materialized aggregate writes require an input revision")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if not legacy_unfenced:
                    self._assert_lease(
                        connection,
                        lease,
                        operation="materialized_aggregate",
                        now=now,
                        expected_as_of=value.as_of,
                    )
                    current_revision = self._materialization_revision(connection, value.as_of)
                    if current_revision != expected_revision:
                        raise MaterializedAggregateConflict(
                            "materialized aggregate inputs changed before commit"
                        )
                    if value.payload.get(MATERIALIZED_COMPONENT_REVISION_KEY) != expected_revision:
                        raise ValueError("materialized aggregate payload revision does not match its inputs")
                connection.execute(
                """
                INSERT INTO materialized_market_environment (
                    as_of, payload_json, generated_at, checksum
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(as_of) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    generated_at = excluded.generated_at,
                    checksum = excluded.checksum
                """,
                (
                    value.as_of.isoformat(),
                    canonical_json(value.payload),
                    value.generated_at.isoformat(),
                    value.checksum,
                ),
                )
        except LeaseFenceError as exc:
            self._record_lease_fence_event(exc)
            raise
        return value

    def get_materialized_aggregate(self, as_of: date) -> MaterializedAggregateRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM materialized_market_environment WHERE as_of = ?",
                (as_of.isoformat(),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if payload_checksum(payload) != row["checksum"]:
            raise SnapshotIntegrityError(
                f"materialized aggregate checksum mismatch: {as_of.isoformat()}"
            )
        return MaterializedAggregateRecord(
            as_of=date.fromisoformat(row["as_of"]),
            payload=payload,
            generated_at=datetime.fromisoformat(row["generated_at"]),
            checksum=row["checksum"],
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
