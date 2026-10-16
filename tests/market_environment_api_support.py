"""Dependency-override helpers for isolated market-environment API tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from src.market_environment.bootstrap.app import create_app
from src.market_environment.interfaces.http.dependencies import (
    get_automation_write_enabled,
    get_collection_commands,
    get_collection_queries,
    get_effective_market_date,
    get_full_collection_commands,
    get_market_queries,
    get_v2_market_queries,
    get_ths_sector_commands,
    get_ths_sector_queries,
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
    v2_queries=None,
    collection_queries=None,
    collection_commands=None,
    full_collection_commands=None,
    automation_write_enabled: bool | None = None,
    ths_queries=None,
    ths_commands=None,
    effective_date: date | None = None,
):
    app = create_app()
    if market_queries is not None:
        app.dependency_overrides[get_market_queries] = lambda: market_queries
    if v2_queries is not None:
        app.dependency_overrides[get_v2_market_queries] = lambda: v2_queries
    if collection_queries is not None:
        app.dependency_overrides[get_collection_queries] = lambda: collection_queries
    if collection_commands is not None:
        app.dependency_overrides[get_collection_commands] = lambda: collection_commands
    if full_collection_commands is not None:
        app.dependency_overrides[get_full_collection_commands] = (
            lambda: full_collection_commands
        )
    if automation_write_enabled is not None:
        app.dependency_overrides[get_automation_write_enabled] = (
            lambda: automation_write_enabled
        )
    if ths_queries is not None:
        app.dependency_overrides[get_ths_sector_queries] = lambda: ths_queries
    if ths_commands is not None:
        app.dependency_overrides[get_ths_sector_commands] = lambda: ths_commands
    if effective_date is not None:
        app.dependency_overrides[get_effective_market_date] = lambda: effective_date
    return app


__all__ = ["FakeCollectionCommands", "build_test_app"]
