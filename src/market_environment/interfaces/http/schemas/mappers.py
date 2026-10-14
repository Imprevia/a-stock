from __future__ import annotations

import copy
from typing import Any

from ....application.ths_diagnostics import ths_warning_response
from .models import (
    Chapter01Response,
    CollectionRunResponse,
    CollectionStatusResponse,
    MarketEnvironmentResponse,
    NextSessionComparisonResponse,
    TimezonePreferencesResponse,
)


_THS_CHAPTER_KEYS = ("industryRanking", "sectorTurnover", "sectorBreadth")


def _normalize_ths_evidence(value: object) -> object:
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    revision = result.get("catalogRevisionId")
    if revision is None:
        revision = result.get("catalogRevision", result.get("revisionId"))
    if revision is not None:
        result["catalogRevisionId"] = revision
    quality = result.get("quality")
    diagnostic = None
    if isinstance(quality, dict):
        quality_revision = quality.get("catalogRevisionId")
        if quality_revision is None:
            quality_revision = quality.get(
                "catalogRevision", quality.get("revisionId")
            )
        if quality_revision is not None:
            quality["catalogRevisionId"] = quality_revision
        if revision is None and quality_revision is not None:
            result["catalogRevisionId"] = quality_revision
        warning = quality.get("warning")
        if isinstance(warning, str):
            message, diagnostic = ths_warning_response(warning)
            quality["warning"] = message
        warnings = quality.get("warnings")
        if isinstance(warnings, (list, tuple)):
            safe_warnings: list[object] = []
            for item in warnings:
                if isinstance(item, str):
                    message, parsed = ths_warning_response(item)
                    safe_warnings.append(message)
                    diagnostic = diagnostic or parsed
                else:
                    safe_warnings.append(item)
            quality["warnings"] = safe_warnings
        if diagnostic is not None:
            quality["diagnostics"] = diagnostic
    if diagnostic is not None:
        result["diagnostics"] = diagnostic
    return result


def _normalize_ths_chapter(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    normalized = copy.deepcopy(payload)
    chapter = normalized.get("chapter01")
    if isinstance(chapter, dict):
        for key in _THS_CHAPTER_KEYS:
            if key in chapter:
                chapter[key] = _normalize_ths_evidence(chapter[key])
    return normalized


def map_market_environment(payload):
    return MarketEnvironmentResponse.model_validate(
        _normalize_ths_chapter(payload)
    ).model_dump()


def map_chapter01(payload):
    return Chapter01Response.model_validate(
        _normalize_ths_chapter(payload)
    ).model_dump()


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
        "sectorAnalysis": payload.get("sectorAnalysis"),
    }
    result = CollectionStatusResponse.model_validate(merged).model_dump()
    if result.get("sectorAnalysis") is None:
        result.pop("sectorAnalysis", None)
    return result


__all__ = [
    "map_chapter01",
    "map_collection_run",
    "map_collection_status",
    "map_market_environment",
    "map_next_session",
    "map_timezone_preferences",
]
