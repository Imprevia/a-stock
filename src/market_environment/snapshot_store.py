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
                """
            )

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

    def put_core_index_result(self, record: CoreIndexResultRecord) -> CoreIndexResultRecord:
        with self._connect() as connection:
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
    ) -> MaterializedAggregateRecord:
        value = record.normalized()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
