"""Typed inputs for collection refresh and limits history preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CollectionRefreshRequest:
    as_of: date
    datasets: tuple[str, ...] | None = None
    allow_historical_latest_only: bool = False
    fetch_previous_limit_details: bool = True


@dataclass(frozen=True, slots=True)
class LimitHistoryPreparationRequest:
    as_of: date
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("history session count must be at least 1")


@runtime_checkable
class LimitHistoryPreparer(Protocol):
    def prepare(
        self,
        request: LimitHistoryPreparationRequest,
    ) -> tuple[date, ...]: ...


__all__ = [
    "CollectionRefreshRequest",
    "LimitHistoryPreparationRequest",
    "LimitHistoryPreparer",
]
