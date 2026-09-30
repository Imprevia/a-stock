from __future__ import annotations

from collections import deque
from datetime import date
from threading import Event, Thread

import pytest

from src.trading_system.data.provider_http import (
    HostPolicy,
    ProviderHttpClient,
    ProviderHttpError,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeResponse:
    def __init__(self, status_code: int = 200, *, headers=None, payload=None) -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._payload = payload
        self.content = b"payload"
        self.text = "payload"

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses=()) -> None:
        self.responses = deque(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, *, params=None, timeout=None, headers=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
                "headers": dict(headers or self.headers),
            }
        )
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response


def policy(**overrides) -> HostPolicy:
    values = {
        "minimum_interval": 0.0,
        "jitter": (0.0, 0.0),
        "timeout": (1.0, 2.0),
        "max_retries": 0,
        "retry_backoff": 0.0,
        "request_budget": 100,
        "failure_threshold": 3,
        "cooldown_seconds": 30.0,
    }
    values.update(overrides)
    return HostPolicy(**values)


def client_for(session, *, clock=None, sleeper=None, host_policy=None, **kwargs):
    clock = clock or FakeClock()
    sleeps = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if hasattr(clock, "advance"):
            clock.advance(seconds)

    client = ProviderHttpClient(
        session_factory=lambda _host: session,
        default_policy=host_policy or policy(),
        clock=clock,
        sleeper=sleeper or record_sleep,
        random_uniform=lambda _low, _high: 0.0,
        ua_selector=lambda values: values[0],
        **kwargs,
    )
    return client, clock, sleeps


def test_user_agent_is_stable_per_host_and_selected_per_host_session():
    sessions = []
    selected = []

    def make_session(_host):
        session = FakeSession([FakeResponse(), FakeResponse()])
        sessions.append(session)
        return session

    clock = FakeClock()
    client = ProviderHttpClient(
        session_factory=make_session,
        default_policy=policy(),
        clock=clock,
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
        ua_selector=lambda _values: selected.append(f"UA-{len(selected) + 1}") or selected[-1],
    )

    client.get("https://quotes.example.test/one")
    client.get("https://quotes.example.test/two")
    client.get("https://other.example.test/one")

    assert len(sessions) == 2
    assert sessions[0].calls[0]["headers"]["User-Agent"] == sessions[0].calls[1]["headers"]["User-Agent"]
    assert sessions[0].calls[0]["headers"]["User-Agent"].startswith("UA-")
    assert sessions[1].calls[0]["headers"]["User-Agent"] != sessions[0].calls[0]["headers"]["User-Agent"]
    assert "application/json" in sessions[0].calls[0]["headers"]["Accept"]


def test_shared_session_applies_the_selected_ua_for_each_host():
    session = FakeSession([FakeResponse(), FakeResponse(), FakeResponse()])
    selected = []
    client = ProviderHttpClient(
        session=session,
        default_policy=policy(),
        sleeper=lambda _seconds: None,
        random_uniform=lambda _low, _high: 0.0,
        ua_selector=lambda _values: selected.append(f"UA-{len(selected) + 1}") or selected[-1],
    )

    client.get("https://quotes.example.test/one", cache_ttl=0.0)
    client.get("https://other.example.test/one", cache_ttl=0.0)
    client.get("https://quotes.example.test/two", cache_ttl=0.0)

    assert [call["headers"]["User-Agent"] for call in session.calls] == ["UA-1", "UA-2", "UA-1"]


def test_retryable_statuses_retry_and_retry_after_is_respected():
    session = FakeSession(
        [
            FakeResponse(503),
            FakeResponse(429, headers={"Retry-After": "2"}),
            FakeResponse(200, payload={"ok": True}),
        ]
    )
    client, _, sleeps = client_for(
        session,
        host_policy=policy(max_retries=2, retry_backoff=0.5),
    )

    response = client.get("https://quotes.example.test/data")

    assert response.status_code == 200
    assert len(session.calls) == 3
    assert sleeps[0] == pytest.approx(0.5)
    assert sleeps[1] >= 2.0


def test_forbidden_response_fails_fast_without_retry():
    session = FakeSession([FakeResponse(403), FakeResponse(200)])
    client, _, _ = client_for(session, host_policy=policy(max_retries=2))

    with pytest.raises(ProviderHttpError) as raised:
        client.get("https://quotes.example.test/data")

    assert raised.value.status_code == 403
    assert raised.value.retryable is False
    assert len(session.calls) == 1


