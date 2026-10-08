from __future__ import annotations

import json
from collections import deque
from threading import Event, Thread

import pytest

from src.trading_system.data.provider_http import (
    HostPolicy,
    ProviderHttpClient,
    ProviderHttpError,
    TransportEngineRegistry,
    TransportFailure,
    TransportFailureCategory,
    TransportPolicyGateway,
    TransportRequest,
    TransportResponse,
    configure_process_transport_gateway,
    get_process_transport_gateway,
    reset_process_transport_gateway_for_testing,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SequenceEngine:
    def __init__(self, name: str = "requests", results: tuple[object, ...] = ()) -> None:
        self.name = name
        self.results = deque(results)
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        if not self.results:
            raise AssertionError("unexpected engine attempt")
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, TransportResponse)
        return result


def no_wait_policy(**overrides: object) -> HostPolicy:
    values: dict[str, object] = {
        "minimum_interval": 0.0,
        "jitter": (0.0, 0.0),
        "timeout": 2.0,
        "max_retries": 0,
        "retry_backoff": 0.0,
        "request_budget": 100,
        "failure_threshold": 3,
        "cooldown_seconds": 30.0,
        "cache_ttl_seconds": 0.0,
    }
    values.update(overrides)
    return HostPolicy(**values)


def gateway_for(
    *engines: SequenceEngine,
    policy: HostPolicy | None = None,
    clock: FakeClock | None = None,
    sleeps: list[float] | None = None,
) -> TransportPolicyGateway:
    clock = clock or FakeClock()
    sleeps = sleeps if sleeps is not None else []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    return TransportPolicyGateway(
        TransportEngineRegistry(engines),
        default_policy=policy or no_wait_policy(),
        clock=clock,
        sleeper=sleep,
        random_uniform=lambda _low, _high: 0.0,
    )


def test_registry_is_complete_unique_and_fails_closed_before_io() -> None:
    engine = SequenceEngine(results=(TransportResponse(200),))

    with pytest.raises(ValueError, match="default.*not registered"):
        TransportEngineRegistry((), default_engine="requests")
    with pytest.raises(ValueError, match="duplicate"):
        TransportEngineRegistry((engine, engine))

    gateway = gateway_for(engine)
    with pytest.raises(TransportFailure) as caught:
        gateway.request(
            TransportRequest(
                "GET",
                "https://quotes.example.test/data",
                engine="unregistered",
            )
        )

    assert caught.value.category is TransportFailureCategory.ENGINE_UNAVAILABLE
    assert engine.calls == []


def test_gateway_owns_the_only_retry_and_request_budget() -> None:
    engine = SequenceEngine(
        results=(
            TransportResponse(503),
            TransportResponse(429, headers={"Retry-After": "2"}),
            TransportResponse(200, body=b'{"ok":true}'),
        )
    )
    sleeps: list[float] = []
    gateway = gateway_for(
        engine,
        policy=no_wait_policy(max_retries=2, retry_backoff=0.5, request_budget=3),
        sleeps=sleeps,
    )

    response = gateway.request(
        TransportRequest("GET", "https://quotes.example.test/data"),
    )

    assert response.json() == {"ok": True}
    assert len(engine.calls) == 3
    assert sleeps == [pytest.approx(0.5), pytest.approx(2.0)]
    diagnostics = gateway.host_diagnostics("quotes.example.test")
    assert diagnostics["requestsUsed"] == 3
    assert diagnostics["lastRetryCount"] == 2


