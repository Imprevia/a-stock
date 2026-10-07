"""Materialized aggregate composition and rebuild factory."""
from __future__ import annotations
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..application.commands.materialized_aggregate import (
    MaterializedAggregateComposer,
    MaterializedAggregateRebuilder,
)
from ..limit_promotion import limit_v1_enabled
from ..schemas import MarketEnvironmentResponse
from ..snapshot_store import (
    MATERIALIZED_COMPONENT_REVISION_KEY,
    STORAGE_SCHEMA_VERSION,
    MaterializedAggregateConflict,
    MaterializedAggregateRecord,
    cache_state,
)
from .materialization_support import CHAPTER_GROUP_KEYS, MaterializationSupport


def utc_now(clock):
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return value.astimezone(ZoneInfo("UTC"))


def build_composer(
    *,
    support: MaterializationSupport,
    repository: Any,
    market_now_callable: Callable[[], datetime],
    snapshot_ttl_seconds: int,
) -> MaterializedAggregateComposer:
    return MaterializedAggregateComposer(
        repository=repository,
        market_now=market_now_callable,
        snapshot_ttl_seconds=snapshot_ttl_seconds,
        chapter_group_keys=CHAPTER_GROUP_KEYS,
        local_core_context=support.local_core_context,
        missing_chapter_provider_data=support.missing_chapter_provider_data,
        snapshot_payload=support.snapshot_payload,
        cache_state=cache_state,
        limit_payload_for_response=support.limit_payload_for_response,
        build_chapter01=support.build_chapter01,
        core_payload=support.core_payload,
        validate_response=lambda payload: MarketEnvironmentResponse.model_validate(payload).model_dump(),
        limits_snapshot_state=support.limits_snapshot_state,
        record_factory=lambda as_of, payload, generated_at: MaterializedAggregateRecord(
            as_of=as_of,
            payload=payload,
            generated_at=generated_at,
        ).normalized(),
        storage_schema_version=STORAGE_SCHEMA_VERSION,
        schema_version_key="_storageSchemaVersion",
        limits_state_key="_limitsSnapshotState",
        component_revision_key=MATERIALIZED_COMPONENT_REVISION_KEY,
    )


def build_rebuilder(
    *,
    repository: Any,
    composer: MaterializedAggregateComposer,
    market_now_callable: Callable[[], datetime],
    limits_v1_enabled_callable: Callable[[], bool] = limit_v1_enabled,
    conflict_error: type[Exception] = MaterializedAggregateConflict,
    attempts: int = 3,
) -> MaterializedAggregateRebuilder:
    return MaterializedAggregateRebuilder(
        repository=repository,
        composer=composer,
        market_now=market_now_callable,
        utc_now_factory=lambda: utc_now(market_now_callable),
        limits_v1_enabled=limits_v1_enabled_callable,
        conflict_error=conflict_error,
        attempts=attempts,
    )


__all__ = ["CHAPTER_GROUP_KEYS", "build_composer", "build_rebuilder", "utc_now"]
