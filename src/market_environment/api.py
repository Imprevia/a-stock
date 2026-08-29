"""FastAPI entrypoint for the market environment dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .schemas import MarketEnvironmentResponse
from .service import MarketEnvironmentService

app = FastAPI(title="市场环境分析 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
service = MarketEnvironmentService()


@app.get("/api/market-environment", response_model=MarketEnvironmentResponse)
def market_environment(
    as_of: date = Query(default_factory=date.today, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    if as_of > date.today():
        raise HTTPException(status_code=422, detail="as_of 不能晚于当前日期")
    try:
        return service.get(as_of)
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

