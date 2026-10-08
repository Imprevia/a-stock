from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import pytest
import requests

from src.trading_system.data.provider_http import (
    HostPolicy,
    ProviderHttpClient,
    RequestsTransportEngine,
    ScraplingStaticEngineConfig,
    ScraplingStaticHttpEngine,
    TransportEngineRegistry,
    TransportFailure,
    TransportFailureCategory,
    TransportPolicyGateway,
    TransportRequest,
    TransportResponse,
)


URL = "https://quotes.example.test/data"
SOURCE_ID = "authorized-quotes"


@dataclass
class NativeResponse:
    content: object = b'{"date":"2026-09-18","value":1}'
    status_code: object = 200
    headers: object = None
    url: str = f"{URL}/final"

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {"Content-Type": "application/json; charset=utf-8"}


class RecordingSession:
    def __init__(self, results: list[object]) -> None:
        self.results = deque(results)
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> NativeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, NativeResponse)
        return result


class RecordingFetcher:
    def __init__(self, results: list[object]) -> None:
        self.results = deque(results)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> Any:
        self.calls.append({"url": url, **kwargs})
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


def allowlisted_config() -> ScraplingStaticEngineConfig:
    return ScraplingStaticEngineConfig(
        enabled=True,
        allowlist=frozenset({("quotes.example.test", SOURCE_ID)}),
    )


def no_retry_policy() -> HostPolicy:
    return HostPolicy(
        minimum_interval=0.0,
        jitter=(0.0, 0.0),
        max_retries=0,
        retry_backoff=0.0,
        cache_ttl_seconds=0.0,
        failure_threshold=10,
    )


def gateway_for(*engines: object, max_retries: int = 0) -> TransportPolicyGateway:
    policy = no_retry_policy()
    if max_retries:
        policy = HostPolicy(
            minimum_interval=0.0,
            jitter=(0.0, 0.0),
            max_retries=max_retries,
            retry_backoff=0.0,
            cache_ttl_seconds=0.0,
            failure_threshold=10,
        )
    return TransportPolicyGateway(
        TransportEngineRegistry(engines),  # type: ignore[arg-type]
        default_policy=policy,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
    )


def scrapling_request(**overrides: Any) -> TransportRequest:
    values: dict[str, Any] = {
        "method": "GET",
        "url": URL,
        "params": {"symbol": "000001"},
        "headers": {"Accept": "application/json"},
        "timeout": 3.0,
        "requested_date": "2026-09-18",
        "source_id": SOURCE_ID,
        "engine": "scrapling",
    }
    values.update(overrides)
    return TransportRequest(**values)


def test_scrapling_is_disabled_with_an_empty_allowlist_by_default() -> None:
    loader_calls = 0

    def loader() -> RecordingFetcher:
        nonlocal loader_calls
        loader_calls += 1
        return RecordingFetcher([NativeResponse()])

    engine = ScraplingStaticHttpEngine(fetcher_loader=loader)

    with pytest.raises(TransportFailure) as caught:
        engine.send(scrapling_request())

    assert caught.value.category is TransportFailureCategory.CONFIGURATION
    assert caught.value.retryable is False
    assert engine.config.enabled is False
    assert engine.config.allowlist == frozenset()
    assert loader_calls == 0


@pytest.mark.parametrize(
    ("url", "source_id"),
    [
        ("https://other.example.test/data", SOURCE_ID),
        (URL, "other-source"),
        (URL, None),
    ],
)
def test_non_allowlisted_host_source_pair_fails_before_loading_scrapling(
    url: str,
    source_id: str | None,
) -> None:
    loader_calls = 0

    def loader() -> RecordingFetcher:
        nonlocal loader_calls
        loader_calls += 1
        return RecordingFetcher([NativeResponse()])

    engine = ScraplingStaticHttpEngine(
        ScraplingStaticEngineConfig(
            enabled=True,
            allowlist=frozenset(
                {
                    ("quotes.example.test", SOURCE_ID),
                    ("other.example.test", "other-source"),
                }
            ),
        ),
        fetcher_loader=loader,
    )

    with pytest.raises(TransportFailure) as caught:
        engine.send(scrapling_request(url=url, source_id=source_id))

    assert caught.value.category is TransportFailureCategory.CONFIGURATION
    assert loader_calls == 0