def test_retry_after_bound_preserves_selected_engine_and_redacts_endpoint() -> None:
    primary = SequenceEngine("requests")
    alternate = SequenceEngine(
        "alternate",
        results=(
            TransportResponse(
                429,
                headers={
                    "Retry-After": "301",
                    "Content-Type": "application/json",
                },
                body=json.dumps(
                    {
                        "code": 5003,
                        "message": "retry secret later",
                        "request_id": "request-retry-after",
                    }
                ),
                final_url="https://quotes.example.test/data?token=secret",
                engine="alternate",
            ),
        ),
    )
    gateway = gateway_for(
        primary,
        alternate,
        policy=no_wait_policy(max_retries=1, max_retry_after_seconds=300.0),
    )

    with pytest.raises(TransportFailure) as caught:
        gateway.request(
            TransportRequest(
                "GET",
                "https://quotes.example.test/data?token=secret",
                engine="alternate",
            )
        )

    assert caught.value.category is TransportFailureCategory.RETRY_AFTER_EXCEEDED
    assert caught.value.engine == "alternate"
    assert caught.value.status_code == 429
    assert caught.value.final_url == "https://quotes.example.test/data"
    assert caught.value.response_evidence["request_id"] == "request-retry-after"
    assert caught.value.response_evidence["message"] == "retry <redacted> later"
    assert "secret" not in str(caught.value)
    assert primary.calls == []
    assert len(alternate.calls) == 1


def test_two_facades_share_budget_and_circuit_state() -> None:
    clock = FakeClock()
    engine = SequenceEngine(
        results=(
            TransportResponse(503),
            TransportResponse(200, body=b"recovered"),
        )
    )
    gateway = gateway_for(
        engine,
        policy=no_wait_policy(
            max_retries=0,
            request_budget=2,
            failure_threshold=1,
            cooldown_seconds=30.0,
        ),
        clock=clock,
    )
    first = ProviderHttpClient(gateway=gateway, ua_selector=lambda _values: "fixture-UA")
    second = ProviderHttpClient(gateway=gateway, ua_selector=lambda _values: "fixture-UA")

    with pytest.raises(ProviderHttpError):
        first.get("https://quotes.example.test/first", cache_ttl=0.0)
    with pytest.raises(ProviderHttpError) as cooling_down:
        second.get("https://quotes.example.test/second", cache_ttl=0.0)

    assert cooling_down.value.kind == "circuit_open"
    assert len(engine.calls) == 1

    clock.advance(30.0)
    assert second.get("https://quotes.example.test/second", cache_ttl=0.0).content == b"recovered"
    assert len(engine.calls) == 2
    assert gateway.host_diagnostics("quotes.example.test")["requestsUsed"] == 2


def test_explicit_alternative_engine_cannot_bypass_a_host_circuit() -> None:
    primary = SequenceEngine("requests", results=(TransportResponse(503),))
    alternate = SequenceEngine("alternate", results=(TransportResponse(200),))
    gateway = gateway_for(
        primary,
        alternate,
        policy=no_wait_policy(max_retries=0, failure_threshold=1),
    )

    with pytest.raises(TransportFailure):
        gateway.request(TransportRequest("GET", "https://quotes.example.test/first"))
    with pytest.raises(TransportFailure) as caught:
        gateway.request(
            TransportRequest(
                "GET",
                "https://quotes.example.test/second",
                engine="alternate",
            )
        )

    assert caught.value.category is TransportFailureCategory.CIRCUIT_OPEN
    assert len(primary.calls) == 1
    assert alternate.calls == []


def test_two_facades_share_one_inflight_engine_attempt() -> None:
    started = Event()
    release = Event()

    class BlockingEngine:
        name = "requests"

        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            started.set()
            assert release.wait(timeout=2.0)
            return TransportResponse(200, body=b"shared")

    engine = BlockingEngine()
    gateway = TransportPolicyGateway(
        TransportEngineRegistry((engine,)),
        default_policy=no_wait_policy(cache_ttl_seconds=10.0),
    )
    first_client = ProviderHttpClient(gateway=gateway)
    second_client = ProviderHttpClient(gateway=gateway)
    responses: list[TransportResponse] = []

    request_kwargs = {
        "params": {"symbols": ["000001", "399001"]},
        "requested_date": "2026-09-18",
    }
    first = Thread(
        target=lambda: responses.append(
            first_client.get("https://quotes.example.test/data", **request_kwargs)
        )
    )
    second = Thread(
        target=lambda: responses.append(
            second_client.get("https://quotes.example.test/data", **request_kwargs)
        )
    )
    first.start()
    assert started.wait(timeout=2.0)
    second.start()
    release.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert engine.calls == 1
    assert len(responses) == 2
    assert responses[0] is responses[1]


