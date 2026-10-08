"""Temporary application-facing query and command service protocols."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol, runtime_checkable

from .collection_inputs import CollectionRefreshRequest, LimitHistoryPreparationRequest


@runtime_checkable
class MarketEnvironmentQueryPort(Protocol):
    def get(self, as_of: date) -> dict: ...

    def get_core(self, as_of: date) -> dict: ...

    def get_chapter01(self, as_of: date, section: str) -> dict: ...

    def get_next_session_comparison(self, as_of: date) -> dict: ...


@runtime_checkable
class CollectionQueryPort(Protocol):
    def collection_status(self, as_of: date) -> dict: ...

    def get_run(self, run_id: str): ...


@runtime_checkable
class CollectionCommandPort(Protocol):
    def start_run(self, as_of: date, datasets: Iterable[str] | None = None): ...

    def submit_run(self, run_id: str): ...

    def execute_run(self, run_id: str): ...

    def refresh(
        self,
        as_of: date,
        datasets: Iterable[str] | None = None,
        *,
        allow_historical_latest_only: bool = False,
        fetch_previous_limit_details: bool = True,
    ): ...

    def refresh_request(self, request: CollectionRefreshRequest): ...

    def prepare_limit_history(
        self,
        request: LimitHistoryPreparationRequest,
    ) -> tuple[date, ...]: ...


@runtime_checkable
class AggregateCommandPort(Protocol):
    def rebuild(self, as_of: date): ...


__all__ = [
    "AggregateCommandPort",
    "CollectionCommandPort",
    "CollectionQueryPort",
    "MarketEnvironmentQueryPort",
]
