from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from src.market_environment.domain.models import (
    CANONICAL_FULL_COLLECTION_DATASETS,
    AcquisitionFailure,
    AcquisitionFailureCategory,
    CollectionFailureCategory,
    FullCollectionSemantics,
    IdempotencyBinding,
    IdempotencyKey,
    StructuredTaskFailure,
    SubmissionState,
)


def test_full_collection_fingerprint_is_stable_and_excludes_wait_preference() -> None:
    first = FullCollectionSemantics.create(
        date(2026, 10, 15),
        wait_timeout_seconds=900,
    )
    replay = FullCollectionSemantics.create(
        date(2026, 10, 15),
        wait_timeout_seconds=0,
    )

    assert first.datasets == CANONICAL_FULL_COLLECTION_DATASETS
    assert first.payload() == replay.payload()
    assert first.semantic_fingerprint == replay.semantic_fingerprint
    assert first.dataset_fingerprint == replay.dataset_fingerprint
    assert len(first.semantic_fingerprint) == 64
    assert first.semantic_fingerprint != FullCollectionSemantics.create(
        date(2026, 10, 16)
    ).semantic_fingerprint


def test_full_collection_semantics_rejects_transport_and_dataset_drift() -> None:
    with pytest.raises(ValueError, match="between 0 and 900"):
        FullCollectionSemantics.create(date(2026, 10, 15), wait_timeout_seconds=901)
    with pytest.raises(ValueError, match="canonical seven datasets"):
        FullCollectionSemantics(
            resolved_as_of=date(2026, 10, 15),
            datasets=("core",),
        )


@pytest.mark.parametrize(
    "value",
    ("", " key", "contains space", "x" * 201, "slash/not-allowed"),
)
def test_idempotency_key_rejects_ambiguous_or_unbounded_values(value: str) -> None:
    with pytest.raises(ValueError, match="idempotency key"):
        IdempotencyKey(value)


def test_structured_failure_redacts_and_round_trips_stably() -> None:
    failure = StructuredTaskFailure(
        category=CollectionFailureCategory.NETWORK,
        message=(
            "POST postgresql://alice:database-secret@db.internal/market "
            "Authorization: Bearer top-secret api_key=provider-secret "
            "https://example.test/path?token=query-secret"
        ),
        retryable=True,
        retained=True,
        source="provider-a",
        stage="acquisition",
        code="connection-reset",
        blocked_by=("core", "core", " "),
    )

    payload = failure.to_dict()
    serialized = failure.canonical_json()
    restored = StructuredTaskFailure.from_dict(json.loads(serialized))

    assert "database-secret" not in serialized
    assert "top-secret" not in serialized
    assert "provider-secret" not in serialized
    assert "query-secret" not in serialized
    assert "postgresql://***@db.internal/market" in failure.message
    assert payload["blockedBy"] == ["core"]
    assert restored == failure
    assert restored.canonical_json() == serialized


def test_structured_failure_redacts_all_optional_string_fields() -> None:
    failure = StructuredTaskFailure(
        category=CollectionFailureCategory.NETWORK,
        message="provider request failed",
        retryable=True,
        retained=False,
        source="https://alice:source-secret@provider.internal?token=query-secret",
        stage="Authorization: Bearer stage-secret",
        code="api_key=code-secret",
        blocked_by=(
            "postgresql://operator:blocked-secret@db.internal/market",
            "password=dependency-secret",
        ),
    )

    serialized = failure.canonical_json()

    for secret in (
        "source-secret",
        "query-secret",
        "stage-secret",
        "code-secret",
        "blocked-secret",
        "dependency-secret",
    ):
        assert secret not in serialized
    assert failure.source == "https://***@provider.internal?token=[REDACTED]"
    assert failure.stage == "Authorization: [REDACTED]"
    assert failure.code == "api_key=[REDACTED]"
    assert failure.blocked_by == (
        "postgresql://***@db.internal/market",
        "password=[REDACTED]",
    )
    assert StructuredTaskFailure.from_dict(json.loads(serialized)) == failure


def test_acquisition_failure_maps_to_safe_structured_value() -> None:
    acquisition = AcquisitionFailure(
        category=AcquisitionFailureCategory.PERMISSION,
        message="token=private-value permission denied",
        retryable=False,
        source="fuyao",
    )

    failure = StructuredTaskFailure.from_acquisition(acquisition, retained=False)

    assert failure.category is CollectionFailureCategory.PERMISSION
    assert failure.message == "token=[REDACTED] permission denied"
    assert failure.retryable is False
    assert failure.retained is False
    assert failure.stage == "acquisition"


def test_binding_matches_only_the_original_semantics() -> None:
    semantics = FullCollectionSemantics.create(date(2026, 10, 15))
    timestamp = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    binding = IdempotencyBinding(
        operation_scope=semantics.operation_scope,
        key=IdempotencyKey("hermes-market-collection-2026-10-15-1630"),
        semantic_fingerprint=semantics.semantic_fingerprint,
        resolved_as_of=semantics.resolved_as_of,
        operation_version=semantics.operation_version,
        dataset_fingerprint=semantics.dataset_fingerprint,
        run_id="run-1",
        submission_state=SubmissionState.RESERVED,
        submission_attempts=0,
        created_at=timestamp,
        updated_at=timestamp,
    )

    assert binding.matches(semantics)
    assert not binding.matches(FullCollectionSemantics.create(date(2026, 10, 16)))


def test_structured_failure_requires_enum_and_nonempty_safe_message() -> None:
    with pytest.raises(TypeError, match="CollectionFailureCategory"):
        StructuredTaskFailure(  # type: ignore[arg-type]
            category="network",
            message="network failed",
            retryable=True,
            retained=False,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        StructuredTaskFailure(
            category=CollectionFailureCategory.NETWORK,
            message="  ",
            retryable=True,
            retained=False,
        )
