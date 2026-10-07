from __future__ import annotations
from typing import Any
from .models import (
    Chapter01Response,
    CollectionRunResponse,
    CollectionStatusResponse,
    MarketEnvironmentResponse,
    NextSessionComparisonResponse,
    TimezonePreferencesResponse,
)


def map_market_environment(payload):
    return MarketEnvironmentResponse.model_validate(payload).model_dump()


def map_chapter01(payload):
    return Chapter01Response.model_validate(payload).model_dump()


def map_next_session(payload):
    return NextSessionComparisonResponse.model_validate(payload).model_dump()


def map_timezone_preferences(payload):
    return TimezonePreferencesResponse.model_validate(payload).model_dump()


def map_collection_run(payload):
    return CollectionRunResponse.model_validate(payload).model_dump()


def map_collection_status(payload, *, manual_refresh_enabled):
    merged = {
        "asOf": payload["asOf"],
        "manualRefreshEnabled": bool(manual_refresh_enabled),
        "datasets": payload["datasets"],
    }
    return CollectionStatusResponse.model_validate(merged).model_dump()


__all__ = [
    "map_chapter01",
    "map_collection_run",
    "map_collection_status",
    "map_market_environment",
    "map_next_session",
    "map_timezone_preferences",
]

