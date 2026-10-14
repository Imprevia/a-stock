"""Collection status and command routes."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from ....collection import manual_refresh_enabled
from ....application.ths_diagnostics import ths_warning_response
from ..schemas.models import (
    CollectionRunRequest,
    CollectionRunResponse,
    CollectionStatusResponse,
)
from ..dependencies import (
    CollectionCommands,
    CollectionQueries,
    get_collection_commands,
    get_collection_queries,
    get_effective_market_date,
)
from ..errors import (
    raise_application_error,
    raise_forbidden,
    raise_not_found,
    raise_unprocessable,
)
from ..schemas import map_collection_run, map_collection_status


router = APIRouter()
THS_DATASETS = frozenset(
    {"industry-ranking", "sector-turnover", "sector-breadth"}
)


def _catalog_revision_id(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _normalize_ths_quality(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    quality = dict(value)
    revision = _catalog_revision_id(
        quality.pop("catalogRevisionId", None),
        quality.pop("catalogRevision", None),
        quality.pop("revisionId", None),
    )
    if revision is not None:
        quality["catalogRevisionId"] = revision
    aliases = {
        "expectedCodes": "expectedCount",
        "observedCodes": "observedCount",
        "rankableCodes": "rankableCount",
        "storedCodes": "usableCount",
        "barCodes": "barCount",
    }
    for legacy, public in aliases.items():
        if public not in quality and legacy in quality:
            quality[public] = quality.pop(legacy)
        else:
            quality.pop(legacy, None)
    for name in ("missingLiveCodes", "missingRankingCodes"):
        codes = quality.get(name)
        if isinstance(codes, (list, tuple, set, frozenset)):
            unique_codes = sorted({str(code) for code in codes})
            count_name = (
                "missingLiveCount"
                if name == "missingLiveCodes"
                else "missingRankingCount"
            )
            quality.setdefault(count_name, len(unique_codes))
            quality[name] = unique_codes[:20]
    diagnostic = None
    warning = quality.get("warning")
    if isinstance(warning, str):
        message, diagnostic = ths_warning_response(warning)
        quality["warning"] = message
    warnings = quality.get("warnings")
    if isinstance(warnings, (list, tuple)):
        safe_warnings: list[object] = []
        for item in warnings:
            if isinstance(item, str):
                message, parsed = ths_warning_response(item)
                safe_warnings.append(message)
                diagnostic = diagnostic or parsed
            else:
                safe_warnings.append(item)
        quality["warnings"] = safe_warnings
    if diagnostic is not None:
        quality["diagnostics"] = diagnostic
    return quality


def _validate_as_of(as_of: date, effective_date: date) -> None:
    if as_of > effective_date:
        raise_unprocessable("as_of 不能晚于当前有效市场日")


def _resolve_as_of(as_of: date | None, effective_date: date) -> date:
    return as_of if as_of is not None else effective_date


def _attempt_payload(record) -> dict | None:
    if record is None:
        return None
    timings = dict(record.timings or {})
    warning = record.warning
    diagnostics = None
    if record.dataset in THS_DATASETS:
        warning, diagnostics = ths_warning_response(record.warning)
    revision = _catalog_revision_id(
        diagnostics.get("catalogRevisionId") if diagnostics else None,
        timings.pop("catalogRevisionId", None),
        timings.pop("catalogRevision", None),
    )
    if revision is not None:
        timings["catalogRevisionId"] = revision
    return {
        "taskId": record.task_id,
        "runId": record.run_id,
        "status": record.status,
        "source": record.source,
        "observations": record.observations,
        "warning": warning,
        "diagnostics": diagnostics,
        "catalogRevisionId": revision,
        "queuedAt": record.queued_at,
        "startedAt": record.started_at,
        "completedAt": record.completed_at,
        "durationMs": record.duration_ms,
        "settled": record.settled,
        "timings": timings,
    }


def _core_index_payload(record) -> dict:
    return {
        "code": record.code,
        "name": record.name,
        "status": record.status,
        "source": record.source,
        "observations": record.observations,
        "warning": record.warning,
        "durationMs": record.duration_ms,
    }


def _attempt_payload_with_detail(record, detail) -> dict | None:
    base = _attempt_payload(record)
    if base is None:
        return None
    if detail is not None:
        base["sampleAsOf"] = detail.get("sampleAsOf")
        base["previousAsOf"] = detail.get("previousAsOf")
        base["excludedCount"] = detail.get("excludedCount")
        base["promotionQuality"] = detail.get("promotionQuality")
        base["promotionDependency"] = detail.get("promotionDependency")
        base["warnings"] = list(detail.get("warnings") or [])
    return base


def _task_payload(record, core_indices: Iterable, detail) -> dict:
    payload = _attempt_payload(record) or {}
    payload.pop("runId", None)
    payload.update({
        "dataset": record.dataset,
        "asOf": record.as_of,
        "coreIndices": [_core_index_payload(item) for item in core_indices],
        "detail": detail,
    })
    return payload


def _run_payload(result, *, extras) -> dict:
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
        "tasks": [
            _task_payload(
                task,
                extras[task.task_id]["coreIndices"],
                extras[task.task_id]["detail"],
            )
            for task in result.tasks
        ],
    }


def _build_task_extras(*, raw_status: dict, result) -> dict[str, dict]:
    dataset_index = {item["dataset"]: item for item in raw_status.get("datasets", [])}
    extras: dict[str, dict] = {}
    for task in result.tasks:
        item = dataset_index.get(task.dataset, {})
        detail = item.get("detail") if task.dataset == "limits" else None
        core_results = item.get("coreIndices") if task.dataset == "core" else ()
        core_indices = core_results if isinstance(core_results, (list, tuple)) else ()
        extras[task.task_id] = {"detail": detail, "coreIndices": core_indices}
    return extras


def _collection_status_response_payload(queries: CollectionQueries, as_of: date) -> dict:
    raw = queries.collection_status(as_of)
    datasets: list[dict] = []
    for item in raw["datasets"]:
        attempt = item.get("latestAttempt")
        detail = item.get("detail") if item["dataset"] == "limits" else None
        core_indices = item.get("coreIndices") or ()
        quality = (
            _normalize_ths_quality(item.get("quality"))
            if item["dataset"] in THS_DATASETS
            else item.get("quality")
        )
        attempt_payload = _attempt_payload_with_detail(attempt, detail)
        catalog_revision_id = _catalog_revision_id(
            quality.get("catalogRevisionId") if quality else None,
            attempt_payload.get("catalogRevisionId") if attempt_payload else None,
        )
        datasets.append(
            {
                "dataset": item["dataset"],
                "available": item.get("available"),
                "source": item.get("source"),
                "observations": item.get("observations"),
                "lastSuccessAt": item.get("lastSuccessAt"),
                "settled": item.get("settled"),
                "refreshWarning": item.get("refreshWarning"),
                "quality": quality,
                "catalogRevisionId": catalog_revision_id,
                "activeTaskId": item.get("activeTaskId"),
                "collectionAllowed": item.get("collectionAllowed"),
                "restriction": item.get("restriction"),
                "latestAttempt": attempt_payload,
                "coreIndices": [_core_index_payload(value) for value in core_indices],
                "detail": detail,
            }
        )
    return {
        "asOf": raw["asOf"],
        "datasets": datasets,
        "sectorAnalysis": raw.get("sectorAnalysis"),
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
    try:
        payload = _collection_status_response_payload(queries, as_of)
        return map_collection_status(
            payload,
            manual_refresh_enabled=manual_refresh_enabled(),
        )
    except Exception as error:
        raise_application_error(error)


@router.post(
    "/api/market-environment/collection-runs",
    response_model=CollectionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_market_environment_collection(
    body: CollectionRunRequest,
    commands: Annotated[CollectionCommands, Depends(get_collection_commands)],
    queries: Annotated[CollectionQueries, Depends(get_collection_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
) -> dict:
    _validate_as_of(body.asOf, effective_date)
    if not manual_refresh_enabled():
        raise_forbidden("手工数据采集未启用")
    try:
        result = commands.start_run(body.asOf, body.datasets)
        raw_status = queries.collection_status(body.asOf)
        extras = _build_task_extras(raw_status=raw_status, result=result)
        commands.submit_run(result.run.run_id)
        return map_collection_run(_run_payload(result, extras=extras))
    except Exception as error:
        raise_application_error(error)


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
    raw_status = queries.collection_status(result.run.as_of)
    extras = _build_task_extras(raw_status=raw_status, result=result)
    try:
        return map_collection_run(_run_payload(result, extras=extras))
    except Exception as error:
        raise_application_error(error)


__all__ = ["router"]