@pytest.mark.parametrize(
    "transport_request",
    [
        scrapling_request(method="POST"),
        scrapling_request(body=b"not-supported"),
    ],
)
def test_unsupported_scrapling_requests_fail_before_loader_or_fetcher(
    transport_request: TransportRequest,
) -> None:
    loader_calls = 0

    def loader() -> RecordingFetcher:
        nonlocal loader_calls
        loader_calls += 1
        return RecordingFetcher([NativeResponse()])

    engine = ScraplingStaticHttpEngine(
        allowlisted_config(),
        fetcher_loader=loader,
    )

    with pytest.raises(TransportFailure) as caught:
        engine.send(transport_request)

    assert caught.value.category is TransportFailureCategory.CONFIGURATION
    assert loader_calls == 0


def test_missing_optional_dependency_fails_closed_without_upstream_request() -> None:
    loader_calls = 0

    def missing_loader() -> object:
        nonlocal loader_calls
        loader_calls += 1
        raise ModuleNotFoundError("No module named 'scrapling'")

    engine = ScraplingStaticHttpEngine(
        allowlisted_config(),
        fetcher_loader=missing_loader,
    )

    with pytest.raises(TransportFailure) as caught:
        engine.send(scrapling_request())

    assert caught.value.category is TransportFailureCategory.ENGINE_UNAVAILABLE
    assert caught.value.retryable is False
    assert caught.value.engine == "scrapling"
    assert loader_calls == 1


def test_scrapling_dependency_is_loaded_only_for_an_authorized_scrapling_attempt() -> None:
    loader_calls = 0
    fetcher = RecordingFetcher([NativeResponse()])

    def loader() -> RecordingFetcher:
        nonlocal loader_calls
        loader_calls += 1
        return fetcher

    requests_session = RecordingSession([NativeResponse(content=b"requests")])
    requests_engine = RequestsTransportEngine(session=requests_session)
    scrapling_engine = ScraplingStaticHttpEngine(
        allowlisted_config(),
        fetcher_loader=loader,
    )
    gateway = gateway_for(requests_engine, scrapling_engine)

    assert loader_calls == 0
    assert gateway.request(TransportRequest("GET", URL)).content == b"requests"
    assert loader_calls == 0
    assert fetcher.calls == []

    gateway.request(scrapling_request())

    assert loader_calls == 1
    assert len(fetcher.calls) == 1


def test_scrapling_static_fetch_is_one_attempt_with_all_escalation_disabled() -> None:
    fetcher = RecordingFetcher([NativeResponse()])
    engine = ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher)

    response = engine.send(scrapling_request(max_response_bytes=1024))

    assert response.engine == "scrapling"
    assert response.status_code == 200
    assert response.json()["date"] == "2026-09-18"
    assert engine.internal_retries == 0
    assert engine.blocked_request_escalation is False
    assert engine.proxy_rotation is False
    assert engine.challenge_solving is False
    assert engine.browser_enabled is False
    assert fetcher.calls == [
        {
            "url": URL,
            "params": {"symbol": "000001"},
            "headers": {"Accept": "application/json"},
            "retries": 0,
            "timeout": 3.0,
        }
    ]
    forbidden_options = {
        "proxy",
        "proxies",
        "browser",
        "solve_challenge",
        "stealth",
    }
    assert forbidden_options.isdisjoint(fetcher.calls[0])


def test_scrapling_normalizes_native_status_and_body_attributes() -> None:
    class ScraplingNativeResponse:
        status = 202
        headers = {"Content-Type": "text/plain; charset=utf-8", "X-Trace": "trace-1"}
        content = None
        body = b"accepted"
        url = f"{URL}/accepted"

    fetcher = RecordingFetcher([ScraplingNativeResponse()])
    engine = ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher)

    response = engine.send(scrapling_request(max_response_bytes=16))

    assert response.status_code == 202
    assert response.headers["X-Trace"] == "trace-1"
    assert response.content == b"accepted"
    assert response.text == "accepted"
    assert response.final_url == f"{URL}/accepted"


def test_scrapling_rejects_a_response_over_the_configured_bound() -> None:
    fetcher = RecordingFetcher([NativeResponse(content=b"12345")])
    engine = ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher)

    with pytest.raises(TransportFailure) as caught:
        engine.send(scrapling_request(max_response_bytes=4))

    assert caught.value.category is TransportFailureCategory.RESPONSE_TOO_LARGE
    assert caught.value.status_code == 200
    assert caught.value.retryable is False
    assert len(fetcher.calls) == 1


