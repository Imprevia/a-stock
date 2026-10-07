"""Provider-free market-environment query routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ....schemas import (
    Chapter01Response,
    MarketEnvironmentResponse,
    NextSessionComparisonResponse,
)
from ..dependencies import (
    MarketEnvironmentQueries,
    get_effective_market_date,
    get_market_queries,
)
from ..errors import raise_application_error, raise_unprocessable
from ..schemas import map_chapter01, map_market_environment, map_next_session


router = APIRouter()
ChapterSection = Literal["breadth", "limits", "sectors", "activeDirection", "summary"]


def _validate_as_of(as_of: date, effective_date: date) -> None:
    if as_of > effective_date:
        raise_unprocessable("as_of 不能晚于当前有效市场日")


def _resolve_as_of(as_of: date | None, effective_date: date) -> date:
    return as_of if as_of is not None else effective_date


@router.get("/api/market-environment", response_model=MarketEnvironmentResponse)
def market_environment(
    queries: Annotated[MarketEnvironmentQueries, Depends(get_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    as_of: date | None = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    as_of = _resolve_as_of(as_of, effective_date)
    _validate_as_of(as_of, effective_date)
    try:
        return map_market_environment(queries.get(as_of))
    except Exception as error:
        raise_application_error(error)


@router.get("/api/market-environment/core", response_model=MarketEnvironmentResponse)
def market_environment_core(
    queries: Annotated[MarketEnvironmentQueries, Depends(get_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    as_of: date | None = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
) -> dict:
    as_of = _resolve_as_of(as_of, effective_date)
    _validate_as_of(as_of, effective_date)
    try:
        return map_market_environment(queries.get_core(as_of))
    except Exception as error:
        raise_application_error(error)


@router.get(
    "/api/market-environment/next-session",
    response_model=NextSessionComparisonResponse,
)
def market_environment_next_session(
    queries: Annotated[MarketEnvironmentQueries, Depends(get_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    as_of: date | None = Query(default=None, description="当前交易日，格式 YYYY-MM-DD"),
) -> dict:
    as_of = _resolve_as_of(as_of, effective_date)
    _validate_as_of(as_of, effective_date)
    try:
        return map_next_session(queries.get_next_session_comparison(as_of))
    except Exception as error:
        raise_application_error(error)


@router.get("/api/market-environment/chapter-01", response_model=Chapter01Response)
def market_environment_chapter01(
    queries: Annotated[MarketEnvironmentQueries, Depends(get_market_queries)],
    effective_date: Annotated[date, Depends(get_effective_market_date)],
    as_of: date | None = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
    section: ChapterSection = Query(description="按需加载的第 01 章数据集"),
) -> dict:
    as_of = _resolve_as_of(as_of, effective_date)
    _validate_as_of(as_of, effective_date)
    try:
        return map_chapter01(queries.get_chapter01(as_of, section))
    except Exception as error:
        raise_application_error(error)


__all__ = ["ChapterSection", "router"]
