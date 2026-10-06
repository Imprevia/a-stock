"""PostgreSQL repositories for collection runs, tasks, and core sub-results."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Connection, bindparam, text

from ....snapshot_store import (
    CollectionRunRecord,
    CollectionTaskRecord,
    CoreIndexResultRecord,
)
from .repositories import _as_date, _as_datetime, _canonical_json, _json_load


RUN_TRANSITIONS = {
    "queued": frozenset({"queued", "collecting", "failed"}),
    "collecting": frozenset({"collecting", "success", "partial", "failed"}),
    "success": frozenset({"success"}),
    "partial": frozenset({"partial"}),
    "failed": frozenset({"failed"}),
}


class PostgresCollectionRunRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def get_run(self, run_id: str) -> CollectionRunRecord | None:
        row = self.connection.execute(
            text("SELECT * FROM collection_runs WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().first()
        if row is None:
            return None
        return CollectionRunRecord(
            run_id=str(row["run_id"]),
            as_of=_as_date(row["as_of"]),  # type: ignore[arg-type]
            status=str(row["status"]),  # type: ignore[arg-type]
            requested_datasets=tuple(
                str(value) for value in _json_load(row["requested_datasets_json"], [])
            ),
            created_at=_as_datetime(row["created_at"]),
            started_at=(
                _as_datetime(row["started_at"])
                if row["started_at"] is not None
                else None
            ),
            completed_at=(
                _as_datetime(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
        )

    def create_run(self, run: CollectionRunRecord) -> CollectionRunRecord:
        if run.status != "queued":
            raise ValueError("new collection runs must start queued")
        self.connection.execute(
            text(
                """
                INSERT INTO collection_runs(
                    run_id, as_of, status, requested_datasets_json, created_at,
                    started_at, completed_at
                ) VALUES (
                    :run_id, :as_of, :status, :requested_datasets_json, :created_at,
                    :started_at, :completed_at
                )
                """
            ),
            {
                "run_id": run.run_id,
                "as_of": run.as_of,
                "status": run.status,
                "requested_datasets_json": _canonical_json(list(run.requested_datasets)),
                "created_at": run.created_at,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
            },
        )
        return run

    def save_run(self, run: object) -> CollectionRunRecord:
        if not isinstance(run, CollectionRunRecord):
            raise TypeError("collection run repository requires CollectionRunRecord")
        current = self.get_run(run.run_id)
        if current is None:
            return self.create_run(run)
        return self.transition_run(
            run.run_id,
            run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def transition_run(
        self,
        run_id: str,
        status: str,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> CollectionRunRecord:
        current = self.get_run(run_id)
        if current is None:
            raise KeyError(f"unknown collection run: {run_id}")
        if status not in RUN_TRANSITIONS[current.status]:
            raise ValueError(
                f"collection run transition rejected: {current.status} -> {status}"
            )
        self.connection.execute(
            text(
                """
                UPDATE collection_runs
                SET status = :status,
                    started_at = COALESCE(:started_at, started_at),
                    completed_at = COALESCE(:completed_at, completed_at)
                WHERE run_id = :run_id
                """
            ),
            {
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at,
                "run_id": run_id,
            },
        )
        value = self.get_run(run_id)
        assert value is not None
        return value


class PostgresCollectionTaskRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def get_task(self, task_id: str) -> CollectionTaskRecord | None:
        row = self.connection.execute(
            text("SELECT * FROM collection_tasks WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).mappings().first()
        return self._from_row(row) if row is not None else None

    def list_tasks(self, run_id: str) -> Sequence[CollectionTaskRecord]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM collection_tasks WHERE run_id = :run_id "
                "ORDER BY queued_at, dataset"
            ),
            {"run_id": run_id},
        ).mappings()
        return tuple(self._from_row(row) for row in rows)

    def latest_attempt(self, dataset: str, as_of: date) -> CollectionTaskRecord | None:
        row = self.connection.execute(
            text(
                "SELECT * FROM collection_tasks "
                "WHERE dataset = :dataset AND as_of = :as_of "
                "ORDER BY queued_at DESC, task_id DESC LIMIT 1"
            ),
            {"dataset": dataset, "as_of": as_of},
        ).mappings().first()
        return self._from_row(row) if row is not None else None

    def active_task(
        self,
        dataset: str,
        as_of: date,
        *,
        now: datetime,
    ) -> CollectionTaskRecord | None:
        row = self.connection.execute(
            text(
                """
                SELECT task.*
                FROM collection_tasks AS task
                JOIN refresh_leases AS lease
                  ON lease.dataset = task.dataset AND lease.as_of = task.as_of
                 AND lease.owner = task.task_id
                WHERE task.dataset = :dataset AND task.as_of = :as_of
                  AND task.status IN ('queued', 'collecting')
                  AND lease.expires_at > :now
                ORDER BY task.queued_at DESC LIMIT 1
                """
            ),
            {"dataset": dataset, "as_of": as_of, "now": now.isoformat()},
        ).mappings().first()
        return self._from_row(row) if row is not None else None

    def create_task(self, task: CollectionTaskRecord) -> CollectionTaskRecord:
        self.connection.execute(
            text(
                """
                INSERT INTO collection_tasks(
                    task_id, run_id, dataset, as_of, status, source, observations,
                    warning, timings_json, queued_at, started_at, completed_at,
                    duration_ms, settled
                ) VALUES (
                    :task_id, :run_id, :dataset, :as_of, :status, :source,
                    :observations, :warning, :timings_json, :queued_at, :started_at,
                    :completed_at, :duration_ms, :settled
                )
                """
            ),
            {
                "task_id": task.task_id,
                "run_id": task.run_id,
                "dataset": task.dataset,
                "as_of": task.as_of,
                "status": task.status,
                "source": task.source,
                "observations": task.observations,
                "warning": task.warning,
                "timings_json": _canonical_json(task.timings or {}),
                "queued_at": task.queued_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "duration_ms": task.duration_ms,
                "settled": int(task.settled),
            },
        )
        return task

    def save_task(self, task: object) -> CollectionTaskRecord:
        if not isinstance(task, CollectionTaskRecord):
            raise TypeError("collection task repository requires CollectionTaskRecord")
        current = self.get_task(task.task_id)
        if current is None:
            return self.create_task(task)
        return self.transition_task(
            task.task_id,
            task.status,
            expected_statuses=(current.status,),
            source=task.source,
            observations=task.observations,
            warning=task.warning,
            timings=task.timings,
            started_at=task.started_at,
            completed_at=task.completed_at,
            duration_ms=task.duration_ms,
            settled=task.settled,
        )

    def transition_task(
        self,
        task_id: str,
        status: str,
        *,
        expected_statuses: Iterable[str] | None = None,
        source: str | None = None,
        observations: int | None = None,
        warning: str | None = None,
        timings: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: float | None = None,
        settled: bool | None = None,
    ) -> CollectionTaskRecord:
        assignments = ["status = :status"]
        parameters: dict[str, Any] = {"status": status, "task_id": task_id}
        optional = {
            "source": source,
            "observations": observations,
            "warning": warning,
            "timings_json": _canonical_json(timings) if timings is not None else None,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "settled": int(settled) if settled is not None else None,
        }
        for column, value in optional.items():
            if value is not None:
                assignments.append(f"{column} = :{column}")
                parameters[column] = value
        expected = tuple(expected_statuses or ())
        statement = (
            f"UPDATE collection_tasks SET {', '.join(assignments)} "
            "WHERE task_id = :task_id"
        )
        clause = text(statement)
        if expected:
            statement += " AND status IN :expected_statuses"
            clause = text(statement).bindparams(
                bindparam("expected_statuses", expanding=True)
            )
            parameters["expected_statuses"] = expected
        result = self.connection.execute(clause, parameters)
        if result.rowcount == 0:
            raise ValueError(f"collection task transition rejected: {task_id} -> {status}")
        value = self.get_task(task_id)
        assert value is not None
        return value

    def expire_inactive(self, *, now: datetime) -> int:
        rows = self.connection.execute(
            text(
                """
                SELECT task.task_id, task.dataset, task.as_of,
                       CASE WHEN snapshot.dataset IS NULL THEN 0 ELSE 1 END AS retained
                FROM collection_tasks AS task
                LEFT JOIN refresh_leases AS lease
                  ON lease.dataset = task.dataset AND lease.as_of = task.as_of
                 AND lease.owner = task.task_id AND lease.expires_at > :now
                LEFT JOIN snapshot_entries AS snapshot
                  ON snapshot.dataset = task.dataset AND snapshot.as_of = task.as_of
                WHERE task.status IN ('queued', 'collecting') AND lease.dataset IS NULL
                """
            ),
            {"now": now.isoformat()},
        ).mappings().all()
        for row in rows:
            self.connection.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status, warning = :warning, completed_at = :completed_at
                    WHERE task_id = :task_id
                    """
                ),
                {
                    "status": "failed-retained" if row["retained"] else "failed-missing",
                    "warning": "collection worker stopped before completion; task is retryable",
                    "completed_at": now,
                    "task_id": row["task_id"],
                },
            )
        return len(rows)

    @staticmethod
    def _from_row(row: Any) -> CollectionTaskRecord:
        return CollectionTaskRecord(
            task_id=str(row["task_id"]),
            run_id=str(row["run_id"]),
            dataset=str(row["dataset"]),
            as_of=_as_date(row["as_of"]),  # type: ignore[arg-type]
            status=str(row["status"]),  # type: ignore[arg-type]
            source=str(row["source"]),
            observations=int(row["observations"]),
            warning=row["warning"],
            timings=dict(_json_load(row["timings_json"], {})),
            queued_at=_as_datetime(row["queued_at"]) if row["queued_at"] is not None else None,
            started_at=_as_datetime(row["started_at"]) if row["started_at"] is not None else None,
            completed_at=(
                _as_datetime(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
            duration_ms=(
                float(row["duration_ms"])
                if row["duration_ms"] is not None
                else None
            ),
            settled=bool(row["settled"]),
        )


class PostgresCoreIndexResultRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def put_result(self, result: object) -> CoreIndexResultRecord:
        if not isinstance(result, CoreIndexResultRecord):
            raise TypeError("core index repository requires CoreIndexResultRecord")
        self.connection.execute(
            text(
                """
                INSERT INTO core_index_results(
                    task_id, code, name, status, source, observations,
                    warning, duration_ms, payload_json
                ) VALUES (
                    :task_id, :code, :name, :status, :source, :observations,
                    :warning, :duration_ms, :payload_json
                )
                ON CONFLICT(task_id, code) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    source = excluded.source,
                    observations = excluded.observations,
                    warning = excluded.warning,
                    duration_ms = excluded.duration_ms,
                    payload_json = excluded.payload_json
                """
            ),
            {
                "task_id": result.task_id,
                "code": result.code,
                "name": result.name,
                "status": result.status,
                "source": result.source,
                "observations": result.observations,
                "warning": result.warning,
                "duration_ms": result.duration_ms,
                "payload_json": (
                    _canonical_json(result.payload)
                    if result.payload is not None
                    else None
                ),
            },
        )
        return result

    def list_results(self, task_id: str) -> Sequence[CoreIndexResultRecord]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM core_index_results "
                "WHERE task_id = :task_id ORDER BY code"
            ),
            {"task_id": task_id},
        ).mappings()
        return tuple(
            CoreIndexResultRecord(
                task_id=str(row["task_id"]),
                code=str(row["code"]),
                name=str(row["name"]),
                status=str(row["status"]),  # type: ignore[arg-type]
                source=str(row["source"]),
                observations=int(row["observations"]),
                warning=row["warning"],
                duration_ms=(
                    float(row["duration_ms"])
                    if row["duration_ms"] is not None
                    else None
                ),
                payload=_json_load(row["payload_json"], None),
            )
            for row in rows
        )


__all__ = [
    "PostgresCollectionRunRepository",
    "PostgresCollectionTaskRepository",
    "PostgresCoreIndexResultRepository",
    "RUN_TRANSITIONS",
]