def test_provider_http_facade_passes_source_identity_to_scrapling() -> None:
    fetcher = RecordingFetcher([NativeResponse()])
    gateway = gateway_for(
        RequestsTransportEngine(session=RecordingSession([NativeResponse()])),
        ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher),
    )
    client = ProviderHttpClient(
        gateway=gateway,
        request_date=lambda: "2026-09-18",
        ua_selector=lambda _pool: "fixture-UA",
    )

    response = client.get(
        URL,
        engine="scrapling",
        source_id=SOURCE_ID,
        cache_ttl=0.0,
    )

    assert response.engine == "scrapling"
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError("slow"), ConnectionError("offline")])
def test_scrapling_fetcher_exception_issues_only_one_engine_attempt(
    error: Exception,
) -> None:
    fetcher = RecordingFetcher([error, NativeResponse()])
    engine = ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher)

    with pytest.raises(TransportFailure) as caught:
        engine.send(scrapling_request())

    expected = (
        TransportFailureCategory.TIMEOUT
        if isinstance(error, TimeoutError)
        else TransportFailureCategory.NETWORK
    )
    assert caught.value.category is expected
    assert caught.value.retryable is True
    assert len(fetcher.calls) == 1


def test_unknown_engine_fails_without_loading_or_calling_scrapling() -> None:
    loader_calls = 0

    def loader() -> RecordingFetcher:
        nonlocal loader_calls
        loader_calls += 1
        return RecordingFetcher([NativeResponse()])

    requests_engine = RequestsTransportEngine(session=RecordingSession([NativeResponse()]))
    scrapling_engine = ScraplingStaticHttpEngine(
        allowlisted_config(),
        fetcher_loader=loader,
    )
    gateway = gateway_for(requests_engine, scrapling_engine)

    with pytest.raises(TransportFailure) as caught:
        gateway.request(TransportRequest("GET", URL, engine="unknown"))

    assert caught.value.category is TransportFailureCategory.ENGINE_UNAVAILABLE
    assert loader_calls == 0


