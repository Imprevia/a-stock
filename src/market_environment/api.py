"""FastAPI entrypoint for the market environment dashboard."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
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
    TimezonePreferenceUpdateRequest,
    TimezonePreferencesResponse,
)
from .service import MarketEnvironmentService, market_today
from .snapshot_store import CollectionTaskRecord, CoreIndexResultRecord, SnapshotStore
from .timezone_preferences import (
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    TimezonePreferenceStore,
    resolve_timezone,
)

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
timezone_preference_store = TimezonePreferenceStore(collection_store.path)
ChapterSection = Literal["breadth", "limits", "sectors", "activeDirection", "summary"]


@dataclass(frozen=True)
class RequestIdentity:
    """Small adapter seam for the platform identity provider.

    Until the host platform supplies auth middleware, local/dev callers may
    provide ``X-User-ID``, ``X-Workspace-ID`` and an explicit admin role.  A
    missing identity is treated as an anonymous read-only subject so the
    dashboard remains usable without making workspace writes permissive.
    """

    user_id: str
    workspace_id: str
    can_manage_workspace: bool


def _header(request: Request, *names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _request_identity(request: Request) -> RequestIdentity:
    user_id = _header(request, "x-user-id", "x-actor-id", "x-user") or DEFAULT_USER_ID
    workspace_id = _header(request, "x-workspace-id", "x-workspace") or DEFAULT_WORKSPACE_ID
    role = (_header(request, "x-workspace-role", "x-user-role") or "").lower()
    admin_flag = (_header(request, "x-workspace-admin") or "").lower()
    can_manage = role in {"admin", "owner", "workspace_admin", "workspace-admin"} or admin_flag in {
        "1",
        "true",
        "yes",
        "on",
    }
    return RequestIdentity(user_id[:256], workspace_id[:256], can_manage)


def _browser_timezone(request: Request) -> str | None:
    # The browser UI resolves its own timezone, but accepting this optional
    # hint lets API consumers obtain the same effective-timezone contract.
    return _header(request, "x-timezone", "x-user-timezone", "x-browser-timezone")


def _timezone_preferences_payload(request: Request) -> dict:
    identity = _request_identity(request)
    personal = timezone_preference_store.get(
        "personal", subject_id=identity.user_id, workspace_id=identity.workspace_id
    )
    workspace = timezone_preference_store.get(
        "workspace", subject_id=identity.user_id, workspace_id=identity.workspace_id
    )
    effective, source = resolve_timezone(
        personal.timezone,
        workspace.timezone,
        _browser_timezone(request),
    )
    updated = max(
        (item.updated_at for item in (personal, workspace) if item.updated_at is not None),
        default=None,
    )
    warning = None
    if source == "utc-fallback" and (personal.timezone or workspace.timezone or _browser_timezone(request)):
        warning = "偏好或浏览器时区无效，已安全回退 UTC。"
    return {
        "personalTimeZone": personal.timezone,
        "workspaceTimeZone": workspace.timezone,
        "effectiveTimeZone": effective,
        "effectiveSource": source,
        "canManageWorkspaceTimeZone": identity.can_manage_workspace,
        "timeZone": effective,
        "timezone": effective,
        "updatedAt": updated,
        "warning": warning,
        "timezoneCapability": {
            "personal": {"read": True, "write": True},
            "workspace": {"read": True, "write": identity.can_manage_workspace},
            "browserFallback": True,
            "utcFallback": True,
        },
    }


@app.middleware("http")
async def attach_timezone_context(request: Request, call_next):
    """Expose the effective display timezone without changing payload values.

    Consumers that aggregate several resource types can use these headers as
    a capability signal; timestamps in JSON remain their original ISO8601
    values for auditability.
    """

    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        try:
            context = _timezone_preferences_payload(request)
            response.headers["X-Effective-Timezone"] = context["effectiveTimeZone"]
            response.headers["X-Timezone-Source"] = context["effectiveSource"]
        except Exception:
            # A preference-store outage must not turn an otherwise healthy
            # read-only market endpoint into a 500; UTC is the safe signal.
            response.headers["X-Effective-Timezone"] = "UTC"
            response.headers["X-Timezone-Source"] = "utc-fallback"
    return response


@app.get(
    "/api/preferences/timezone",
    response_model=TimezonePreferencesResponse,
)
def get_timezone_preferences(request: Request) -> dict:
    """Return persisted preferences and the effective display timezone."""

    return _timezone_preferences_payload(request)


@app.put(
    "/api/preferences/timezone",
    response_model=TimezonePreferencesResponse,
)
def update_timezone_preferences(
    request: Request,
    body: TimezonePreferenceUpdateRequest,
) -> dict:
    """Set or clear a personal/workspace IANA timezone preference."""

    identity = _request_identity(request)
    if body.scope == "workspace" and not identity.can_manage_workspace:
        raise HTTPException(status_code=403, detail="当前账号没有修改工作区时区的权限")
    timezone_preference_store.set(
        body.scope,
        subject_id=identity.user_id,
        workspace_id=identity.workspace_id,
        timezone_value=body.timezone,
        actor_id=identity.user_id,
    )
    return _timezone_preferences_payload(request)


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
    detail = (
        collection_coordinator._limits_collection_detail(
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
