from __future__ import annotations

import json
from datetime import date

import pytest

from src.market_environment.fuyao import (
    FuyaoClient,
    FuyaoConfigurationError,
    FuyaoPermissionError,
    FuyaoTransportError,
)
from src.market_environment.fuyao_market import (
    FuyaoMarketClient,
    FuyaoMarketPermissionError,
    FuyaoMarketRateLimitError,
    FuyaoMarketTransportError,
)
from src.trading_system.data.provider_transport import (
    HostPolicy,
    TransportEngineRegistry,
    TransportFailure,
    TransportFailureCategory,
    TransportPolicyGateway,
    TransportResponse,
)


class SequenceEngine:
    name = "requests"

    def __init__(self, *results: TransportResponse | BaseException) -> None:
        self.results = list(results)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def response(payload: object, status: int = 200) -> TransportResponse:
    return TransportResponse(
        status,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload),
        final_url="https://fuyao.aicubes.cn/fixture",
    )


def gateway(engine: SequenceEngine, *, retries: int = 0, budget: int = 20) -> TransportPolicyGateway:
    return TransportPolicyGateway(
        TransportEngineRegistry((engine,)),
        default_policy=HostPolicy(
            minimum_interval=0.0,
            jitter=(0.0, 0.0),
            timeout=1.0,
            max_retries=retries,
            retry_backoff=0.0,
            request_budget=budget,
            failure_threshold=20,
            cache_ttl_seconds=0.0,
        ),
        sleeper=lambda _delay: None,
        random_uniform=lambda _low, _high: 0.0,
    )


def test_missing_api_key_fails_before_the_shared_gateway() -> None:
    engine = SequenceEngine(response({"code": 0, "data": {}}))
    shared = gateway(engine)

    with pytest.raises(FuyaoConfigurationError):
        FuyaoClient("", transport_gateway=shared).fetch_trading_days()

    assert engine.requests == []
    assert shared.host_diagnostics("fuyao.aicubes.cn")["requestsUsed"] == 0


def test_market_and_limits_clients_share_one_host_budget() -> None:
    engine = SequenceEngine(response({"code": 0, "data": {}}))
    shared = gateway(engine, budget=1)
    market = FuyaoMarketClient("fixture-key", transport_gateway=shared, max_retries=0)
    limits = FuyaoClient("fixture-key", transport_gateway=shared, max_retries=0)

    assert market.request("/market").data == {}
    with pytest.raises(FuyaoTransportError, match="governed retries"):
        limits._request_data("/limits")

    assert len(engine.requests) == 1
    diagnostics = shared.host_diagnostics("fuyao.aicubes.cn")
    assert diagnostics["requestsUsed"] == 2
    assert diagnostics["authenticationScopeDigest"] != "fixture-key"
    assert "fixture-key" not in json.dumps(diagnostics)


@pytest.mark.parametrize(
    ("client_factory", "error"),
    [
        (
            lambda shared: FuyaoMarketClient(
                "fixture-key", transport_gateway=shared, max_retries=1
            ).request("/fixture"),
            FuyaoMarketTransportError,
        ),
        (
            lambda shared: FuyaoClient(
                "fixture-key", transport_gateway=shared, max_retries=1
            )._request_data("/fixture"),
            FuyaoTransportError,
        ),
    ],
)
def test_transport_retry_budget_is_owned_only_by_gateway(client_factory, error) -> None:
    failure = TransportFailure(
        "offline fixture",
        category=TransportFailureCategory.NETWORK,
        retryable=True,
        engine="requests",
        final_url="https://fuyao.aicubes.cn/fixture",
    )
    engine = SequenceEngine(failure, failure)
    shared = gateway(engine, retries=1)

    with pytest.raises(error):
        client_factory(shared)

    assert len(engine.requests) == 2
    assert shared.host_diagnostics("fuyao.aicubes.cn")["lastRetryCount"] == 1


@pytest.mark.parametrize(
    ("client_factory", "error"),
    [
        (
            lambda shared: FuyaoMarketClient(
                "fixture-key", transport_gateway=shared, max_retries=2
            ).request("/fixture"),
            FuyaoMarketPermissionError,
        ),
        (
            lambda shared: FuyaoClient(
                "fixture-key", transport_gateway=shared, max_retries=2
            )._request_data("/fixture"),
            FuyaoPermissionError,
        ),
    ],
)
def test_http_permission_failure_is_not_retried(client_factory, error) -> None:
    engine = SequenceEngine(response({"code": 2001, "data": None}, status=403))
    shared = gateway(engine, retries=2)

    with pytest.raises(error):
        client_factory(shared)

    assert len(engine.requests) == 1


@pytest.mark.parametrize(
    ("status", "client_factory", "error"),
    [
        (
            429,
            lambda shared: FuyaoMarketClient(
                "fixture-key", transport_gateway=shared, max_retries=0
            ).request("/fixture"),
            FuyaoMarketRateLimitError,
        ),
        (
            429,
            lambda shared: FuyaoClient(
                "fixture-key", transport_gateway=shared, max_retries=0
            )._request_data("/fixture"),
            FuyaoTransportError,
        ),
        (
            503,
            lambda shared: FuyaoMarketClient(
                "fixture-key", transport_gateway=shared, max_retries=0
            ).request("/fixture"),
            FuyaoMarketTransportError,
        ),
        (
            503,
            lambda shared: FuyaoClient(
                "fixture-key", transport_gateway=shared, max_retries=0
            )._request_data("/fixture"),
            FuyaoTransportError,
        ),
    ],
)
def test_http_failure_preserves_redacted_fuyao_request_evidence(
    status, client_factory, error
) -> None:
    request_id = f"req-http-{status}"
    engine = SequenceEngine(
        response(
            {
                "code": 5003,
                "message": "upstream fixture-key unavailable",
                "request_id": request_id,
                "data": None,
                "secret": "must-not-escape",
            },
            status=status,
        )
    )
    shared = gateway(engine)

    with pytest.raises(error) as caught:
        client_factory(shared)

    message = str(caught.value)
    assert "code=5003" in message
    assert "message=upstream <redacted> unavailable" in message
    assert f"request_id={request_id}" in message
    assert "fixture-key" not in message
    assert "must-not-escape" not in message
    assert len(engine.requests) == 1


def test_fuyao_request_identity_carries_date_source_auth_scope_and_redirect_policy() -> None:
    as_of = date(2026, 9, 18)
    engine = SequenceEngine(response({"code": 0, "data": {}}))
    shared = gateway(engine)

    FuyaoMarketClient(
        "fixture-key", transport_gateway=shared, max_retries=0
    ).request("/fixture", params={"page": 1}, requested_date=as_of)

    request = engine.requests[0]
    assert request.requested_date == as_of.isoformat()
    assert request.source_id == "fuyao-market-v2:/fixture"
    assert request.allow_redirects is False
    assert len(request.authentication_scope_digest) == 64
    assert request.authentication_scope_digest != "fixture-key"
