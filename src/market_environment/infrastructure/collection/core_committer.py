"""Atomic fenced committer for core index collection results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from ...application.ports import MarketEnvironmentUnitOfWork
from ...application.ports.committers import DatasetCommitRequest
from ...application.ports.core_committers import (
    CoreCommitEvidence,
    CoreCommitRequest,
    CoreIndexCommitEvidence,
    CoreTradingSessionEvidence,
)
from ...domain.models import CollectionCandidate, CollectionTaskState
from ..legacy.snapshot_store import (
    CollectionTaskRecord,
    CoreIndexResultRecord,
    TradingSessionRecord,
    payload_checksum,
)


class CoreDatasetCommitter:
    """Persist the complete core write set in one fenced transaction."""

    dataset_id = "core"

    def __init__(
        self,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def commit(self, request: DatasetCommitRequest) -> CoreCommitEvidence:
        if not isinstance(request, CoreCommitRequest):
            raise TypeError("core committer requires CoreCommitRequest")

        with self._unit_of_work_factory() as unit_of_work:
            stored, task, index_results, session, previous_session = (
                unit_of_work.leases.execute_fenced(
                    request.lease,
                    "core_dataset_commit",
                    lambda _connection: self._write(unit_of_work, request),
                    expected_identity=request.identity,
                )
            )
            unit_of_work.commit()

        if not isinstance(stored, CollectionCandidate):
            raise TypeError("core transaction returned invalid snapshot evidence")
        if not isinstance(task, CollectionTaskRecord):
            raise TypeError("core transaction returned invalid task evidence")
        return CoreCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=stored,
            writes=(
                "core-index-results",
                *(("trading-session",) if session is not None else ()),
                *(
                    ("snapshot",)
                    if request.outcome.state
                    is not CollectionTaskState.FAILED_RETAINED
                    else ()
                ),
                "collection-task",
            ),
            task_id=task.task_id,
            index_results=index_results,
            session=session,
            previous_session=previous_session,
            snapshot_checksum=payload_checksum(dict(stored.payload)),
        )

    def _write(
        self,
        unit_of_work: MarketEnvironmentUnitOfWork,
        request: CoreCommitRequest,
    ) -> tuple[
        CollectionCandidate,
        CollectionTaskRecord,
        tuple[CoreIndexCommitEvidence, ...],
        CoreTradingSessionEvidence | None,
        CoreTradingSessionEvidence | None,
    ]:
        task = unit_of_work.collection_tasks.get_task(request.task_id)
        if not isinstance(task, CollectionTaskRecord):
            raise ValueError(f"unknown core collection task: {request.task_id}")
        if (
            task.dataset != request.identity.dataset
            or task.as_of != request.identity.as_of
        ):
            raise ValueError("core collection task identity mismatch")
        if task.status != "collecting":
            raise ValueError("core collection task must be collecting before commit")

        existing = unit_of_work.snapshots.get(request.identity)
        retained_by_code = self._retained_payloads(existing)
        for result in request.index_results:
            if result.retained and (
                result.code not in retained_by_code
                or dict(result.payload or {}) != dict(retained_by_code[result.code])
            ):
                raise ValueError(
                    f"core retained index lacks matching same-date snapshot: {result.code}"
                )

        committed_results: list[CoreIndexCommitEvidence] = []
        for result in request.index_results:
            stored_result = unit_of_work.core_index_results.put_result(
                CoreIndexResultRecord(
                    task_id=request.task_id,
                    code=result.code,
                    name=result.name,
                    status=result.state.value,
                    source=result.source,
                    observations=result.observations,
                    warning=result.warning,
                    duration_ms=result.duration_ms,
                    payload=dict(result.payload) if result.payload is not None else None,
                )
            )
            if not isinstance(stored_result, CoreIndexResultRecord):
                raise TypeError("core index repository returned invalid commit evidence")
            committed_results.append(result)

        committed_session = None
        committed_previous_session = None
        if request.session is not None:
            if request.previous_session is not None:
                stored_previous_session = (
                    unit_of_work.trading_sessions.put_session_if_absent(
                        TradingSessionRecord(
                            as_of=request.previous_session.as_of,
                            previous_as_of=request.previous_session.previous_as_of,
                            is_session=request.previous_session.is_session,
                            source=request.previous_session.source,
                            actual_as_of=request.previous_session.actual_as_of,
                            fetched_at=request.previous_session.fetched_at,
                            warnings=request.previous_session.warnings,
                        )
                    )
                )
                if not isinstance(stored_previous_session, TradingSessionRecord):
                    raise TypeError(
                        "previous trading-session repository returned invalid evidence"
                    )
                if (
                    stored_previous_session.as_of != request.previous_session.as_of
                    or stored_previous_session.actual_as_of
                    != request.previous_session.actual_as_of
                    or not stored_previous_session.is_session
                ):
                    raise ValueError(
                        "stored previous core session conflicts with evidence"
                    )
                committed_previous_session = request.previous_session
            stored_session = unit_of_work.trading_sessions.put_session(
                TradingSessionRecord(
                    as_of=request.session.as_of,
                    previous_as_of=request.session.previous_as_of,
                    is_session=request.session.is_session,
                    source=request.session.source,
                    actual_as_of=request.session.actual_as_of,
                    fetched_at=request.session.fetched_at,
                    warnings=request.session.warnings,
                )
            )
            if not isinstance(stored_session, TradingSessionRecord):
                raise TypeError("trading-session repository returned invalid evidence")
            committed_session = request.session

        stored = (
            existing
            if request.outcome.state is CollectionTaskState.FAILED_RETAINED
            else unit_of_work.snapshots.put(request.candidate)
        )
        if not isinstance(stored, CollectionCandidate):
            raise TypeError("snapshot repository returned invalid core commit evidence")
        if stored.identity != request.identity:
            raise ValueError("snapshot repository returned mismatched core identity")

        warning = request.outcome.warning
        if warning is None and request.candidate.warnings:
            warning = "; ".join(request.candidate.warnings)
        updated_task = replace(
            task,
            status=request.outcome.state.value,
            source=request.candidate.source,
            observations=request.candidate.observations,
            warning=warning,
            timings=dict(request.task_timings),
            completed_at=request.completed_at,
            duration_ms=request.duration_ms,
            settled=request.candidate.settled,
        )
        stored_task = unit_of_work.collection_tasks.save_task(updated_task)
        if not isinstance(stored_task, CollectionTaskRecord):
            raise TypeError("collection task repository returned invalid core evidence")
        if stored_task.status != request.outcome.state.value:
            raise ValueError("core task state was not committed atomically")
        return (
            stored,
            stored_task,
            tuple(committed_results),
            committed_session,
            committed_previous_session,
        )

    @staticmethod
    def _retained_payloads(
        candidate: CollectionCandidate | None,
    ) -> dict[str, Mapping[str, object]]:
        if candidate is None:
            return {}
        indices = candidate.payload.get("indices")
        if not isinstance(indices, (list, tuple)):
            return {}
        return {
            str(value["code"]): value
            for value in indices
            if isinstance(value, Mapping) and str(value.get("code") or "").strip()
        }


__all__ = ["CoreDatasetCommitter"]