def test_request_identity_isolates_date_engine_params_and_authentication_scope() -> None:
    requests_engine = SequenceEngine(
        "requests",
        results=(
            TransportResponse(200, body=b"requests-one"),
            TransportResponse(200, body=b"requests-date"),
            TransportResponse(200, body=b"requests-params"),
            TransportResponse(200, body=b"requests-auth"),
        ),
    )
    alternate_engine = SequenceEngine(
        "alternate",
        results=(TransportResponse(200, body=b"alternate"),),
    )
    gateway = gateway_for(
        requests_engine,
        alternate_engine,
        policy=no_wait_policy(cache_ttl_seconds=60.0),
    )
    base = {
        "method": "GET",
        "url": "https://quotes.example.test/data?b=2&a=1",
        "params": {"symbols": ["000001", "399001"], "fields": {"price": True}},
        "requested_date": "2026-09-18",
        "authentication_scope": "account-a-secret",
    }

    first_request = TransportRequest(**base)
    first = gateway.request(first_request)
    equivalent = gateway.request(
        TransportRequest(
            "GET",
            "https://quotes.example.test/data?a=1&b=2",
            params={"fields": {"price": True}, "symbols": ["000001", "399001"]},
            requested_date="2026-09-18",
            authentication_scope="account-a-secret",
        )
    )
    other_date = gateway.request(
        TransportRequest(**{**base, "requested_date": "2026-09-19"})
    )
    other_params = gateway.request(
        TransportRequest(
            **{**base, "params": {**base["params"], "page": 2}},
        )
    )
    other_auth = gateway.request(
        TransportRequest(**{**base, "authentication_scope": "account-b-secret"})
    )
    other_engine = gateway.request(
        TransportRequest(**{**base, "engine": "alternate"})
    )

    assert equivalent is first
    assert other_date.content == b"requests-date"
    assert other_params.content == b"requests-params"
    assert other_auth.content == b"requests-auth"
    assert other_engine.content == b"alternate"
    assert len(requests_engine.calls) == 4
    assert len(alternate_engine.calls) == 1

    identities = {
        gateway.request_identity(first_request),
        gateway.request_identity(TransportRequest(**{**base, "requested_date": "2026-09-19"})),
        gateway.request_identity(TransportRequest(**{**base, "authentication_scope": "account-b-secret"})),
        gateway.request_identity(TransportRequest(**{**base, "engine": "alternate"})),
    }
    assert len(identities) == 4
    assert all(len(identity) == 64 for identity in identities)
    assert all("secret" not in identity for identity in identities)
    assert gateway.request_identity(
        TransportRequest(**{**base, "max_response_bytes": 1024})
    ) != gateway.request_identity(
        TransportRequest(**{**base, "max_response_bytes": 2048})
    )


def test_diagnostics_and_failures_redact_credentials_query_and_scope() -> None:
    engine = SequenceEngine(results=(TransportResponse(200, body=b"ok"),))
    gateway = gateway_for(engine)
    secret = "never-persist-this"
    request = TransportRequest(
        "GET",
        f"https://user:{secret}@quotes.example.test/data?api_key={secret}",
        params={"token": secret, "symbols": ["000001"]},
        headers={"Cookie": f"session={secret}"},
        authentication_scope=secret,
        tenant_scope="tenant-private",
    )

    gateway.request(request)
    diagnostics = gateway.host_diagnostics("quotes.example.test")
    encoded = json.dumps(diagnostics, sort_keys=True)

    assert diagnostics["host"] == "quotes.example.test"
    assert diagnostics["endpoint"] == "https://quotes.example.test/data"
    assert len(diagnostics["requestIdentity"]) == 64
    assert len(diagnostics["authenticationScopeDigest"]) == 64
    assert secret not in encoded
    assert "tenant-private" not in encoded
    assert "api_key" not in encoded
    assert secret not in repr(request)


