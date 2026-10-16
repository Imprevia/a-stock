"""Focused tests for shared v2 DTO and consistency primitives."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from src.market_environment.application.queries.v2_consistency import (
    CollectionLimitError,
    CursorBindingError,
    MalformedCursorError,
    StaleCursorRevisionError,
    decode_cursor,
    encode_cursor,
    opaque_snapshot_revision,
    resolve_collection_limit,
)
from src.market_environment.interfaces.http.schemas.models import (
    Chapter01Response,
    MarketEnvironmentResponse,
)
from src.market_environment.interfaces.http.schemas.v2 import (
    V2HistoryEnvelope,
    V2OverviewData,
    V2OverviewEnvelope,
    V2Quality,
)
from src.market_environment.interfaces.http.v2_conditional import (
    SnapshotRevisionConflict,
    conditional_not_modified_response,
    format_etag,
    require_snapshot_revision,
    snapshot_revision_conflict_response,
)
from src.market_environment.domain.models import MaterializationRevision


def test_v2_dto_is_dedicated_and_exposes_only_the_shared_envelope() -> None:
    assert not issubclass(V2OverviewEnvelope, MarketEnvironmentResponse)
    assert not issubclass(V2OverviewEnvelope, Chapter01Response)

    schema = V2OverviewEnvelope.model_json_schema()
    assert set(schema["properties"]) == {
        "asOf",
        "generatedAt",
        "snapshotRevision",
        "quality",
        "data",
        "links",
    }
    encoded = json.dumps(schema, sort_keys=True)
    assert "MarketEnvironmentResponse" not in encoded
    assert "Chapter01Response" not in encoded
    assert "chapter01" not in encoded

    response = V2OverviewEnvelope(
        asOf=date(2026, 8, 28),
        generatedAt=datetime(2026, 8, 28, 8, tzinfo=timezone.utc),
        snapshotRevision="sr1_fixture",
        quality=V2Quality(status="ok", source="local", observations=5),
        data=V2OverviewData(),
    )
    assert response.data.resources == []


def test_paginated_schema_contains_typed_shared_pagination() -> None:
    schema = V2HistoryEnvelope.model_json_schema()
    assert "pagination" in schema["properties"]
    encoded = json.dumps(schema, sort_keys=True)
    assert "nextCursor" in encoded
    assert "V2HistoryPoint" in encoded


def test_snapshot_revision_is_stable_and_hides_component_metadata() -> None:
    first = opaque_snapshot_revision(
        {"limits": "private-limits-checksum", "core": "private-core-checksum"}
    )
    reordered = opaque_snapshot_revision(
        {"core": "private-core-checksum", "limits": "private-limits-checksum"}
    )
    changed = opaque_snapshot_revision(
        {"core": "private-core-checksum-v2", "limits": "private-limits-checksum"}
    )

    assert first == reordered
    assert first != changed
    assert first.startswith("sr1_")
    assert "private" not in first
    assert "core" not in first
    assert opaque_snapshot_revision(MaterializationRevision("component-v1")) == (
        opaque_snapshot_revision("component-v1")
    )


def test_etag_preconditions_and_not_modified_response() -> None:
    revision = opaque_snapshot_revision("private-component-revision")
    etag = format_etag(revision)

    require_snapshot_revision(revision, etag)
    assert conditional_not_modified_response(revision, etag).status_code == 304
    assert conditional_not_modified_response(revision, f"W/{etag}").status_code == 304
    assert conditional_not_modified_response(revision, '"another"') is None

    with pytest.raises(SnapshotRevisionConflict) as raised:
        require_snapshot_revision(revision, '"stale-revision"')
    response = snapshot_revision_conflict_response(raised.value)
    assert response.status_code == 409
    assert response.headers["etag"] == etag
    assert json.loads(response.body)["error"] == {
        "code": "snapshot_revision_conflict",
        "message": "requested snapshot revision does not match current evidence",
        "requestedSnapshotRevision": "stale-revision",
        "currentSnapshotRevision": revision,
    }


def _cursor(*, filters: dict | None = None) -> tuple[str, str]:
    revision = opaque_snapshot_revision("component-revision")
    return (
        encode_cursor(
            resource="limits_pool",
            scope={"asOf": "2026-08-28", "poolType": "limit_up"},
            filters=filters or {"sort": "pool-order"},
            sort_key=(3, "000001.SZ"),
            snapshot_revision=revision,
        ),
        revision,
    )


def test_cursor_round_trip_is_bound_to_resource_scope_filters_and_revision() -> None:
    token, revision = _cursor()
    state = decode_cursor(
        token,
        expected_resource="limits_pool",
        expected_scope={"poolType": "limit_up", "asOf": "2026-08-28"},
        expected_filters={"sort": "pool-order"},
        current_snapshot_revision=revision,
    )

    assert state.sort_key == (3, "000001.SZ")
    assert state.snapshot_revision == revision


def test_cursor_rejects_malformed_cross_resource_changed_filter_and_stale_revision() -> None:
    token, revision = _cursor()
    common = {
        "expected_scope": {"asOf": "2026-08-28", "poolType": "limit_up"},
        "expected_filters": {"sort": "pool-order"},
        "current_snapshot_revision": revision,
    }

    with pytest.raises(MalformedCursorError):
        decode_cursor("not-a-cursor", expected_resource="limits_pool", **common)
    with pytest.raises(MalformedCursorError):
        decode_cursor(token[:-1] + "A", expected_resource="limits_pool", **common)
    with pytest.raises(CursorBindingError):
        decode_cursor(token, expected_resource="sector_rankings", **common)
    with pytest.raises(CursorBindingError):
        decode_cursor(
            token,
            expected_resource="limits_pool",
            **{**common, "expected_filters": {"sort": "identity"}},
        )
    with pytest.raises(StaleCursorRevisionError) as raised:
        decode_cursor(
            token,
            expected_resource="limits_pool",
            **{**common, "current_snapshot_revision": "sr1_new"},
        )
    assert raised.value.current_revision == "sr1_new"


def test_collection_limits_apply_defaults_and_reject_out_of_range_values() -> None:
    assert resolve_collection_limit("limits_pool", None) == 20
    assert resolve_collection_limit("index_history", None) == 60
    assert resolve_collection_limit("operation_checkpoints", None) == 50
    assert resolve_collection_limit("limits_pool", 100) == 100
    assert resolve_collection_limit("index_history", 250) == 250
    assert resolve_collection_limit("operation_checkpoints", 200) == 200

    for resource, invalid in (
        ("limits_pool", 0),
        ("limits_pool", 101),
        ("index_history", 251),
        ("operation_checkpoints", 201),
    ):
        with pytest.raises(CollectionLimitError):
            resolve_collection_limit(resource, invalid)
