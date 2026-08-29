"""API response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MovingAverages(BaseModel):
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None


class DataQuality(BaseModel):
    source: str
    isStale: bool
    warning: str | None


class HistoryPoint(BaseModel):
    date: str
    close: float
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    amount: float


class IndexAnalysis(BaseModel):
    code: str
    name: str
    representative: str
    changePct: float
    close: float
    movingAverages: MovingAverages
    rangePosition20: float | None
    rangePosition60: float | None
    rangePosition20Label: str
    rangePosition60Label: str
    amount: float
    amountRatio5: float | None
    amountRatio20: float | None
    trendState: str
    volumePriceState: str
    history: list[HistoryPoint]
    dataQuality: DataQuality


class Summary(BaseModel):
    synchronization: str
    dominantTrend: str
    warnings: list[str]


class MarketEnvironmentResponse(BaseModel):
    asOf: str
    generatedAt: str
    indices: list[IndexAnalysis]
    summary: Summary


def schema_extra(value: Any) -> Any:
    return value

