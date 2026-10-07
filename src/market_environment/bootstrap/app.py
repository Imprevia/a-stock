"""FastAPI application factory and runtime resource lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .container import (
    ApplicationContainer,
    ContainerAdapters,
    build_container,
)
from .settings import MarketEnvironmentSettings


ContainerFactory = Callable[[], ApplicationContainer]


def create_app(
    settings: MarketEnvironmentSettings | None = None,
    overrides: ApplicationContainer | ContainerAdapters | ContainerFactory | None = None,
    *,
    router: APIRouter | None = None,
    http_middleware: Iterable[Callable[..., Any]] = (),
) -> FastAPI:
    """Create the HTTP application without opening runtime resources."""

    if router is None:
        from ..interfaces.http.router import api_router
        from ..interfaces.http.routers.timezone_preferences import (
            attach_timezone_context,
        )

        router = api_router
        http_middleware = (attach_timezone_context,)

    factory = _container_factory(settings, overrides)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.lifespan_started = True
        container = get_app_container(app)
        try:
            yield
        finally:
            container.close()
            app.state.lifespan_started = False

    app = FastAPI(
        title="市场环境分析 API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.container_factory = factory
    app.state.lifespan_started = False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    for middleware in http_middleware:
        app.middleware("http")(middleware)
    app.include_router(router)
    _mount_frontend(app)
    return app


def get_app_container(app: FastAPI) -> ApplicationContainer:
    """Return the lifespan container, lazily supporting legacy direct clients."""

    container = getattr(app.state, "container", None)
    if container is None:
        container = app.state.container_factory()
        app.state.container = container
    return container


def _container_factory(
    settings: MarketEnvironmentSettings | None,
    overrides: ApplicationContainer | ContainerAdapters | ContainerFactory | None,
) -> ContainerFactory:
    if isinstance(overrides, ApplicationContainer):
        return lambda: overrides
    if callable(overrides) and not isinstance(overrides, ContainerAdapters):
        return overrides
    return lambda: build_container(settings, adapters=overrides)


def _mount_frontend(app: FastAPI) -> None:
    static_dir = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "market-environment-dashboard"
        / "dist"
    )
    if not static_dir.is_dir():
        return
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    def serve_frontend(path: str) -> FileResponse:
        candidate = static_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")

    app.add_api_route("/{path:path}", serve_frontend, methods=["GET"])


__all__ = ["create_app", "get_app_container"]
