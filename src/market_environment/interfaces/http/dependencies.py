"""Typed FastAPI dependencies for the transitional application container."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Protocol

from fastapi import Request


class MarketEnvironmentQueries(Protocol):
    def get(self, as_of: date) -> dict: ...

    def get_core(self, as_of: date) -> dict: ...

    def get_chapter01(self, as_of: date, section: str) -> dict: ...

    def get_next_session_comparison(self, as_of: date) -> dict: ...


class CollectionQueries(Protocol):
    def collection_status(self, as_of: date) -> dict[str, Any]: ...

    def get_run(self, run_id: str): ...


class CollectionCommands(Protocol):
    def start_run(self, as_of: date, datasets: Iterable[str] | None = None): ...

    def submit_run(self, run_id: str): ...


class ThsSectorQueries(Protocol):
    def list_catalog(self, **kwargs) -> dict[str, Any]: ...

    def get_bars(self, thscode: str, **kwargs) -> dict[str, Any]: ...

    def get_operation(self, run_id: str) -> dict[str, Any]: ...


class ThsSectorCommands(Protocol):
    def start_catalog_sync(self, **kwargs) -> dict[str, str]: ...

    def start_turnover_backfill(self, **kwargs) -> dict[str, str]: ...

    def start_member_import(self, **kwargs) -> dict[str, str]: ...


class TimezonePreferenceQueries(Protocol):
    def get(self, *args, **kwargs): ...


class TimezonePreferenceCommands(Protocol):
    def set(self, *args, **kwargs): ...


def get_market_queries(request: Request) -> MarketEnvironmentQueries:
    return _request_container(request).reads.market_environment


def get_collection_queries(request: Request) -> CollectionQueries:
    return _request_container(request).reads.collection


def get_collection_commands(request: Request) -> CollectionCommands:
    return _request_container(request).commands.collection


def get_ths_sector_queries(request: Request) -> ThsSectorQueries:
    return _request_container(request).reads.ths_sectors


def get_ths_sector_commands(request: Request) -> ThsSectorCommands:
    return _request_container(request).commands.ths_sectors


def get_timezone_queries(request: Request) -> TimezonePreferenceQueries:
    return _request_container(request).reads.timezone_preferences


def get_timezone_commands(request: Request) -> TimezonePreferenceCommands:
    return _request_container(request).commands.timezone_preferences


def get_effective_market_date() -> date:
    from ...refresh import effective_market_date

    return effective_market_date(datetime.now())


def get_manual_write_enabled() -> bool:
    return os.getenv("MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _request_container(request: Request):
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = request.app.state.container_factory()
        request.app.state.container = container
    return container


__all__ = [
    "CollectionCommands",
    "CollectionQueries",
    "MarketEnvironmentQueries",
    "TimezonePreferenceCommands",
    "TimezonePreferenceQueries",
    "ThsSectorCommands",
    "ThsSectorQueries",
    "get_collection_commands",
    "get_collection_queries",
    "get_effective_market_date",
    "get_market_queries",
    "get_manual_write_enabled",
    "get_ths_sector_commands",
    "get_ths_sector_queries",
    "get_timezone_commands",
    "get_timezone_queries",
]
