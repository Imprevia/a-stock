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
    CollectionOutcome,
    CollectionRunState,
    CollectionTaskState,
    DatasetDate,
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
