"""Vendor-neutral acquisition ports used by dataset plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ...domain.models import (
    AcquisitionFailure,
    CollectionCandidate,
    CollectionOutcome,
    DatasetDate,
)


@dataclass(frozen=True, slots=True)
class SourceCapability:
    """Declared source/date/field capability; no transport type leaks here."""

    source_id: str
    provider: str
    revision: str
    supports_historical: bool = True
    latest_only: bool = False
    supported_fields: tuple[str, ...] = ()
    methods: tuple[str, ...] = ("GET",)
    available: bool = True

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.provider.strip() or not self.revision.strip():
            raise ValueError("source capability requires source, provider and revision")
        if self.latest_only and self.supports_historical:
            raise ValueError("latest-only source cannot support historical dates")
        if any(not field_name.strip() for field_name in self.supported_fields):
            raise ValueError("source capability fields must not be empty")
        if any(not method.strip() for method in self.methods):
            raise ValueError("source capability methods must not be empty")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    """Normalized request passed from a dataset plan to one source adapter."""

    identity: DatasetDate
    source_id: str
    role: str = "formal"
    params: Mapping[str, object] = field(default_factory=dict)
    capability_revision: str | None = None
    current_market_date: date | None = None
    settled: bool | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source request requires a source id")
        if self.role not in {"formal", "fallback", "shadow", "enrichment"}:
            raise ValueError(f"unsupported source request role: {self.role}")


SourceResult = CollectionCandidate | AcquisitionFailure


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str
    capability: SourceCapability

    def acquire(self, request: SourceRequest) -> SourceResult: ...


@runtime_checkable
class AcquisitionPlan(Protocol):
    dataset_id: str
    plan_id: str
    steps: tuple["AcquisitionPlanStep", ...]

    def collect(self, identity: DatasetDate) -> CollectionOutcome: ...


@dataclass(frozen=True, slots=True)
class AcquisitionPlanStep:
    adapter_id: str
    role: str = "formal"
    capability_revision: str | None = None
    enabled: bool = True
    approved_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.adapter_id.strip():
            raise ValueError("acquisition plan step requires adapter id")
        if self.role not in {"formal", "fallback", "shadow", "enrichment"}:
            raise ValueError(f"unsupported acquisition plan step role: {self.role}")
        if self.role != "enrichment" and self.approved_fields:
            raise ValueError("approved fields are only valid for enrichment steps")


__all__ = [
    "AcquisitionPlan",
    "AcquisitionPlanStep",
    "SourceAdapter",
    "SourceCapability",
    "SourceRequest",
    "SourceResult",
]
