"""Compatibility mappers between typed values and existing representations."""

from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any, Mapping, Protocol

from ..domain.models import (
    AcquisitionTimings,
    CacheMetadata,
    CacheState,
    CollectionCandidate,
    DatasetDate,
    FieldAvailability,
    MaterializationRevision,
    QualityMetadata,
    RedactedProvenance,
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
    "sourceRevision",
    "fetchedAt",
    "fieldAvailability",
    "timings",
    "evidenceFingerprint",
    "provenance",
}


def _timings_from_api(value: Any) -> AcquisitionTimings:
    if not isinstance(value, Mapping):
        return AcquisitionTimings()
    phases = value.get("phasesMs")
    return AcquisitionTimings(
        total_ms=float(value["totalMs"]) if value.get("totalMs") is not None else None,
        phases_ms={str(key): float(item) for key, item in (phases or {}).items()},
    )


def _timings_to_api(value: AcquisitionTimings) -> dict[str, Any] | None:
    if value.total_ms is None and not value.phases_ms:
        return None
    return {
        "totalMs": value.total_ms,
        "phasesMs": dict(value.phases_ms),
    }


def _field_availability_from_api(value: Any) -> FieldAvailability:
    if not isinstance(value, Mapping):
        return FieldAvailability()
    return FieldAvailability(
        available=tuple(str(item) for item in value.get("available") or ()),
        missing=tuple(str(item) for item in value.get("missing") or ()),
        unsupported=tuple(str(item) for item in value.get("unsupported") or ()),
    )


def _field_availability_to_api(value: FieldAvailability) -> dict[str, Any] | None:
    if not (value.available or value.missing or value.unsupported):
        return None
    return {
        "available": list(value.available),
        "missing": list(value.missing),
        "unsupported": list(value.unsupported),
    }


def _provenance_from_api(value: Any) -> RedactedProvenance:
    if not isinstance(value, Mapping):
        return RedactedProvenance()
    reserved = {"endpoint", "engine", "requestId", "authenticationScopeDigest"}
    return RedactedProvenance(
        endpoint=str(value["endpoint"]) if value.get("endpoint") is not None else None,
        engine=str(value["engine"]) if value.get("engine") is not None else None,
        request_id=str(value["requestId"]) if value.get("requestId") is not None else None,
        authentication_scope_digest=(
            str(value["authenticationScopeDigest"])
            if value.get("authenticationScopeDigest") is not None
            else None
        ),
        attributes={str(key): copy.deepcopy(item) for key, item in value.items() if key not in reserved},
    )


def _provenance_to_api(value: RedactedProvenance) -> dict[str, Any] | None:
    if not (value.endpoint or value.engine or value.request_id or value.authentication_scope_digest or value.attributes):
        return None
    result = copy.deepcopy(dict(value.attributes))
    if value.endpoint is not None:
        result["endpoint"] = value.endpoint
    if value.engine is not None:
        result["engine"] = value.engine
    if value.request_id is not None:
        result["requestId"] = value.request_id
    if value.authentication_scope_digest is not None:
        result["authenticationScopeDigest"] = value.authentication_scope_digest
    return result


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
    timings = _timings_from_api(payload.get("timings"))
    field_availability = _field_availability_from_api(payload.get("fieldAvailability"))
    provenance = _provenance_from_api(payload.get("provenance"))
    fetched_at = payload.get("fetchedAt")
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
        source_revision=(
            str(payload["sourceRevision"]) if payload.get("sourceRevision") is not None else None
        ),
        fetched_at=(datetime.fromisoformat(str(fetched_at)) if fetched_at is not None else None),
        field_availability=field_availability,
        timings=timings,
        evidence_fingerprint=(
            str(payload["evidenceFingerprint"])
            if payload.get("evidenceFingerprint") is not None
            else None
        ),
        provenance=provenance,
    )


def quality_to_api(quality: QualityMetadata) -> dict[str, Any]:
    cache = quality.cache
    result = {
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
    optional = {
        "sourceRevision": quality.source_revision,
        "fetchedAt": quality.fetched_at.isoformat() if quality.fetched_at is not None else None,
        "fieldAvailability": _field_availability_to_api(quality.field_availability),
        "timings": _timings_to_api(quality.timings),
        "evidenceFingerprint": quality.evidence_fingerprint,
        "provenance": _provenance_to_api(quality.provenance),
    }
    result.update({key: value for key, value in optional.items() if value is not None})
    return result


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
        source_revision=quality.source_revision if quality is not None else None,
        fetched_at=quality.fetched_at if quality is not None else None,
        field_availability=quality.field_availability if quality is not None else FieldAvailability(),
        timings=quality.timings if quality is not None else AcquisitionTimings(),
        evidence_fingerprint=quality.evidence_fingerprint if quality is not None else None,
        provenance=quality.provenance if quality is not None else RedactedProvenance(),
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