def test_http_failure_retains_only_bounded_redacted_response_evidence() -> None:
    secret = "never-persist-this"
    engine = SequenceEngine(
        results=(
            TransportResponse(
                429,
                headers={"Content-Type": "application/json"},
                body=json.dumps(
                    {
                        "code": 5003,
                        "message": f"upstream {secret} unavailable",
                        "request_id": "request-429",
                        "secret": "raw-provider-secret",
                        "data": {"raw": "body-must-not-escape"},
                    }
                ),
            ),
        )
    )
    gateway = gateway_for(engine, policy=no_wait_policy(max_retries=0))

    with pytest.raises(TransportFailure) as caught:
        gateway.request(
            TransportRequest(
                "GET",
                "https://quotes.example.test/data",
                headers={"Authorization": secret},
            )
        )

    assert caught.value.response_evidence == {
        "code": "5003",
        "message": "upstream <redacted> unavailable",
        "request_id": "request-429",
    }
    encoded = json.dumps(caught.value.response_evidence)
    assert secret not in encoded
    assert "raw-provider-secret" not in encoded
    assert "body-must-not-escape" not in encoded


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (TransportResponse(401), TransportFailureCategory.PERMISSION),
        (TransportResponse(403), TransportFailureCategory.PERMISSION),
        (
            TransportResponse(
                200,
                headers={"Content-Type": "text/html"},
                body=b"<html><title>Verify you are human</title><div>CAPTCHA</div></html>",
            ),
            TransportFailureCategory.CHALLENGE,
        ),
    ],
)
def test_permission_and_challenge_fail_fast_without_retry_or_engine_switch(
    response: TransportResponse,
    category: TransportFailureCategory,
) -> None:
    primary = SequenceEngine("requests", results=(response, TransportResponse(200)))
    alternate = SequenceEngine("alternate", results=(TransportResponse(200),))
    gateway = gateway_for(
        primary,
        alternate,
        policy=no_wait_policy(max_retries=3),
    )

    with pytest.raises(TransportFailure) as caught:
        gateway.request(TransportRequest("GET", "https://quotes.example.test/data"))

    assert caught.value.category is category
    assert caught.value.retryable is False
    assert len(primary.calls) == 1
    assert alternate.calls == []


def test_gateway_overrides_an_engine_that_marks_permission_as_retryable() -> None:
    permission = TransportFailure(
        "raw engine detail must not escape",
        category=TransportFailureCategory.PERMISSION,
        retryable=True,
        status_code=403,
        final_url="https://quotes.example.test/data?token=secret",
    )
    primary = SequenceEngine(
        "requests",
        results=(permission, TransportResponse(200)),
    )
    alternate = SequenceEngine("alternate", results=(TransportResponse(200),))
    gateway = gateway_for(
        primary,
        alternate,
        policy=no_wait_policy(max_retries=3),
    )

    with pytest.raises(TransportFailure) as caught:
        gateway.request(TransportRequest("GET", "https://quotes.example.test/data"))

    assert caught.value.category is TransportFailureCategory.PERMISSION
    assert caught.value.retryable is False
    assert "raw engine detail" not in str(caught.value)
    assert "secret" not in str(caught.value)
    assert caught.value.final_url == "https://quotes.example.test/data"
    assert len(primary.calls) == 1
    assert alternate.calls == []


def test_process_composition_helper_returns_one_gateway_and_rejects_replacement() -> None:
    reset_process_transport_gateway_for_testing()
    engine = SequenceEngine(results=(TransportResponse(200),))
    gateway = gateway_for(engine)
    try:
        assert configure_process_transport_gateway(gateway) is gateway
        assert get_process_transport_gateway() is gateway
        with pytest.raises(RuntimeError, match="already configured"):
            configure_process_transport_gateway(gateway_for(SequenceEngine()))
    finally:
        reset_process_transport_gateway_for_testing()
