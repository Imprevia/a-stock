from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from src.market_environment.fuyao_market import (
    FuyaoMarketAdapter,
    FuyaoMarketClient,
    FuyaoMarketConfigurationError,
    FuyaoMarketContractError,
    FuyaoMarketPermissionError,
    FuyaoMarketRateLimitError,
    FuyaoMarketTransportError,
)


AS_OF = date(2026, 9, 18)
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/market-environment/fuyao-market-data.json").read_text(encoding="utf-8")
)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(session, **kwargs):
    return FuyaoMarketClient("fixture-key", session=session, sleep=lambda _: None, **kwargs)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (Response({"code": 2001, "data": None}), FuyaoMarketPermissionError),
        (Response({"code": 4001, "data": {}}), FuyaoMarketTransportError),
        (Response({"code": 0, "data": None}), FuyaoMarketContractError),
        (Response(ValueError("bad json")), FuyaoMarketContractError),
    ],
)
def test_generic_envelope_classifies_errors_without_secret_echo(response, error):
    with pytest.raises(error):
        client(Session([response]), max_retries=0).request("/fixture")
    assert "fixture-key" not in str(response.payload)


def test_generic_layer_retries_429_and_stops_at_budget():
    session = Session([Response({}, 429), Response({}, 429), Response({}, 429)])
    with pytest.raises(FuyaoMarketRateLimitError):
        client(session, max_retries=2, request_budget=3).request("/fixture")
    assert len(session.calls) == 3


def test_missing_key_fails_closed_without_request():
    session = Session([])
    with pytest.raises(FuyaoMarketConfigurationError):
        FuyaoMarketClient(session=session).request("/fixture")
    assert session.calls == []


def test_core_normalization_keeps_bars_and_missing_date_insufficient():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_core(FIXTURE["core"], AS_OF, min_bars=2)["sh000001"]
    assert result.status == "insufficient"  # fixture's last date intentionally differs from AS_OF
    assert result.payload["bars"][-1].amount == 120000000000
    assert result.quality["asOf"] == AS_OF.isoformat()


def test_core_accepts_exact_date_and_rejects_identity_mismatch():
    adapter = FuyaoMarketAdapter()
    rows = [dict(row, date="2026-09-18") for row in FIXTURE["core"]["sh000001"]]
    rows[-1]["thscode"] = "399001.SZ"
    result = adapter.normalize_core({"sh000001": rows}, AS_OF, min_bars=2)["sh000001"]
    assert result.status == "insufficient"
    assert any("identity mismatch" in item for item in result.warnings)


def test_breadth_requires_complete_stable_pagination_and_real_identities():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_breadth(FIXTURE["breadth_pages"], AS_OF)
    assert result.status == "ok"
    assert result.payload["validCount"] == 4
    assert result.payload["advanceCount"] == 2

    changed = json.loads(json.dumps(FIXTURE["breadth_pages"]))
    changed[1]["pagination"]["total"] = 5
    rejected = adapter.normalize_breadth(changed, AS_OF)
    assert rejected.status == "insufficient"
    assert any("pagination total changed" in item for item in rejected.warnings)


def test_active_direction_requires_ordering_evidence_and_thirty_rows():
    adapter = FuyaoMarketAdapter()
    base = FIXTURE["active_direction_row"]
    rows = [dict(base, thscode=f"{600001 + i:06d}.SH", ticker=f"{600001 + i:06d}", amount=30000 - i, name=f"样本{i}") for i in range(30)]
    result = adapter.normalize_active_direction(rows, AS_OF, ordering_proven=True)
    assert result.status == "ok"
    assert len(result.payload["topStocks"]) == 30
    rejected = adapter.normalize_active_direction(rows, AS_OF)
    assert rejected.status == "ineligible"
    assert any("ordering" in item for item in rejected.warnings)


def test_sectors_reject_code_as_leader_and_missing_fields():
    adapter = FuyaoMarketAdapter()
    result = adapter.normalize_sectors(FIXTURE["sectors"], AS_OF)
    assert result.status == "ok"
    bad = [dict(FIXTURE["sectors"][0], leader="600001.SH", main_net=None)]
    rejected = adapter.normalize_sectors(bad, AS_OF)
    assert rejected.status in {"ineligible", "insufficient"}
    assert rejected.payload["rows"][0]["leader"] is None
    assert rejected.payload["rows"][0]["mainNet"] is None


def test_fixture_contains_no_credentials():
    serialized = json.dumps(FIXTURE, ensure_ascii=False).lower()
    assert "api-key" not in serialized
    assert "fixture-key" not in serialized
    assert "secret" not in serialized
