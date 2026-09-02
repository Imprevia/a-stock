"""FastAPI entrypoint for the market environment dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .schemas import Chapter01Response, MarketEnvironmentResponse
from .service import MarketEnvironmentService, market_today

app = FastAPI(title="市场环境分析 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
service = MarketEnvironmentService()
ChapterSection = Literal["breadth", "limits", "sectors", "activeDirection", "summary"]


def _validate_as_of(as_of: date) -> None:
    if as_of > market_today():
        raise HTTPException(status_code=422, detail="as_of 不能晚于当前日期")


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
