"""Dedicated DTOs for the bounded v2 market-data read API.

This module deliberately does not import or inherit the legacy aggregate or
Chapter 01 response models.  Resource-specific routers can parameterize the
shared envelope with a narrow data model.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


V2QualityStatus = Literal[
    "ok",
    "partial",
    "fallback",
    "fallback-derived",
    "missing",
    "insufficient",
    "degraded",
    "failed",
    "failed-retained",
    "failed-missing",
    "unverified",
]
V2CacheState = Literal["fresh", "stale", "missing"]
V2Scalar = str | int | float | bool | None
T = TypeVar("T")


class V2StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class V2Quality(V2StrictModel):
    status: V2QualityStatus
    source: str | None = None
    provider: str | None = None
    actualDate: date | None = None
    observations: int | None = Field(default=None, ge=0)
    cacheState: V2CacheState | None = None
    isStale: bool | None = None
    fetchedAt: datetime | None = None
    evidenceRevision: str | None = None
    checksum: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=50)


class V2Link(V2StrictModel):
    relation: str
    href: str
    resource: str
    method: Literal["GET"] = "GET"
    title: str | None = None
    templated: bool = False


class V2Pagination(V2StrictModel):
    limit: int = Field(ge=1)
    returned: int = Field(ge=0)
    hasMore: bool
    nextCursor: str | None = None


class V2Error(V2StrictModel):
    code: str
    message: str
    parameter: str | None = None
    requestedSnapshotRevision: str | None = None
    currentSnapshotRevision: str | None = None


class V2ErrorResponse(V2StrictModel):
    error: V2Error


class V2Envelope(V2StrictModel, Generic[T]):
    asOf: date
    generatedAt: datetime
    snapshotRevision: str = Field(min_length=1)
    quality: V2Quality
    data: T
    links: list[V2Link] = Field(default_factory=list)


class V2PaginatedEnvelope(V2Envelope[T], Generic[T]):
    pagination: V2Pagination


class V2Metric(V2StrictModel):
    code: str
    label: str
    value: V2Scalar
    unit: str | None = None
    status: V2QualityStatus | None = None
    evidence: list[str] = Field(default_factory=list, max_length=20)


class V2Conclusion(V2StrictModel):
    code: str
    label: str
    summary: str | None = None
    status: V2QualityStatus | None = None
    evidence: list[str] = Field(default_factory=list, max_length=20)


class V2ResourceAvailability(V2StrictModel):
    resource: str
    available: bool
    quality: V2Quality
    href: str | None = None


class V2OverviewData(V2StrictModel):
    conclusions: list[V2Conclusion] = Field(default_factory=list)
    resources: list[V2ResourceAvailability] = Field(default_factory=list)


class V2ResourceData(V2StrictModel):
    """Typed compact data shared by scalar resource summaries."""

    metrics: list[V2Metric] = Field(default_factory=list)
    conclusions: list[V2Conclusion] = Field(default_factory=list)


class V2Identity(V2StrictModel):
    code: str
    name: str | None = None


class V2Observation(V2StrictModel):
    """Common bounded row shape extended by resource-specific DTOs."""

    identity: V2Identity
    rank: int | None = Field(default=None, ge=1)
    asOf: date | None = None
    metrics: list[V2Metric] = Field(default_factory=list)
    quality: V2Quality | None = None


class V2CollectionData(V2StrictModel, Generic[T]):
    items: list[T] = Field(default_factory=list)


class V2HistoryPoint(V2StrictModel):
    asOf: date
    metrics: list[V2Metric] = Field(default_factory=list)


class V2OverviewEnvelope(V2Envelope[V2OverviewData]):
    pass


class V2ResourceEnvelope(V2Envelope[V2ResourceData]):
    pass


class V2ObservationCollectionEnvelope(
    V2PaginatedEnvelope[V2CollectionData[V2Observation]]
):
    pass


class V2HistoryEnvelope(V2PaginatedEnvelope[V2CollectionData[V2HistoryPoint]]):
    pass


__all__ = [
    "V2CacheState",
    "V2CollectionData",
    "V2Conclusion",
    "V2Envelope",
    "V2Error",
    "V2ErrorResponse",
    "V2HistoryEnvelope",
    "V2HistoryPoint",
    "V2Identity",
    "V2Link",
    "V2Metric",
    "V2Observation",
    "V2ObservationCollectionEnvelope",
    "V2OverviewData",
    "V2OverviewEnvelope",
    "V2PaginatedEnvelope",
    "V2Pagination",
    "V2Quality",
    "V2QualityStatus",
    "V2ResourceAvailability",
    "V2ResourceData",
    "V2ResourceEnvelope",
]