@pytest.mark.parametrize(
    "result",
    [
        NativeResponse(status_code=401),
        NativeResponse(status_code=403),
        NativeResponse(
            content=b"<html><title>Verify you are human</title><div>CAPTCHA</div></html>",
            headers={"Content-Type": "text/html"},
        ),
        requests.ConnectionError("offline"),
    ],
)
def test_requests_failure_never_escalates_to_scrapling(result: object) -> None:
    requests_results = (
        [requests.ConnectionError("offline") for _attempt in range(4)]
        if isinstance(result, requests.ConnectionError)
        else [result, NativeResponse()]
    )
    requests_session = RecordingSession(requests_results)
    scrapling_fetcher = RecordingFetcher([NativeResponse()])
    gateway = gateway_for(
        RequestsTransportEngine(session=requests_session),
        ScraplingStaticHttpEngine(allowlisted_config(), fetcher=scrapling_fetcher),
        max_retries=3,
    )

    with pytest.raises(TransportFailure):
        gateway.request(TransportRequest("GET", URL, source_id=SOURCE_ID))

    assert scrapling_fetcher.calls == []
    if isinstance(result, requests.ConnectionError):
        assert len(requests_session.calls) == 4
    else:
        assert len(requests_session.calls) == 1


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (NativeResponse(status_code=401), TransportFailureCategory.PERMISSION),
        (NativeResponse(status_code=403), TransportFailureCategory.PERMISSION),
        (
            NativeResponse(
                content=b"<html><title>Verify you are human</title><div>CAPTCHA</div></html>",
                headers={"Content-Type": "text/html"},
            ),
            TransportFailureCategory.CHALLENGE,
        ),
    ],
)
def test_direct_scrapling_permission_and_challenge_fail_after_one_attempt(
    response: NativeResponse,
    category: TransportFailureCategory,
) -> None:
    fetcher = RecordingFetcher([response, NativeResponse()])
    gateway = gateway_for(
        RequestsTransportEngine(session=RecordingSession([NativeResponse()])),
        ScraplingStaticHttpEngine(allowlisted_config(), fetcher=fetcher),
        max_retries=3,
    )

    with pytest.raises(TransportFailure) as caught:
        gateway.request(scrapling_request())

    assert caught.value.category is category
    assert caught.value.retryable is False
    assert caught.value.engine == "scrapling"
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    ("case", "native", "expected_category"),
    [
        ("success", NativeResponse(), None),
        (
            "rate-limit",
            NativeResponse(
                content=b"busy",
                status_code=429,
                headers={"Content-Type": "text/plain", "Retry-After": "2"},
            ),
            TransportFailureCategory.RATE_LIMIT,
        ),
        (
            "permission",
            NativeResponse(content=b"denied", status_code=403),
            TransportFailureCategory.PERMISSION,
        ),
        (
            "challenge",
            NativeResponse(
                content=b"<html><title>Verify you are human</title><div>CAPTCHA</div></html>",
                headers={"Content-Type": "text/html"},
            ),
            TransportFailureCategory.CHALLENGE,
        ),
        (
            "malformed",
            NativeResponse(content=object()),
            TransportFailureCategory.INVALID_RESPONSE,
        ),
        (
            "date-mismatch",
            NativeResponse(content=b'{"date":"2026-09-17","value":1}'),
            TransportFailureCategory.CONTRACT,
        ),
    ],
)
def test_requests_and_scrapling_share_the_same_offline_contract(
    case: str,
    native: NativeResponse,
    expected_category: TransportFailureCategory | None,
) -> None:
    requests_session = RecordingSession([native])
    scrapling_fetcher = RecordingFetcher([native])
    requests_gateway = gateway_for(RequestsTransportEngine(session=requests_session))
    scrapling_gateway = gateway_for(
        RequestsTransportEngine(session=RecordingSession([NativeResponse()])),
        ScraplingStaticHttpEngine(allowlisted_config(), fetcher=scrapling_fetcher),
    )
    validator = None
    if case == "date-mismatch":
        validator = lambda response: response.json().get("date") == "2026-09-18"

    requests_request = TransportRequest(
        "GET",
        URL,
        params={"symbol": "000001"},
        headers={"Accept": "application/json"},
        timeout=3.0,
        requested_date="2026-09-18",
        source_id=SOURCE_ID,
    )
    enhanced_request = scrapling_request()

    if expected_category is None:
        default_response = requests_gateway.request(
            requests_request,
            validator=validator,
        )
        enhanced_response = scrapling_gateway.request(
            enhanced_request,
            validator=validator,
        )
        assert isinstance(default_response, TransportResponse)
        assert isinstance(enhanced_response, TransportResponse)
        assert default_response.status_code == enhanced_response.status_code
        assert default_response.headers == enhanced_response.headers
        assert default_response.content == enhanced_response.content
        assert default_response.final_url == enhanced_response.final_url
        assert {default_response.engine, enhanced_response.engine} == {
            "requests",
            "scrapling",
        }
    else:
        failures: list[TransportFailure] = []
        for gateway, request in (
            (requests_gateway, requests_request),
            (scrapling_gateway, enhanced_request),
        ):
            with pytest.raises(TransportFailure) as caught:
                gateway.request(request, validator=validator)
            failures.append(caught.value)

        default_failure, enhanced_failure = failures
        assert default_failure.category is expected_category
        assert enhanced_failure.category is expected_category
        assert default_failure.status_code == enhanced_failure.status_code
        assert default_failure.retryable == enhanced_failure.retryable
        assert {default_failure.engine, enhanced_failure.engine} == {
            "requests",
            "scrapling",
        }

    assert len(requests_session.calls) == 1
    assert len(scrapling_fetcher.calls) == 1


def test_source_id_is_part_of_cache_and_single_flight_identity() -> None:
    gateway = gateway_for(
        RequestsTransportEngine(session=RecordingSession([NativeResponse()])),
    )
    first = TransportRequest("GET", URL, source_id="source-a")
    second = TransportRequest("GET", URL, source_id="source-b")

    assert gateway.request_identity(first) != gateway.request_identity(second)


@pytest.mark.parametrize(
    "allowlist",
    [
        frozenset({("*", SOURCE_ID)}),
        frozenset({("quotes.example.test", "*")}),
        frozenset({("", SOURCE_ID)}),
        frozenset({("quotes.example.test", "")}),
    ],
)
def test_scrapling_allowlist_rejects_wildcards_and_empty_values(
    allowlist: frozenset[tuple[str, str]],
) -> None:
    with pytest.raises(ValueError):
        ScraplingStaticEngineConfig(enabled=True, allowlist=allowlist)
