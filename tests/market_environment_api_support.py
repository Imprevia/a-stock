"""Dependency-override helpers for isolated market-environment API tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from src.market_environment.bootstrap.app import create_app
from src.market_environment.interfaces.http.dependencies import (
    get_collection_commands,
    get_collection_queries,
    get_effective_market_date,
    get_market_queries,
)


@dataclass(frozen=True, slots=True)
class FakeCollectionCommands:
    coordinator: object
    executor: object

    def start_run(self, as_of: date, datasets: Iterable[str] | None = None):
        return self.coordinator.start_run(as_of, datasets)

    def submit_run(self, run_id: str):
        return self.executor.submit(self.coordinator.execute_run, run_id)


def build_test_app(
    *,
    market_queries=None,
    collection_queries=None,
    collection_commands=None,
    effective_date: date | None = None,
):
    app = create_app()
    if market_queries is not None:
        app.dependency_overrides[get_market_queries] = lambda: market_queries
    if collection_queries is not None:
        app.dependency_overrides[get_collection_queries] = lambda: collection_queries
    if collection_commands is not None:
        app.dependency_overrides[get_collection_commands] = lambda: collection_commands
    if effective_date is not None:
        app.dependency_overrides[get_effective_market_date] = lambda: effective_date
    return app


__all__ = ["FakeCollectionCommands", "build_test_app"]
