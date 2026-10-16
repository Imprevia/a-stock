"""Typed provider-free read contracts for the v2 market-data surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, TypeAlias, runtime_checkable


JsonObject: TypeAlias = Mapping[str, Any]
SortKey: TypeAlias = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V2Resource:
    """One exact-date resource plus private consistency metadata.

    ``component_revision`` is deliberately application-private.  The HTTP
    boundary turns it into the opaque public snapshot revision.
    """

    as_of: date | None
    generated_at: str
    component_revision: str
    quality: JsonObject
    data: JsonObject | Sequence[JsonObject] | None


@dataclass(frozen=True, slots=True)
class V2Page:
    """A bounded page whose continuation key is encoded by the HTTP layer."""

    resource: V2Resource
    next_sort_key: SortKey | None = None
    total: int | None = None


@runtime_checkable
class V2MarketDataReadPort(Protocol):
    """Smallest local read boundary used by the v2 query facade."""

    def overview(self, as_of: date) -> V2Resource | None: ...
    def indices(self, as_of: date) -> V2Resource | None: ...
    def index(self, as_of: date, code: str) -> V2Resource | None: ...
    def index_history(
        self,
        as_of: date,
        code: str,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def breadth(self, as_of: date) -> V2Resource | None: ...
    def breadth_history(
        self,
        as_of: date,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def limits(self, as_of: date) -> V2Resource | None: ...
    def limits_pool(
        self,
        as_of: date,
        pool_type: str,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def limits_history(
        self,
        as_of: date,
        *,
        start_date: date | None,
        end_date: date | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def limits_evidence(self, as_of: date) -> V2Resource | None: ...
    def sector_rankings(
        self,
        as_of: date,
        *,
        tag: str | None,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def sector_turnover(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def sector_breadth(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def sector_analysis(self, as_of: date) -> V2Resource | None: ...
    def active_direction(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def events(
        self,
        as_of: date,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...
    def assessment(self, as_of: date) -> V2Resource | None: ...
    def operation_summary(self, run_id: str) -> V2Resource | None: ...
    def operation_checkpoints(
        self,
        run_id: str,
        *,
        after: SortKey | None,
        limit: int,
    ) -> V2Page | None: ...


__all__ = [
    "JsonObject",
    "SortKey",
    "V2MarketDataReadPort",
    "V2Page",
    "V2Resource",
]
