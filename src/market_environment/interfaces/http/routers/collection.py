"""Collection status and command routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from ....collection import manual_refresh_enabled
from ....schemas import (
    CollectionRunRequest,
    CollectionRunResponse,
    CollectionStatusResponse,
)
from ....snapshot_store import CollectionTaskRecord, CoreIndexResultRecord
from ..dependencies import (
    CollectionCommands,
    CollectionQueries,
    get_collection_commands,
    get_collection_queries,
    get_effective_market_date,
    unwrap_collection_coordinator,
)
from ..errors import (
    raise_application_error,
    raise_forbidden,
    raise_not_found,
    raise_unprocessable,
)


router = APIRouter()


def _validate_as_of(as_of: date, effective_date: date) -> None:
    if as_of > effective_date:
        raise_unprocessable("as_of 不能晚于当前有效市场日")


def _resolve_as_of(as_of: date | None, effective_date: date) -> date:
    return as_of if as_of is not None else effective_date


def _core_index_payload(record: CoreIndexResultRecord) -> dict:
    return {
        "code": record.code,
        "name": record.name,
        "status": record.status,
        "source": record.source,
        "observations": record.observations,
        "warning": record.warning,
        "durationMs": record.duration_ms,
    }


def _task_payload(record: CollectionTaskRecord, coordinator) -> dict:
    store = coordinator.store
    core_indices = (
        store.list_core_index_results(record.task_id)
        if record.dataset == "core"
        else ()
    )
    detail = (
        coordinator._limits_collection_detail(
            store.get("limits", record.as_of),
            record.as_of,
        )
        if record.dataset == "limits"
        else None
    )
    return {
        "taskId": record.task_id,
        "dataset": record.dataset,
        "asOf": record.as_of,
        "status": record.status,
        "source": record.source,
        "observations": record.observations,
        "warning": record.warning,
        "timings": record.timings or {},
        "queuedAt": record.queued_at,
        "startedAt": record.started_at,
        "completedAt": record.completed_at,
        "durationMs": record.duration_ms,
        "settled": record.settled,
        "coreIndices": [_core_index_payload(item) for item in core_indices],
        "detail": detail,
    }


def _run_payload(result, coordinator) -> dict:
    completed = sum(task.status not in {"queued", "collecting"} for task in result.tasks)
    return {
        "runId": result.run.run_id,
        "asOf": result.run.as_of,
        "status": result.run.status,
        "requestedDatasets": list(result.run.requested_datasets),
        "completedTasks": completed,
        "totalTasks": len(result.tasks),
        "createdAt": result.run.created_at,
        "startedAt": result.run.started_at,
        "completedAt": result.run.completed_at,
        "tasks": [_task_payload(task, coordinator) for task in result.tasks],
    }


@router.get(
    "/api/market-environment/data-collection",
    response_model=CollectionStatusResponse,
)
def market_environment_collection_status(
    queries: Annotated[CollectionQueries, Depends(get_collection_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    as_of: date | None = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    as_of = _resolve_as_of(as_of, effective_date)
    _validate_as_of(as_of, effective_date)
    result = queries.collection_status(as_of)
    datasets = []
    for item in result["datasets"]:
        attempt = item["latestAttempt"]
        detail = item.get("detail") if item["dataset"] == "limits" else None
        datasets.append(
            {
                **item,
                "latestAttempt": None
                if attempt is None
                else {
                    "taskId": attempt.task_id,
                    "runId": attempt.run_id,
                    "status": attempt.status,
                    "source": attempt.source,
                    "observations": attempt.observations,
                    "warning": attempt.warning,
                    "queuedAt": attempt.queued_at,
                    "startedAt": attempt.started_at,
                    "completedAt": attempt.completed_at,
                    "durationMs": attempt.duration_ms,
                    "settled": attempt.settled,
                    "timings": attempt.timings or {},
                    "sampleAsOf": detail.get("sampleAsOf") if detail else None,
                    "previousAsOf": detail.get("previousAsOf") if detail else None,
                    "excludedCount": detail.get("excludedCount") if detail else None,
                    "promotionQuality": detail.get("promotionQuality") if detail else None,
                    "promotionDependency": detail.get("promotionDependency") if detail else None,
                    "warnings": detail.get("warnings", []) if detail else [],
                },
                "coreIndices": [_core_index_payload(value) for value in item["coreIndices"]],
                "detail": detail,
            }
        )
    return {
        "asOf": result["asOf"],
        "manualRefreshEnabled": manual_refresh_enabled(),
        "datasets": datasets,
    }


@router.post(
    "/api/market-environment/collection-runs",
    response_model=CollectionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_market_environment_collection(
    body: CollectionRunRequest,
    commands: Annotated[CollectionCommands, Depends(get_collection_commands)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
) -> dict:
    _validate_as_of(body.asOf, effective_date)
    if not manual_refresh_enabled():
        raise_forbidden("手工数据采集未启用")
    try:
        result = commands.start_run(body.asOf, body.datasets)
    except Exception as error:
        raise_application_error(error)
    commands.submit_run(result.run.run_id)
    return _run_payload(result, unwrap_collection_coordinator(commands))


@router.get(
    "/api/market-environment/collection-runs/{run_id}",
    response_model=CollectionRunResponse,
)
def market_environment_collection_run(
    run_id: str,
    queries: Annotated[CollectionQueries, Depends(get_collection_queries)],
) -> dict:
    result = queries.get_run(run_id)
    if result is None:
        raise_not_found("采集批次不存在")
    return _run_payload(result, unwrap_collection_coordinator(queries))


__all__ = ["router"]
