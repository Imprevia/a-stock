"""Executable contract for the bounded, provider-free v2 read surface."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from src.market_environment.application.queries import V2MarketDataQueries
from src.market_environment.bootstrap.app import create_app
from src.market_environment.infrastructure.v2_market_data_compat import (
    CompatibilityV2MarketDataReadAdapter,
)
from tests.market_environment_api_support import build_test_app


AS_OF = "2026-08-28"
ROOT = f"/api/v2/market-environment/{AS_OF}"


def _queries() -> V2MarketDataQueries:
    as_of = date.fromisoformat(AS_OF)
    aggregate = {
        "asOf": AS_OF,
        "generatedAt": "2026-08-28T16:30:00+08:00",
        "summary": {
            "synchronization": "fixture",
            "dominantTrend": "fixture",
            "warnings": [],
        },
        "indices": [
            {
                "code": "000001.SH",
                "name": "上证指数",
                "history": [
                    {"date": "2026-08-27", "close": 100.0},
                    {"date": AS_OF, "close": 101.0},
                ],
                "dataQuality": {"status": "ok", "warnings": []},
            }
        ],
        "chapter01": {
            "status": "ok",
            "coverage": 1.0,
            "breadth": {"quality": {"status": "ok", "warnings": []}, "history": {"points": []}},
            "limits": {
                "quality": {"status": "ok", "warnings": []},
                "securityDetails": {},
                "history": {"points": []},
                "ruleEvidence": [],
                "riskEvidence": [],
            },
            "industryRanking": {"quality": {"status": "missing", "warnings": []}, "rows": []},
            "sectorTurnover": {"quality": {"status": "missing", "warnings": []}, "rows": []},
            "sectorBreadth": {"quality": {"status": "missing", "warnings": []}, "rows": []},
            "sectorAnalysis": None,
            "activeDirection": {"quality": {"status": "missing", "warnings": []}, "topStocks": []},
            "events": {"quality": {"status": "missing", "warnings": []}, "items": []},
            "assessment": {"state": "insufficient", "confidence": "insufficient", "evidence": [], "risks": []},
        },
        "_componentRevision": "private-fixture-revision",
    }
    return V2MarketDataQueries(CompatibilityV2MarketDataReadAdapter({as_of: aggregate}))


def _client() -> TestClient:
    return TestClient(
        build_test_app(
            v2_queries=_queries(),
            effective_date=date(2026, 10, 16),
        )
    )


def test_v2_openapi_declares_the_closed_resource_tree() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/api/v2/market-environment/{as_of}/overview",
        "/api/v2/market-environment/{as_of}/indices",
        "/api/v2/market-environment/{as_of}/indices/{code}",
        "/api/v2/market-environment/{as_of}/indices/{code}/history",
        "/api/v2/market-environment/{as_of}/breadth",
        "/api/v2/market-environment/{as_of}/breadth/history",
        "/api/v2/market-environment/{as_of}/limits",
        "/api/v2/market-environment/{as_of}/limits/pools/{pool_type}",
        "/api/v2/market-environment/{as_of}/limits/history",
        "/api/v2/market-environment/{as_of}/limits/evidence",
        "/api/v2/market-environment/{as_of}/sectors/rankings",
        "/api/v2/market-environment/{as_of}/sectors/turnover",
        "/api/v2/market-environment/{as_of}/sectors/breadth",
        "/api/v2/market-environment/{as_of}/sectors/analysis",
        "/api/v2/market-environment/{as_of}/active-direction",
        "/api/v2/market-environment/{as_of}/events",
        "/api/v2/market-environment/{as_of}/assessment",
        "/api/v2/market-environment/operations/{run_id}",
        "/api/v2/market-environment/operations/{run_id}/checkpoints",
        "/llms.txt",
        "/llms-full.txt",
    }

    assert required <= set(paths)
    overview_schema = paths["/api/v2/market-environment/{as_of}/overview"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "Chapter01Response" not in str(overview_schema)
    assert "MarketEnvironmentResponse" not in str(overview_schema)


def test_v2_overview_is_resource_isolated_and_uses_the_shared_envelope() -> None:
    response = _client().get(f"{ROOT}/overview")

    assert response.status_code == 200
    body = response.json()
    assert {
        "asOf",
        "generatedAt",
        "snapshotRevision",
        "quality",
        "data",
        "links",
    } <= body.keys()
    encoded = response.text
    for forbidden in (
        '"history"',
        '"securityDetails"',
        '"rows"',
        '"checkpoints"',
        '"chapter01"',
    ):
        assert forbidden not in encoded


def test_v2_missing_future_and_closed_selectors_have_stable_statuses() -> None:
    client = _client()
    future = (date.today() + timedelta(days=366)).isoformat()

    assert client.get(f"/api/v2/market-environment/{future}/overview").status_code == 422
    assert client.get("/api/v2/market-environment/1900-01-01/overview").status_code == 404
    assert client.get(f"{ROOT}/indices/not-a-code").status_code in {404, 422}
    assert client.get(f"{ROOT}/limits/pools/not-a-pool").status_code == 422


def test_v2_variable_collections_reject_limits_above_their_maximum() -> None:
    client = _client()
    cases = (
        (f"{ROOT}/indices/000001.SH/history?limit=251", 422),
        (f"{ROOT}/breadth/history?limit=251", 422),
        (f"{ROOT}/limits/history?limit=251", 422),
        (f"{ROOT}/limits/pools/limit_up?limit=101", 422),
        (f"{ROOT}/sectors/rankings?limit=101", 422),
        (f"{ROOT}/active-direction?limit=101", 422),
        ("/api/v2/market-environment/operations/run-1/checkpoints?limit=201", 422),
    )

    assert [(url, client.get(url).status_code) for url, _ in cases] == list(cases)


def test_v2_revision_precondition_conflict_is_stable() -> None:
    response = _client().get(
        f"{ROOT}/overview",
        headers={"If-Match": '"stale-revision"'},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "snapshot_revision_conflict"


def test_v2_reads_do_not_expose_write_methods_or_arbitrary_projection() -> None:
    client = _client()

    assert client.post(f"{ROOT}/overview").status_code == 405
    response = client.get(f"{ROOT}/overview?fields=indices&include=chapter01")
    assert response.status_code in {200, 422}
    if response.status_code == 200:
        assert "chapter01" not in response.text
