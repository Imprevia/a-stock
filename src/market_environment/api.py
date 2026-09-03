"""FastAPI entrypoint for the market environment dashboard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .collection import CollectionCoordinator, manual_refresh_enabled
from .schemas import (
    Chapter01Response,
    CollectionRunRequest,
    CollectionRunResponse,
    CollectionStatusResponse,
    MarketEnvironmentResponse,
)
from .service import MarketEnvironmentService, market_today
from .snapshot_store import CollectionTaskRecord, CoreIndexResultRecord, SnapshotStore

app = FastAPI(title="市场环境分析 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
service = MarketEnvironmentService()
collection_store = service.snapshot_store or SnapshotStore()
collection_coordinator = CollectionCoordinator(
    service.provider,
    collection_store,
    rebuild_aggregate=service.rebuild_materialized_aggregate,
)
collection_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-collection")
ChapterSection = Literal["breadth", "limits", "sectors", "activeDirection", "summary"]


def _validate_as_of(as_of: date) -> None:
    if as_of > market_today():
        raise HTTPException(status_code=422, detail="as_of 不能晚于当前日期")


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


def _task_payload(record: CollectionTaskRecord) -> dict:
    store = collection_coordinator.store
    core_indices = (
        store.list_core_index_results(record.task_id)
        if record.dataset == "core"
        else ()
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
    }


def _run_payload(result) -> dict:
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
        "tasks": [_task_payload(task) for task in result.tasks],
    }


@app.get("/api/market-environment", response_model=MarketEnvironmentResponse)
def market_environment(
    as_of: date = Query(default_factory=market_today, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    _validate_as_of(as_of)
    try:
        return service.get(as_of)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/market-environment/core", response_model=MarketEnvironmentResponse)
def market_environment_core(
    as_of: date = Query(default_factory=market_today, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    _validate_as_of(as_of)
    try:
        return service.get_core(as_of)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/market-environment/chapter-01", response_model=Chapter01Response)
def market_environment_chapter01(
    as_of: date = Query(default_factory=market_today, description="交易日，格式 YYYY-MM-DD"),
    section: ChapterSection = Query(description="按需加载的第 01 章数据集"),
) -> dict:
    _validate_as_of(as_of)
    try:
        return service.get_chapter01(as_of, section)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(
    "/api/market-environment/data-collection",
    response_model=CollectionStatusResponse,
)
def market_environment_collection_status(
    as_of: date = Query(default_factory=market_today, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    _validate_as_of(as_of)
    result = collection_coordinator.collection_status(as_of)
    datasets = []
    for item in result["datasets"]:
        attempt = item["latestAttempt"]
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
                },
                "coreIndices": [_core_index_payload(value) for value in item["coreIndices"]],
            }
        )
    return {
        "asOf": result["asOf"],
        "manualRefreshEnabled": manual_refresh_enabled(),
        "datasets": datasets,
    }


@app.post(
    "/api/market-environment/collection-runs",
    response_model=CollectionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_market_environment_collection(request: CollectionRunRequest) -> dict:
    _validate_as_of(request.asOf)
    if not manual_refresh_enabled():
        raise HTTPException(status_code=403, detail="手工数据采集未启用")
    try:
        result = collection_coordinator.start_run(request.asOf, request.datasets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    collection_executor.submit(collection_coordinator.execute_run, result.run.run_id)
    return _run_payload(result)


@app.get(
    "/api/market-environment/collection-runs/{run_id}",
    response_model=CollectionRunResponse,
)
def market_environment_collection_run(run_id: str) -> dict:
    result = collection_coordinator.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="采集批次不存在")
    return _run_payload(result)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


static_dir = Path(__file__).resolve().parents[2] / "apps" / "market-environment-dashboard" / "dist"
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}")
    def serve_frontend(path: str) -> FileResponse:
        candidate = static_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
