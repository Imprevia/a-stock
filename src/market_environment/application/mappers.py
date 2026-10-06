"""Compatibility mappers between typed values and existing representations."""

from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any, Mapping, Protocol

from ..domain.models import (
    CacheMetadata,
    CacheState,
    CollectionCandidate,
    DatasetDate,
    MaterializationRevision,
    QualityMetadata,
)


class SnapshotRecordLike(Protocol):
    dataset: str
    as_of: date
    payload: dict[str, Any]
    source: str
    status: str
    observations: int
    warnings: tuple[str, ...]
    fetched_at: datetime
    settled: bool
    schema_version: int
    checksum: str
    refresh_warning: str | None


_QUALITY_KEYS = {
    "dataset",
    "source",
    "provider",
    "status",
    "observations",
    "asOf",
    "warning",
    "warnings",
    "cacheState",
    "snapshotFetchedAt",
    "refreshing",
    "refreshWarning",
}


def quality_from_api(payload: Mapping[str, Any]) -> QualityMetadata:
    as_of = payload.get("asOf")
    snapshot_fetched_at = payload.get("snapshotFetchedAt")
    cache_state = payload.get("cacheState")
    cache = None
    if any(
        payload.get(key) is not None
        for key in ("cacheState", "snapshotFetchedAt", "refreshing", "refreshWarning")
    ):
        cache = CacheMetadata(
            state=CacheState(cache_state) if cache_state is not None else None,
            snapshot_fetched_at=(
                datetime.fromisoformat(str(snapshot_fetched_at))
                if snapshot_fetched_at is not None
                else None
            ),
            refreshing=payload.get("refreshing"),
            refresh_warning=payload.get("refreshWarning"),
        )
    return QualityMetadata(
        dataset=str(payload.get("dataset") or "unknown"),
        source=str(payload.get("source") or "none"),
        provider=str(payload.get("provider") or payload.get("source") or "none"),
        status=str(payload.get("status") or "missing"),
        observations=int(payload.get("observations") or 0),
        as_of=date.fromisoformat(str(as_of)) if as_of is not None else None,
        warning=str(payload["warning"]) if payload.get("warning") is not None else None,
        warnings=tuple(str(value) for value in payload.get("warnings") or ()),
        cache=cache,
        extra={
            key: copy.deepcopy(value)
            for key, value in payload.items()
            if key not in _QUALITY_KEYS
        },
    )


def quality_to_api(quality: QualityMetadata) -> dict[str, Any]:
    cache = quality.cache
    return {
        "dataset": quality.dataset,
        "source": quality.source,
        "provider": quality.provider,
        "status": quality.status,
        "observations": quality.observations,
        "asOf": quality.as_of.isoformat() if quality.as_of is not None else None,
        "warning": quality.warning,
        "warnings": list(quality.warnings),
        "cacheState": cache.state.value if cache is not None and cache.state is not None else None,
        "snapshotFetchedAt": (
            cache.snapshot_fetched_at.isoformat()
            if cache is not None and cache.snapshot_fetched_at is not None
            else None
        ),
        "refreshing": cache.refreshing if cache is not None else None,
        "refreshWarning": cache.refresh_warning if cache is not None else None,
        **copy.deepcopy(dict(quality.extra)),
    }


def snapshot_to_candidate(record: SnapshotRecordLike) -> CollectionCandidate:
    payload = copy.deepcopy(record.payload)
    quality_payload = payload.get("quality") if isinstance(payload, dict) else None
    quality = quality_from_api(quality_payload) if isinstance(quality_payload, Mapping) else None
    actual_as_of = quality.as_of if quality is not None else record.as_of
    return CollectionCandidate(
        identity=DatasetDate(record.dataset, record.as_of),
        payload=payload,
        source=record.source,
        status=record.status,
        observations=record.observations,
        warnings=tuple(record.warnings),
        settled=record.settled,
        actual_as_of=actual_as_of,
        quality=quality,
    )


def candidate_to_snapshot_fields(
    candidate: CollectionCandidate,
    *,
    fetched_at: datetime,
    schema_version: int = 1,
    checksum: str = "",
    refresh_warning: str | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(candidate.payload))
    if candidate.quality is not None:
        payload["quality"] = quality_to_api(candidate.quality)
    return {
        "dataset": candidate.identity.dataset,
        "as_of": candidate.identity.as_of,
        "payload": payload,
        "source": candidate.source,
        "status": candidate.status,
        "observations": candidate.observations,
        "warnings": tuple(candidate.warnings),
        "fetched_at": fetched_at,
        "settled": candidate.settled,
        "schema_version": schema_version,
        "checksum": checksum,
        "refresh_warning": refresh_warning,
    }


def materialization_revision_from_storage(value: str) -> MaterializationRevision:
    return MaterializationRevision(value)


def materialization_revision_to_storage(revision: MaterializationRevision) -> str:
    return revision.value


__all__ = [
    "SnapshotRecordLike",
    "candidate_to_snapshot_fields",
    "materialization_revision_from_storage",
    "materialization_revision_to_storage",
    "quality_from_api",
    "quality_to_api",
    "snapshot_to_candidate",
]
