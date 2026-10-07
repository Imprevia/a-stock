"""Timezone preference routes and response-context middleware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..schemas.models import (
    TimezonePreferenceUpdateRequest,
    TimezonePreferencesResponse,
)
from ....timezone_preferences import (
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    resolve_timezone,
)
from ..dependencies import (
    TimezonePreferenceCommands,
    TimezonePreferenceQueries,
    get_timezone_commands,
    get_timezone_queries,
)
from ..errors import raise_forbidden
from ..schemas import map_timezone_preferences


router = APIRouter()


@dataclass(frozen=True)
class RequestIdentity:
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
    return _header(request, "x-timezone", "x-user-timezone", "x-browser-timezone")


def _timezone_preferences_payload(
    request: Request,
    repository: TimezonePreferenceQueries,
) -> dict:
    identity = _request_identity(request)
    personal = repository.get(
        "personal",
        subject_id=identity.user_id,
        workspace_id=identity.workspace_id,
    )
    workspace = repository.get(
        "workspace",
        subject_id=identity.user_id,
        workspace_id=identity.workspace_id,
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
    if source == "utc-fallback" and (
        personal.timezone or workspace.timezone or _browser_timezone(request)
    ):
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


def _map_timezone_preferences(
    request: Request,
    repository: TimezonePreferenceQueries,
) -> dict:
    return map_timezone_preferences(_timezone_preferences_payload(request, repository))


async def attach_timezone_context(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        try:
            if (
                not getattr(request.app.state, "lifespan_started", False)
                and getattr(request.app.state, "container", None) is None
            ):
                raise RuntimeError("lifespan is not active")
            context = _map_timezone_preferences(
                request,
                get_timezone_queries(request),
            )
            response.headers["X-Effective-Timezone"] = context["effectiveTimeZone"]
            response.headers["X-Timezone-Source"] = context["effectiveSource"]
        except Exception:
            response.headers["X-Effective-Timezone"] = "UTC"
            response.headers["X-Timezone-Source"] = "utc-fallback"
    return response


@router.get(
    "/api/preferences/timezone",
    response_model=TimezonePreferencesResponse,
)
def get_timezone_preferences(
    request: Request,
    queries: Annotated[TimezonePreferenceQueries, Depends(get_timezone_queries)],
) -> dict:
    return _map_timezone_preferences(request, queries)


@router.put(
    "/api/preferences/timezone",
    response_model=TimezonePreferencesResponse,
)
def update_timezone_preferences(
    request: Request,
    body: TimezonePreferenceUpdateRequest,
    queries: Annotated[TimezonePreferenceQueries, Depends(get_timezone_queries)],
    commands: Annotated[TimezonePreferenceCommands, Depends(get_timezone_commands)],
) -> dict:
    identity = _request_identity(request)
    if body.scope == "workspace" and not identity.can_manage_workspace:
        raise_forbidden("当前账号没有修改工作区时区的权限")
    commands.set(
        body.scope,
        subject_id=identity.user_id,
        workspace_id=identity.workspace_id,
        timezone_value=body.timezone,
        actor_id=identity.user_id,
    )
    return _map_timezone_preferences(request, queries)


__all__ = ["attach_timezone_context", "router"]