def test_timeout_is_forwarded_and_http_error_preserves_retryability():
    session = FakeSession([FakeResponse(408)])
    client, _, _ = client_for(session, host_policy=policy(max_retries=0))

    with pytest.raises(ProviderHttpError) as raised:
        client.get("https://quotes.example.test/data", timeout=9.0)

    assert session.calls[0]["timeout"] == 9.0
    assert raised.value.status_code == 408
    assert raised.value.retryable is True


def test_ttl_cache_reuses_response_but_requested_date_is_part_of_cache_key():
    session = FakeSession(
        [
            FakeResponse(payload={"value": 1}),
            FakeResponse(payload={"value": 2}),
            FakeResponse(payload={"value": 3}),
        ]
    )
    clock = FakeClock()
    client, _, _ = client_for(session, clock=clock)

    first = client.get(
        "https://quotes.example.test/data",
        params={"symbol": "000001"},
        cache_ttl=10.0,
        requested_date=date(2026, 9, 18),
    )
    cached = client.get(
        "https://quotes.example.test/data",
        params={"symbol": "000001"},
        cache_ttl=10.0,
        requested_date=date(2026, 9, 18),
    )
    other_date = client.get(
        "https://quotes.example.test/data",
        params={"symbol": "000001"},
        cache_ttl=10.0,
        requested_date=date(2026, 9, 19),
    )

    assert cached is first
    assert other_date is not first
    assert len(session.calls) == 2

    clock.advance(11.0)
    refreshed = client.get(
        "https://quotes.example.test/data",
        params={"symbol": "000001"},
        cache_ttl=10.0,
        requested_date=date(2026, 9, 18),
    )
    assert refreshed is not first
    assert len(session.calls) == 3


def test_same_key_requests_are_single_flight():
    started = Event()
    release = Event()

    class BlockingSession(FakeSession):
        def get(self, *args, **kwargs):
            self.calls.append({"url": args[0], "params": kwargs.get("params")})
            started.set()
            assert release.wait(timeout=2.0)
            return FakeResponse(payload={"ok": True})

    session = BlockingSession()
    client, _, _ = client_for(session)
    results = []

    def run_request() -> None:
        results.append(client.get("https://quotes.example.test/data", cache_ttl=10.0))

    first = Thread(target=run_request)
    second = Thread(target=run_request)
    first.start()
    assert started.wait(timeout=2.0)
    second.start()
    release.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert len(session.calls) == 1
    assert len(results) == 2
    assert results[0] is results[1]


def test_circuit_breaker_opens_after_threshold_and_allows_probe_after_cooldown():
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(503), FakeResponse(200)])
    clock = FakeClock()
    client, _, _ = client_for(
        session,
        clock=clock,
        host_policy=policy(failure_threshold=3, cooldown_seconds=30.0),
    )

    for _ in range(3):
        with pytest.raises(ProviderHttpError):
            client.get("https://quotes.example.test/data")

    with pytest.raises(ProviderHttpError) as raised:
        client.get("https://quotes.example.test/data")
    assert "circuit" in raised.value.kind
    assert len(session.calls) == 3

    clock.advance(30.0)
    assert client.get("https://quotes.example.test/data").status_code == 200
    assert len(session.calls) == 4


def test_request_budget_rejects_calls_after_budget_is_exhausted():
    session = FakeSession([FakeResponse(), FakeResponse(), FakeResponse()])
    client, _, _ = client_for(session, host_policy=policy(request_budget=2))

    client.get("https://quotes.example.test/one")
    client.get("https://quotes.example.test/two")
    with pytest.raises(ProviderHttpError) as raised:
        client.get("https://quotes.example.test/three")

    assert "budget" in raised.value.kind
    assert raised.value.retryable is False
    assert len(session.calls) == 2


def test_request_budget_rolls_over_after_its_window():
    session = FakeSession([FakeResponse(), FakeResponse(), FakeResponse()])
    clock = FakeClock()
    client, _, _ = client_for(
        session,
        clock=clock,
        host_policy=policy(request_budget=1, budget_window_seconds=60.0),
    )

    client.get("https://quotes.example.test/one")
    with pytest.raises(ProviderHttpError):
        client.get("https://quotes.example.test/two")

    clock.advance(60.0)
    assert client.get("https://quotes.example.test/three").status_code == 200
