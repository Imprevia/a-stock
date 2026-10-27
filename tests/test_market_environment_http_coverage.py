"""Runtime HTTP coverage for previously unexercised market-environment operations."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.market_environment.application.queries import V2MarketDataQueries
from src.market_environment.infrastructure.v2_market_data_compat import (
    CompatibilityV2MarketDataReadAdapter,
)
from tests.market_environment_api_support import build_test_app


AS_OF = date(2026, 10, 15)
ROOT = f"/api/v2/market-environment/{AS_OF.isoformat()}"


def _quality(status: str, *, warnings: list[str] | None = None) -> dict:
    return {
        "dataset": "fixture",
        "source": "local-fixture",
        "provider": "fixture",
        "status": status,
        "actualDate": AS_OF.isoformat(),
        "observations": 2,
        "warnings": warnings or [],
    }


def _aggregate(*, breadth_status: str = "ok", include_workbench: bool = True) -> dict:
    chapter = {
        "status": "ok",
        "coverage": 1.0,
        "breadth": {
            "advanceCount": 3000 if breadth_status == "ok" else None,
            "declineCount": 1500 if breadth_status == "ok" else None,
            "quality": _quality(breadth_status),
            "history": {"points": []},
        },
    }
    if include_workbench:
        chapter["activeDirectionWorkbench"] = {
            "state": "ok",
            "quality": _quality("ok"),
            "researchRows": [
                {
                    "rank": 1,
                    "code": "000001",
                    "name": "fixture-stock",
                    "rawDirectionLabel": "fixture-direction",
                }
            ],
            "observations": [{"label": "fixture-direction", "count": 1}],
        }
    return {
        "asOf": AS_OF.isoformat(),
        "generatedAt": "2026-10-15T16:30:00+08:00",
        "summary": {"synchronization": "fixture", "warnings": []},
        "indices": [],
        "chapter01": chapter,
        "_componentRevision": "http-coverage-fixture-r1",
    }


def _client(aggregate: dict | None = None) -> TestClient:
    source = {} if aggregate is None else {AS_OF: aggregate}
    return TestClient(
        build_test_app(
            v2_queries=V2MarketDataQueries(
                CompatibilityV2MarketDataReadAdapter(source)
            ),
            effective_date=AS_OF,
        )
    )


def _assert_envelope(response, *, status: str) -> dict:
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "asOf", "generatedAt", "snapshotRevision", "quality", "data", "links"
    }
    assert body["asOf"] == AS_OF.isoformat()
    assert body["generatedAt"] == "2026-10-15T16:30:00+08:00"
    assert body["snapshotRevision"].startswith("sr1_")
    assert response.headers["etag"] == f'"{body["snapshotRevision"]}"'
    assert body["quality"]["status"] == status
    assert body["quality"]["source"] == "local-fixture"
    assert body["quality"]["provider"] == "fixture"
    assert body["quality"]["actualDate"] == AS_OF.isoformat()
    assert body["quality"]["observations"] == 2
    assert body["quality"]["warnings"] == []
    assert "http-coverage-fixture-r1" not in response.text
    return body


def test_health_http_success_dispatches_through_registered_route(monkeypatch) -> None:
    dispatches = []
    original_handle = APIRoute.handle

    async def record_handle(route, scope, receive, send):
        async def record_send(message):
            if message["type"] == "http.response.start":
                dispatches.append((scope["method"], route.path, message["status"]))
            await send(message)

        await original_handle(route, scope, receive, record_send)

    monkeypatch.setattr(APIRoute, "handle", record_handle)
    response = _client().get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert dispatches == [("GET", "/api/health", 200)]


def test_v2_breadth_success_has_exact_date_envelope_and_quality() -> None:
    response = _client(_aggregate()).get(f"{ROOT}/breadth")

    body = _assert_envelope(response, status="ok")
    assert body["links"] == []
    assert "history" not in body["data"]
    assert body["data"]["advanceCount"] == 3000
    assert body["data"]["declineCount"] == 1500
    assert body["data"]["quality"]["status"] == "ok"


@pytest.mark.parametrize("status", ["missing", "insufficient"])
def test_v2_breadth_preserves_missing_date_and_insufficient_quality(status) -> None:
    missing = _client(_aggregate()).get(
        "/api/v2/market-environment/2026-10-14/breadth"
    )
    insufficient = _client(_aggregate(breadth_status=status)).get(
        f"{ROOT}/breadth"
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"
    body = _assert_envelope(insufficient, status=status)
    assert body["data"]["advanceCount"] is None
    assert body["data"]["declineCount"] is None
    assert body["data"]["quality"]["status"] == status


def test_v2_workbench_success_has_links_and_exact_date_envelope() -> None:
    response = _client(_aggregate()).get(f"{ROOT}/active-direction/workbench")

    body = _assert_envelope(response, status="ok")
    assert body["data"]["state"] == "ok"
    assert body["data"]["researchRows"][0]["code"] == "000001"
    assert {link["href"] for link in body["links"]} == {
        f"{ROOT}/active-direction",
        f"{ROOT}/limits",
        f"{ROOT}/sectors/analysis",
        f"{ROOT}/events",
    }
    assert response.headers["etag"] == f'"{body["snapshotRevision"]}"'


def test_v2_workbench_revision_and_conditional_headers_are_enforced() -> None:
    client = _client(_aggregate())
    first = client.get(f"{ROOT}/active-direction/workbench")
    assert first.status_code == 200
    revision = first.json()["snapshotRevision"]
    etag = first.headers["etag"]
    pinned = client.get(
        f"{ROOT}/active-direction/workbench",
        params={"revision": revision},
        headers={"If-Match": etag},
    )
    changed = client.get(
        f"{ROOT}/active-direction/workbench",
        headers={"If-None-Match": '"older-revision"'},
    )
    assert pinned.status_code == changed.status_code == 200
    assert pinned.json() == changed.json() == first.json()

    stale = client.get(
        f"{ROOT}/active-direction/workbench",
        params={"revision": "stale-revision"},
    )
    if_match_conflict = client.get(
        f"{ROOT}/active-direction/workbench",
        headers={"If-Match": '"stale-revision"'},
    )
    unchanged = client.get(
        f"{ROOT}/active-direction/workbench",
        headers={"If-None-Match": first.headers["etag"]},
    )

    for conflict in (stale, if_match_conflict):
        assert conflict.status_code == 409
        assert conflict.json()["error"] == {
            "code": "snapshot_revision_conflict",
            "message": "requested snapshot revision does not match current evidence",
            "requestedSnapshotRevision": "stale-revision",
            "currentSnapshotRevision": revision,
        }
        assert conflict.headers["etag"] == first.headers["etag"]
    conflict_before_cache = client.get(
        f"{ROOT}/active-direction/workbench",
        params={"revision": "stale-revision"},
        headers={"If-None-Match": etag},
    )
    assert conflict_before_cache.status_code == 409
    assert conflict_before_cache.json() == stale.json()
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == first.headers["etag"]
