"""Contract, side-effect and publication-safety tests for AI discovery."""

from __future__ import annotations

import builtins
import copy
import pathlib
import socket
import sqlite3

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.engine import Connection

from src.market_environment.bootstrap.app import create_app
from src.market_environment.interfaces.http.discovery import (
    DiscoveryContractError,
    UnsafeDiscoveryContentError,
    render_llms_full_txt,
    render_llms_txt,
    validate_discovery_content,
    validate_discovery_contract,
)


OVERVIEW_PATH = "/api/v2/market-environment/{as_of}/overview"
HISTORY_PATH = "/api/v2/market-environment/{as_of}/indices/{code}/history"


@pytest.fixture(scope="module")
def openapi() -> dict:
    return create_app().openapi()


def test_renderer_is_pure_in_memory_and_performs_no_io(monkeypatch, openapi) -> None:
    calls = {"file": 0, "database": 0, "network": 0}

    def reject(kind):
        def rejected(*_args, **_kwargs):
            calls[kind] += 1
            raise AssertionError(f"discovery attempted {kind} I/O")

        return rejected

    monkeypatch.setattr(builtins, "open", reject("file"))
    monkeypatch.setattr(pathlib.Path, "write_text", reject("file"))
    monkeypatch.setattr(pathlib.Path, "write_bytes", reject("file"))
    monkeypatch.setattr(sqlite3, "connect", reject("database"))
    monkeypatch.setattr(Connection, "execute", reject("database"))
    monkeypatch.setattr(requests.sessions.Session, "request", reject("network"))
    monkeypatch.setattr(socket, "create_connection", reject("network"))

    compact = render_llms_txt(openapi)
    full = render_llms_full_txt(openapi)

    assert compact and full
    assert calls == {"file": 0, "database": 0, "network": 0}


def test_discovery_routes_are_utf8_plain_text_and_overview_first() -> None:
    client = TestClient(create_app())

    compact_response = client.get("/llms.txt")
    full_response = client.get("/llms-full.txt")

    for response in (compact_response, full_response):
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.content.decode("utf-8") == response.text
        assert "/openapi.json" in response.text

    compact = compact_response.text
    full = full_response.text
    assert compact.index(OVERVIEW_PATH) < compact.index(
        "/api/v2/market-environment/{as_of}/indices"
    )
    assert "Start with GET" in compact
    assert "exact-date" in compact
    assert "snapshotRevision" in compact

    for phrase in (
        "Recommended workflow",
        "explicit YYYY-MM-DD",
        "quality",
        "pagination.nextCursor",
        "missing, insufficient, degraded and failed-retained",
        "default 60, maximum 250",
        "default 20, maximum 100",
        "default 50, maximum 200",
        "HTTP 409",
    ):
        assert phrase in full


@pytest.mark.parametrize(
    "unsafe",
    (
        "Authorization: Bearer abcdefghijklmnop",
        "X-API-Key: super-secret-value",
        "https://example.test/file?X-Amz-Signature=deadbeef",
        "https://example.test/data?access_token=secret-token",
        'row={"code":"000001","close":10.2}',
        'row={"thscode":"885001.TI","amount":12345}',
    ),
)
def test_secret_provider_header_presigned_url_and_live_rows_are_rejected(unsafe: str) -> None:
    with pytest.raises(UnsafeDiscoveryContentError):
        validate_discovery_content(unsafe)


def test_published_documents_pass_the_security_scan(openapi) -> None:
    validate_discovery_content(render_llms_txt(openapi))
    validate_discovery_content(render_llms_full_txt(openapi))


def test_rendering_is_deterministic_even_if_openapi_paths_are_reordered(openapi) -> None:
    reversed_schema = copy.deepcopy(openapi)
    reversed_schema["paths"] = dict(reversed(list(reversed_schema["paths"].items())))

    assert render_llms_txt(openapi) == render_llms_txt(reversed_schema)
    assert render_llms_full_txt(openapi) == render_llms_full_txt(reversed_schema)


@pytest.mark.parametrize("mutation", ("path", "operation_id", "parameters", "response", "limit"))
def test_deliberately_altered_openapi_fixture_fails_drift_check(openapi, mutation: str) -> None:
    altered = copy.deepcopy(openapi)
    if mutation == "path":
        altered["paths"].pop(OVERVIEW_PATH)
    elif mutation == "operation_id":
        altered["paths"][OVERVIEW_PATH]["get"]["operationId"] = "driftedOverview"
    elif mutation == "parameters":
        altered["paths"][OVERVIEW_PATH]["get"]["parameters"].append(
            {"name": "include", "in": "query", "schema": {"type": "string"}}
        )
    elif mutation == "response":
        altered["paths"][OVERVIEW_PATH]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"] = "#/components/schemas/Chapter01Response"
    elif mutation == "limit":
        parameters = altered["paths"][HISTORY_PATH]["get"]["parameters"]
        limit = next(value for value in parameters if value["name"] == "limit")
        limit["schema"]["maximum"] = 9999

    with pytest.raises(DiscoveryContractError, match="discovery/OpenAPI drift"):
        validate_discovery_contract(altered)


def test_discovery_contract_covers_operation_ids_parameters_models_and_limits(openapi) -> None:
    validate_discovery_contract(openapi)
    full = render_llms_full_txt(openapi)

    assert "operationId: getV2MarketOverview" in full
    assert "parameters: as_of, revision, If-Match, If-None-Match" in full
    assert "responseModel: V2Envelope_dict_str__Any__" in full
    assert "paginationLimit: default 60, maximum 250" in full
