from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.market_environment.application.mappers import (
    candidate_to_snapshot_fields,
    materialization_revision_from_storage,
    materialization_revision_to_storage,
    quality_from_api,
    quality_to_api,
    snapshot_to_candidate,
)
from src.market_environment.domain.models import (
    AcquisitionFailure,
    AcquisitionFailureCategory,
    AcquisitionTimings,
    AttemptEvidence,
    CollectionCandidate,
    CollectionOutcome,
    CollectionRunState,
    CollectionTaskState,
    DatasetDate,
    FieldAvailability,
    QualityMetadata,
    RedactedProvenance,
)
from src.market_environment.snapshot_store import SnapshotRecord


AS_OF = date(2026, 9, 3)
FETCHED_AT = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def quality_payload() -> dict:
    return {
        "dataset": "market-breadth",
        "source": "tdx-daily-package",
        "provider": "tdx",
        "status": "degraded",
        "observations": 3200,
        "asOf": AS_OF.isoformat(),
        "warning": "fixture warning",
        "warnings": ["fixture warning"],
        "cacheState": "stale",
        "snapshotFetchedAt": FETCHED_AT.isoformat(),
        "refreshing": False,
        "refreshWarning": "retained exact-date snapshot",
        "rankingMethod": "fixture-rank-v1",
        "stockUniverseRawCount": 3300,
        "stockUniverseRetainedCount": 3200,
    }


def test_quality_and_cache_metadata_round_trip_existing_api_shape() -> None:
    payload = quality_payload()

    typed = quality_from_api(payload)

    assert typed.as_of == AS_OF
    assert typed.cache is not None
    assert typed.cache.snapshot_fetched_at == FETCHED_AT
    assert quality_to_api(typed) == payload


def test_snapshot_candidate_round_trip_existing_storage_record() -> None:
    record = SnapshotRecord(
        dataset="breadth",
        as_of=AS_OF,
        payload={
            "advanceCount": 2100,
            "declineCount": 1100,
            "quality": quality_payload(),
        },
        source="tdx-daily-package",
        status="degraded",
        observations=3200,
        warnings=("fixture warning",),
        fetched_at=FETCHED_AT,
        settled=True,
        refresh_warning="retained exact-date snapshot",
    )

    candidate = snapshot_to_candidate(record)
    rebuilt = SnapshotRecord(
        **candidate_to_snapshot_fields(
            candidate,
            fetched_at=record.fetched_at,
            schema_version=record.schema_version,
            checksum=record.checksum,
            refresh_warning=record.refresh_warning,
        )
    )

    assert candidate.identity == DatasetDate("breadth", AS_OF)
    assert candidate.actual_as_of == AS_OF
    assert rebuilt.normalized() == record.normalized()


def test_run_task_outcome_and_revision_values_keep_stored_strings() -> None:
    assert CollectionRunState("partial").value == "partial"
    assert CollectionTaskState("failed-retained").value == "failed-retained"

    record = SnapshotRecord(
        dataset="sectors",
        as_of=AS_OF,
        payload={"quality": {**quality_payload(), "dataset": "industry-ranking"}},
        source="fixture",
        status="ok",
        observations=10,
        warnings=(),
        fetched_at=FETCHED_AT,
    )
    candidate = snapshot_to_candidate(record)
    retained = CollectionOutcome(
        identity=candidate.identity,
        state=CollectionTaskState.FAILED_RETAINED,
        candidate=candidate,
        warning="fixture failure",
        retained=True,
    )
    revision = materialization_revision_from_storage("a" * 64)

    assert retained.state.value == "failed-retained"
    assert retained.retained is True
    assert materialization_revision_to_storage(revision) == "a" * 64


def test_typed_values_reject_invalid_identity_and_outcome() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        DatasetDate("unknown", AS_OF)
    with pytest.raises(ValueError, match="retained outcomes"):
        CollectionOutcome(
            identity=DatasetDate("breadth", AS_OF),
            state=CollectionTaskState.FAILED_MISSING,
            retained=True,
        )


def test_acquisition_evidence_values_are_typed_and_validate_success_identity() -> None:
    identity = DatasetDate("breadth", AS_OF)
    candidate = CollectionCandidate(
        identity=identity,
        payload={"advanceCount": 1},
        source="fixture-primary",
        status="ok",
        observations=1,
        warnings=(),
        settled=True,
        actual_as_of=AS_OF,
        source_revision="fixture-v1",
        fetched_at=FETCHED_AT,
        field_availability=FieldAvailability(available=("advanceCount",), missing=("leader",)),
        timings=AcquisitionTimings(total_ms=12.5, phases_ms={"parse": 1.5}),
        evidence_fingerprint="a" * 64,
        provenance=RedactedProvenance(
            endpoint="https://fixture.invalid/data",
            engine="requests",
            authentication_scope_digest="b" * 64,
        ),
    )
    attempt = AttemptEvidence(
        role="formal",
        provider="fixture",
        source="fixture-primary",
        source_revision="fixture-v1",
        engine="requests",
        requested_as_of=AS_OF,
        actual_as_of=AS_OF,
        timings=AcquisitionTimings(total_ms=12.5),
        provenance=candidate.provenance,
        evidence_fingerprint="a" * 64,
    )
    outcome = CollectionOutcome(
        identity=identity,
        state=CollectionTaskState.SUCCESS,
        candidate=candidate,
        attempts=(attempt,),
    )
    assert outcome.candidate is candidate
    assert outcome.attempts[0].engine == "requests"

    failure = AcquisitionFailure(
        category=AcquisitionFailureCategory.DATE_MISMATCH,
        message="fixture date mismatch",
        source="fixture-primary",
        requested_as_of=AS_OF,
    )
    failed = CollectionOutcome(
        identity=identity,
        state=CollectionTaskState.FAILED_MISSING,
        warning=failure.message,
        failure=failure,
    )
    assert failed.failure is failure

    with pytest.raises(ValueError, match="actual date"):
        CollectionCandidate(
            identity=identity,
            payload={},
            source="fixture",
            status="ok",
            observations=0,
            warnings=(),
            settled=True,
            actual_as_of=AS_OF.replace(day=4),
        )


def test_extended_quality_evidence_round_trips_without_changing_legacy_defaults() -> None:
    quality = QualityMetadata(
        dataset="breadth",
        source="fixture-primary",
        provider="fixture",
        status="degraded",
        observations=3,
        as_of=AS_OF,
        source_revision="fixture-v1",
        fetched_at=FETCHED_AT,
        field_availability=FieldAvailability(available=("advanceCount",), unsupported=("leader",)),
        timings=AcquisitionTimings(total_ms=4.0, phases_ms={"normalize": 2.0}),
        evidence_fingerprint="c" * 64,
        provenance=RedactedProvenance(endpoint="https://fixture.invalid", engine="requests"),
    )
    encoded = quality_to_api(quality)
    decoded = quality_from_api(encoded)

    assert decoded == quality
    assert quality_to_api(decoded) == encoded
    assert "sourceRevision" in encoded
    assert "fieldAvailability" in encoded
