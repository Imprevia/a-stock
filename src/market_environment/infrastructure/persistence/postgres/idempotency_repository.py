"""Atomic PostgreSQL idempotency binding and submission-state repository."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from ....domain.models import (
    FullCollectionSemantics,
    IdempotencyBinding,
    IdempotencyClaim,
    IdempotencyClaimDisposition,
    IdempotencyKey,
    StructuredTaskFailure,
    SubmissionState,
)
from ....snapshot_store import CollectionRunRecord, CollectionTaskRecord
from .collection_repositories import (
    PostgresCollectionRunRepository,
    PostgresCollectionTaskRepository,
)
from .repositories import _as_date, _as_datetime, _canonical_json, _json_load


class PostgresCollectionIdempotencyRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.runs = PostgresCollectionRunRepository(connection)
        self.tasks = PostgresCollectionTaskRepository(connection)

    def get_binding(
        self,
        operation_scope: str,
        key: IdempotencyKey,
    ) -> IdempotencyBinding | None:
        row = self.connection.execute(
            text(
                """
                SELECT * FROM collection_idempotency_bindings
                WHERE operation_scope = :operation_scope
                  AND idempotency_key = :idempotency_key
                """
            ),
            {
                "operation_scope": operation_scope,
                "idempotency_key": key.value,
            },
        ).mappings().first()
        return self._from_row(row) if row is not None else None

    def claim(
        self,
        key: IdempotencyKey,
        semantics: FullCollectionSemantics,
        *,
        run_id: str,
        task_ids: Mapping[str, str],
        now: datetime,
    ) -> IdempotencyClaim:
        self._validate_new_claim(semantics, run_id=run_id, task_ids=task_ids)
        try:
            with self.connection.begin_nested():
                self.runs.create_run(
                    CollectionRunRecord(
                        run_id=run_id,
                        as_of=semantics.resolved_as_of,
                        status="queued",
                        requested_datasets=semantics.datasets,
                        created_at=now,
                    )
                )
                for dataset in semantics.datasets:
                    self.tasks.create_task(
                        CollectionTaskRecord(
                            task_id=task_ids[dataset],
                            run_id=run_id,
                            dataset=dataset,
                            as_of=semantics.resolved_as_of,
                            status="queued",
                            queued_at=now,
                        )
                    )
                self.connection.execute(
                    text(
                        """
                        INSERT INTO collection_idempotency_bindings(
                            operation_scope, idempotency_key,
                            semantic_fingerprint, resolved_as_of,
                            operation_version, dataset_fingerprint, run_id,
                            submission_state, submission_attempts,
                            created_at, updated_at
                        ) VALUES (
                            :operation_scope, :idempotency_key,
                            :semantic_fingerprint, :resolved_as_of,
                            :operation_version, :dataset_fingerprint, :run_id,
                            'reserved', 0, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "operation_scope": semantics.operation_scope,
                        "idempotency_key": key.value,
                        "semantic_fingerprint": semantics.semantic_fingerprint,
                        "resolved_as_of": semantics.resolved_as_of,
                        "operation_version": semantics.operation_version,
                        "dataset_fingerprint": semantics.dataset_fingerprint,
                        "run_id": run_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError:
            existing = self.get_binding(semantics.operation_scope, key)
            if existing is None:
                raise
            return IdempotencyClaim(
                disposition=(
                    IdempotencyClaimDisposition.REPLAY
                    if existing.matches(semantics)
                    else IdempotencyClaimDisposition.CONFLICT
                ),
                binding=existing,
            )

        binding = self.get_binding(semantics.operation_scope, key)
        if binding is None:  # pragma: no cover - defensive database contract
            raise RuntimeError("idempotency claim was inserted but cannot be read")
        return IdempotencyClaim(IdempotencyClaimDisposition.CREATED, binding)

    def acquire_submission(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        *,
        owner: str,
        now: datetime,
        lease_seconds: float,
    ) -> IdempotencyBinding | None:
        if not owner.strip() or lease_seconds <= 0:
            raise ValueError("submission owner and positive lease are required")
        row = self.connection.execute(
            text(
                """
                UPDATE collection_idempotency_bindings
                SET submission_state = 'submitting',
                    submission_attempts = submission_attempts + 1,
                    submission_owner = :owner,
                    submission_lease_expires_at = :lease_expires_at,
                    submission_error_json = NULL,
                    updated_at = :updated_at
                WHERE operation_scope = :operation_scope
                  AND idempotency_key = :idempotency_key
                  AND (
                    submission_state IN ('reserved', 'submission-failed')
                    OR (
                      submission_state IN ('submitting', 'submitted')
                      AND submission_lease_expires_at <= :updated_at
                      AND NOT EXISTS (
                        SELECT 1
                        FROM collection_tasks AS task
                        JOIN refresh_leases AS lease
                          ON lease.dataset = task.dataset
                         AND lease.as_of = task.as_of
                         AND lease.owner = task.task_id
                         AND lease.expires_at > :updated_at
                        WHERE task.run_id = collection_idempotency_bindings.run_id
                          AND task.status IN ('queued', 'collecting')
                      )
                    )
                  )
                RETURNING *
                """
            ),
            {
                "owner": owner,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
                "operation_scope": operation_scope,
                "idempotency_key": key.value,
            },
        ).mappings().first()
        return self._from_row(row) if row is not None else None

    def mark_submitted(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        *,
        owner: str,
        now: datetime,
        recovery_seconds: float,
    ) -> IdempotencyBinding:
        if recovery_seconds <= 0:
            raise ValueError("positive submission recovery duration is required")
        return self._finish_submission(
            operation_scope,
            key,
            owner=owner,
            now=now,
            state=SubmissionState.SUBMITTED,
            failure=None,
            recovery_seconds=recovery_seconds,
        )

    def mark_submission_failed(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        *,
        owner: str,
        failure: StructuredTaskFailure,
        now: datetime,
    ) -> IdempotencyBinding:
        return self._finish_submission(
            operation_scope,
            key,
            owner=owner,
            now=now,
            state=SubmissionState.SUBMISSION_FAILED,
            failure=failure,
            recovery_seconds=None,
        )

    def _finish_submission(
        self,
        operation_scope: str,
        key: IdempotencyKey,
        *,
        owner: str,
        now: datetime,
        state: SubmissionState,
        failure: StructuredTaskFailure | None,
        recovery_seconds: float | None,
    ) -> IdempotencyBinding:
        result = self.connection.execute(
            text(
                """
                UPDATE collection_idempotency_bindings
                SET submission_state = :submission_state,
                    submission_owner = NULL,
                    submission_lease_expires_at = :submission_lease_expires_at,
                    submission_error_json = :submission_error_json,
                    submitted_at = CASE
                        WHEN :submission_state = 'submitted' THEN :updated_at
                        ELSE submitted_at
                    END,
                    updated_at = :updated_at
                WHERE operation_scope = :operation_scope
                  AND idempotency_key = :idempotency_key
                  AND submission_state = 'submitting'
                  AND submission_owner = :owner
                """
            ),
            {
                "submission_state": state.value,
                "submission_error_json": (
                    _canonical_json(failure.to_dict()) if failure is not None else None
                ),
                "submission_lease_expires_at": (
                    now + timedelta(seconds=recovery_seconds)
                    if recovery_seconds is not None
                    else None
                ),
                "updated_at": now,
                "operation_scope": operation_scope,
                "idempotency_key": key.value,
                "owner": owner,
            },
        )
        if result.rowcount != 1:
            raise ValueError("submission transition rejected")
        binding = self.get_binding(operation_scope, key)
        assert binding is not None
        return binding

    @staticmethod
    def _validate_new_claim(
        semantics: FullCollectionSemantics,
        *,
        run_id: str,
        task_ids: Mapping[str, str],
    ) -> None:
        if not run_id.strip():
            raise ValueError("collection run id is required")
        if tuple(task_ids) != semantics.datasets:
            raise ValueError("task ids must cover the canonical datasets in stable order")
        values = tuple(task_ids.values())
        if any(not str(value).strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("task ids must be non-empty and unique")

    @staticmethod
    def _from_row(row: Any) -> IdempotencyBinding:
        error_value = _json_load(row["submission_error_json"], None)
        return IdempotencyBinding(
            operation_scope=str(row["operation_scope"]),
            key=IdempotencyKey(str(row["idempotency_key"])),
            semantic_fingerprint=str(row["semantic_fingerprint"]),
            resolved_as_of=_as_date(row["resolved_as_of"]),  # type: ignore[arg-type]
            operation_version=str(row["operation_version"]),
            dataset_fingerprint=str(row["dataset_fingerprint"]),
            run_id=str(row["run_id"]),
            submission_state=SubmissionState(str(row["submission_state"])),
            submission_attempts=int(row["submission_attempts"]),
            submission_owner=row["submission_owner"],
            submission_lease_expires_at=(
                _as_datetime(row["submission_lease_expires_at"])
                if row["submission_lease_expires_at"] is not None
                else None
            ),
            submission_error=(
                StructuredTaskFailure.from_dict(error_value)
                if error_value is not None
                else None
            ),
            created_at=_as_datetime(row["created_at"]),
            updated_at=_as_datetime(row["updated_at"]),
            submitted_at=(
                _as_datetime(row["submitted_at"])
                if row["submitted_at"] is not None
                else None
            ),
        )


__all__ = ["PostgresCollectionIdempotencyRepository"]
