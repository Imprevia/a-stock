from __future__ import annotations

from collections import deque

import pytest
import requests

from src.trading_system.data.provider_http import (
    ProviderHttpClient,
    ProviderHttpError,
    RequestEngine,
    RequestsTransportEngine,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)


class NativeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        url: str = "https://redirected.example.test/final",
    ) -> None:
        self.content = body
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


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

    def get(self, url: str, **kwargs: object) -> NativeResponse:
        return self.request("GET", url, **kwargs)


def test_transport_contract_exposes_json_text_binary_and_response_metadata() -> None:
    native = NativeResponse(
        b'{"value":"ok"}',
        status_code=202,
        headers={"Content-Type": "application/json; charset=utf-8", "X-Trace": "trace-1"},
    )
    session = RecordingSession([native])
    engine = RequestsTransportEngine(session=session, clock=iter((10.0, 10.25)).__next__)

    response = engine.send(
        TransportRequest(
            "GET",
            "https://provider.example.test/data",
            params={"symbol": "000001"},
            headers={"Accept": "application/json"},
            timeout=(1.0, 2.0),
            max_response_bytes=1024,
        )
    )

    assert isinstance(engine, RequestEngine)
    assert isinstance(response, TransportResponse)
    assert response.status_code == 202
    assert response.headers["X-Trace"] == "trace-1"
    assert response.body == response.content == b'{"value":"ok"}'
    assert response.text == '{"value":"ok"}'
    assert response.json() == {"value": "ok"}
    assert response.final_url == response.url == "https://redirected.example.test/final"
    assert response.elapsed_seconds == pytest.approx(0.25)
    assert response.engine == "requests"
    assert session.calls == [
        {
            "method": "GET",
            "url": "https://provider.example.test/data",
            "params": {"symbol": "000001"},
            "timeout": (1.0, 2.0),
            "headers": {"Accept": "application/json"},
            "stream": True,
        }
    ]


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (requests.Timeout("slow"), "timeout"),
        (requests.ConnectionError("offline"), "network"),
    ],
)
def test_requests_engine_maps_network_failures_without_retry(
    exception: requests.RequestException,
    category: str,
) -> None:
    session = RecordingSession([exception, NativeResponse(b"should not be used")])
    engine = RequestsTransportEngine(session=session)

    with pytest.raises(TransportFailure) as caught:
        engine.send(TransportRequest("GET", "https://provider.example.test/data", timeout=3.0))

    assert caught.value.category == category
    assert caught.value.retryable is True
    assert caught.value.engine == "requests"
    assert caught.value.status_code is None
    assert caught.value.final_url == "https://provider.example.test/data"
    assert len(session.calls) == 1


def test_requests_engine_returns_http_status_without_internal_retry() -> None:
    session = RecordingSession(
        [
            NativeResponse(b"busy", status_code=503, headers={"Retry-After": "2"}),
            NativeResponse(b"should not be used"),
        ]
    )
    engine = RequestsTransportEngine(session=session)

    response = engine.send(TransportRequest("GET", "https://provider.example.test/data"))

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"
    assert response.body == b"busy"
    assert len(session.calls) == 1


def test_requests_engine_rejects_binary_content_over_the_configured_bound() -> None:
    session = RecordingSession([NativeResponse(b"12345", status_code=200)])
    engine = RequestsTransportEngine(session=session)

    with pytest.raises(TransportFailure) as caught:
        engine.send(
            TransportRequest(
                "GET",
                "https://provider.example.test/package.zip",
                max_response_bytes=4,
            )
        )

    assert caught.value.category == "response-too-large"
    assert caught.value.retryable is False
    assert caught.value.status_code == 200
    assert len(session.calls) == 1


def test_requests_engine_stops_a_stream_after_crossing_the_binary_bound() -> None:
    class StreamingResponse(NativeResponse):
        def __init__(self) -> None:
            super().__init__(b"", status_code=200)
            self.closed = False
            self.chunks_read = 0

        def iter_content(self, *, chunk_size: int):
            assert chunk_size == 5
            for chunk in (b"123", b"45", b"must-not-be-read"):
                self.chunks_read += 1
                yield chunk

        def close(self) -> None:
            self.closed = True

    native = StreamingResponse()
    session = RecordingSession([native])
    engine = RequestsTransportEngine(session=session)

    with pytest.raises(TransportFailure) as caught:
        engine.send(
            TransportRequest(
                "GET",
                "https://provider.example.test/package.zip",
                max_response_bytes=4,
            )
        )

    assert caught.value.category == "response-too-large"
    assert native.chunks_read == 2
    assert native.closed is True
    assert len(session.calls) == 1


def test_provider_validator_receives_only_engine_neutral_response() -> None:
    native = NativeResponse(b'{"ok":true}')
    session = RecordingSession([native])
    observed: list[TransportResponse] = []
    client = ProviderHttpClient(
        session=session,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
    )

    returned = client.get(
        "https://provider.example.test/data",
        cache_ttl=0.0,
        validator=lambda response: observed.append(response) or response.json() == {"ok": True},
    )

    assert isinstance(returned, TransportResponse)
    assert returned.json() == {"ok": True}
    assert len(observed) == 1
    assert observed[0] is returned
    assert not hasattr(observed[0], "native_response")


def test_compatibility_facade_never_retries_a_session_type_error() -> None:
    class FailingSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.calls = 0

        def get(self, url: str, **kwargs: object) -> NativeResponse:
            self.calls += 1
            raise TypeError("failure after the upstream attempt started")

    session = FailingSession()
    client = ProviderHttpClient(
        session=session,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
    )

    with pytest.raises(ProviderHttpError) as caught:
        client.get(
            "https://provider.example.test/data",
            cache_ttl=0.0,
            max_response_bytes=1024,
        )

    assert session.calls == 1
    assert caught.value.kind == "internal"


def test_compatibility_facade_adapts_minimal_session_before_one_call() -> None:
    class MinimalSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.calls = 0

        def get(
            self,
            url: str,
            *,
            params: dict[str, object],
            timeout: float | tuple[float, float],
        ) -> NativeResponse:
            self.calls += 1
            assert self.headers["Accept"].startswith("application/json")
            return NativeResponse(b"bounded")

    session = MinimalSession()
    client = ProviderHttpClient(
        session=session,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
    )

    response = client.get(
        "https://provider.example.test/data",
        cache_ttl=0.0,
        max_response_bytes=1024,
    )

    assert response.content == b"bounded"
    assert session.calls == 1


def test_legacy_client_can_return_an_engine_neutral_response_explicitly() -> None:
    native = NativeResponse(b"plain text", headers={"Content-Type": "text/plain"})
    session = RecordingSession([native])
    client = ProviderHttpClient(
        session=session,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
    )

    response = client.get_transport("https://provider.example.test/data", cache_ttl=0.0)

    assert isinstance(response, TransportResponse)
    assert response.text == "plain text"
    assert response.final_url == native.url
