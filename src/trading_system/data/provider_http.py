"""Shared, bounded HTTP transport for external market-data providers."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests


MODERN_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)


@dataclass(frozen=True)
class HostPolicy:
    """Transport controls applied independently to one upstream host."""

    minimum_interval: float = 0.2
    jitter: tuple[float, float] = (0.02, 0.10)
    timeout: float | tuple[float, float] = 8.0
    max_retries: int = 2
    retry_backoff: float = 0.5
    request_budget: int = 120
    budget_window_seconds: float = 60.0
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    max_retry_after_seconds: float = 300.0
    cache_ttl_seconds: float = 10.0


class ProviderHttpError(RuntimeError):
    """Classified transport failure that is safe to pass to provider fallbacks."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        kind: str = "transport",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.kind = kind


@dataclass
class _HostState:
    next_allowed_at: float = 0.0
    failures: int = 0
    open_until: float = 0.0
    probe_in_flight: bool = False
    requests_used: int = 0
    budget_started_at: float | None = None
    last_request_seconds: float | None = None
    last_retry_count: int = 0


@dataclass
class _Inflight:
    event: threading.Event
    response: requests.Response | None = None
    error: BaseException | None = None


class ProviderHttpClient:
    """Small synchronous transport with per-host pacing and recovery state.

    The client deliberately leaves response parsing to providers.  A caller can
    pass ``validator`` when a response must be structurally checked before it is
    admitted to the short-lived request cache.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        session_factory: Callable[[str], requests.Session] | None = None,
        policies: Mapping[str, HostPolicy] | None = None,
        default_policy: HostPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        ua_selector: Callable[[tuple[str, ...]], str] | None = None,
        request_date: Callable[[], str] | None = None,
    ) -> None:
        self._provided_session = session
        self.session_factory = session_factory or (lambda _host: requests.Session())
        self._policies = dict(policies or {})
        self._default_policy = default_policy or HostPolicy()
        self._clock = clock
        self._sleep = sleeper
        self._random_uniform = random_uniform
        self._ua_selector = ua_selector or (lambda pool: random.choice(pool))
        self._request_date = request_date or (
            lambda: datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        )
        self._sessions: dict[str, requests.Session] = {}
        self._host_uas: dict[str, str] = {}
        self._host_headers: dict[str, dict[str, str]] = {}
        self._states: dict[str, _HostState] = {}
        self._cache: dict[str, tuple[float, requests.Response]] = {}
        self._inflight: dict[str, _Inflight] = {}
        self._lock = threading.RLock()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | tuple[float, float] | None = None,
        cache_ttl: float | None = None,
        requested_date: str | None = None,
        validator: Callable[[requests.Response], bool] | None = None,
        gate: Callable[[Callable[[], requests.Response]], requests.Response] | None = None,
    ) -> requests.Response:
        host = self._host(url)
        policy = self._policy(host)
        cache_seconds = policy.cache_ttl_seconds if cache_ttl is None else max(0.0, cache_ttl)
        key = self._cache_key(url, params, requested_date or self._request_date())
        # A gated call has different pacing semantics from a direct call;
        # keep those in-flight and cached entries independent.
        key = f"{key}|{'gated' if gate is not None else 'direct'}"
        with self._lock:
            if cache_seconds > 0:
                cached = self._cache.get(key)
                if cached is not None and cached[0] > self._clock():
                    self._validate_cached(cached[1], validator, host)
                    return cached[1]
                if cached is not None:
                    self._cache.pop(key, None)
            current = self._inflight.get(key)
            if current is None:
                current = _Inflight(event=threading.Event())
                self._inflight[key] = current
                owner = True
            else:
                owner = False
        if not owner:
            current.event.wait()
            if current.error is not None:
                raise current.error
            if current.response is None:
                raise ProviderHttpError("provider request completed without a response", kind="internal")
            self._validate_cached(current.response, validator, host)
            return current.response

        try:
            response = self._request(
                host,
                url,
                params=params,
                timeout=timeout if timeout is not None else policy.timeout,
                policy=policy,
                validator=validator,
                gate=gate,
            )
            if cache_seconds > 0:
                with self._lock:
                    self._cache[key] = (self._clock() + cache_seconds, response)
            current.response = response
            return response
        except BaseException as exc:
            current.error = exc
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                current.event.set()

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """Fetch and decode a JSON response through the shared policy."""
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        """Fetch a text response through the shared policy."""
        return self.get(url, **kwargs).text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        """Fetch a binary response through the shared policy."""
        return bytes(self.get(url, **kwargs).content)

    def reset_host(self, host: str) -> None:
        """Drop a host session and its cooldown so an operator can recover it."""

        normalized = self._host(host)
        with self._lock:
            self._sessions.pop(normalized, None)
            self._host_uas.pop(normalized, None)
            self._host_headers.pop(normalized, None)
            self._states.pop(normalized, None)

    def host_diagnostics(self, host: str) -> dict[str, Any]:
        normalized = self._host(host)
        with self._lock:
            state = self._states.get(normalized, _HostState())
            now = self._clock()
            return {
                "host": normalized,
                "userAgent": self._host_uas.get(normalized),
                "requestsUsed": state.requests_used,
                "budgetWindowSeconds": self._policy(normalized).budget_window_seconds,
                "failures": state.failures,
                "cooldownRemaining": max(0.0, state.open_until - now),
                "lastRequestSeconds": state.last_request_seconds,
                "lastRetryCount": state.last_retry_count,
            }

    def _request(
        self,
        host: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        timeout: float | tuple[float, float],
        policy: HostPolicy,
        validator: Callable[[requests.Response], bool] | None,
        gate: Callable[[Callable[[], requests.Response]], requests.Response] | None,
    ) -> requests.Response:
        started_at = self._clock()
        probe_state = [False]
        retry_count = [0]
        try:
            return self._request_attempts(
                host,
                url,
                params=params,
                timeout=timeout,
                policy=policy,
                validator=validator,
                gate=gate,
                probe_state=probe_state,
                retry_count=retry_count,
            )
        finally:
            if probe_state[0]:
                self._clear_probe(host)
            self._record_timing(host, started_at, retry_count[0])

    def _request_attempts(
        self,
        host: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        timeout: float | tuple[float, float],
        policy: HostPolicy,
        validator: Callable[[requests.Response], bool] | None,
        gate: Callable[[Callable[[], requests.Response]], requests.Response] | None,
        probe_state: list[bool],
        retry_count: list[int],
    ) -> requests.Response:
        last_error: ProviderHttpError | None = None
        for attempt in range(policy.max_retries + 1):
            probe_state[0] = self._wait_for_slot(
                host,
                policy,
                use_internal_gate=gate is None,
                probe_owner=probe_state[0],
            )
            session = self._session_for(host)
            operation = lambda: self._get_with_host_headers(
                session,
                host,
                url,
                params=dict(params or {}),
                timeout=timeout,
            )
            try:
                with self._lock:
                    state = self._states.setdefault(host, _HostState())
                    now = self._clock()
                    if (
                        state.budget_started_at is None
                        or now - state.budget_started_at >= policy.budget_window_seconds
                    ):
                        state.budget_started_at = now
                        state.requests_used = 0
                    state.requests_used += 1
                    if state.requests_used > policy.request_budget:
                        raise ProviderHttpError(
                            f"provider request budget exceeded for {host}",
                            retryable=False,
                            kind="request_budget_exhausted",
                        )
                response = gate(operation) if gate is not None else operation()
            except ProviderHttpError:
                raise
            except requests.RequestException as exc:
                last_error = ProviderHttpError(
                    f"provider network request failed for {host}",
                    retryable=True,
                    kind="network",
                )
                if attempt < policy.max_retries:
                    retry_count[0] += 1
                    try:
                        self._backoff(policy, attempt)
                    except ProviderHttpError:
                        self._record_failure(host, policy)
                        raise
                    continue
                self._record_failure(host, policy)
                raise last_error from exc

            status = int(getattr(response, "status_code", 200) or 200)
            if status in {408, 429} or status >= 500:
                last_error = ProviderHttpError(
                    f"provider HTTP status {status} from {host}",
                    status_code=status,
                    retryable=True,
                    kind="http-retryable",
                )
                if attempt < policy.max_retries:
                    retry_count[0] += 1
                    try:
                        self._backoff(policy, attempt, response=response)
                    except ProviderHttpError:
                        self._record_failure(host, policy)
                        raise
                    continue
                self._record_failure(host, policy)
                raise last_error
            if status == 401 or status == 403:
                self._record_non_retryable_failure(host)
                raise ProviderHttpError(
                    f"provider HTTP status {status} from {host}",
                    status_code=status,
                    retryable=False,
                    kind="permission",
                )
            if status >= 400:
                self._record_non_retryable_failure(host)
                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise ProviderHttpError(
                        f"provider HTTP status {status} from {host}",
                        status_code=status,
                        retryable=False,
                        kind="http-client-error",
                    ) from exc
                raise ProviderHttpError(
                    f"provider HTTP status {status} from {host}",
                    status_code=status,
                    retryable=False,
                    kind="http-client-error",
                )
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                self._record_failure(host, policy)
                raise ProviderHttpError(
                    f"provider response status validation failed for {host}",
                    status_code=status,
                    retryable=True,
                    kind="network",
                ) from exc
            if validator is not None:
                try:
                    valid = bool(validator(response))
                except Exception as exc:
                    valid = False
                    validation_error = exc
                else:
                    validation_error = None
                if not valid:
                    self._record_non_retryable_failure(host)
                    error = ProviderHttpError(
                        f"provider response contract rejected for {host}",
                        status_code=status,
                        retryable=False,
                        kind="contract",
                    )
                    if validation_error is not None:
                        raise error from validation_error
                    raise error
            self._record_success(host)
            return response
        if last_error is not None:
            raise last_error
        raise ProviderHttpError("provider request failed without a classified result", kind="internal")

    def _session_for(self, host: str) -> requests.Session:
        with self._lock:
            session = self._sessions.get(host)
            if session is None:
                if self._provided_session is not None:
                    session = self._provided_session
                else:
                    try:
                        session = self.session_factory(host)
                    except TypeError:
                        session = self.session_factory()  # type: ignore[call-arg]
                self._sessions[host] = session
                self._host_uas[host] = self._ua_selector(MODERN_USER_AGENTS)
                self._host_headers[host] = {
                    "User-Agent": self._host_uas[host],
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                }
                if self._provided_session is None:
                    session.headers.update(self._host_headers[host])
            return session

    @staticmethod
    def _validate_cached(
        response: requests.Response,
        validator: Callable[[requests.Response], bool] | None,
        host: str,
    ) -> None:
        if validator is None:
            return
        try:
            valid = bool(validator(response))
        except Exception as exc:
            raise ProviderHttpError(
                f"provider cached response contract rejected for {host}",
                status_code=getattr(response, "status_code", None),
                retryable=False,
                kind="contract",
            ) from exc
        if not valid:
            raise ProviderHttpError(
                f"provider cached response contract rejected for {host}",
                status_code=getattr(response, "status_code", None),
                retryable=False,
                kind="contract",
            )

    def _get_with_host_headers(
        self,
        session: requests.Session,
        host: str,
        url: str,
        *,
        params: Mapping[str, Any],
        timeout: float | tuple[float, float],
    ) -> requests.Response:
        if self._provided_session is None:
            return session.get(url, params=params, timeout=timeout)
        headers = self._host_headers[host]
        try:
            return session.get(url, params=params, timeout=timeout, headers=headers)
        except TypeError:
            # Keep compatibility with small test doubles that do not expose
            # requests.Session's per-call headers argument.
            with self._lock:
                original_headers = dict(session.headers)
                session.headers.update(headers)
                try:
                    return session.get(url, params=params, timeout=timeout)
                finally:
                    session.headers.clear()
                    session.headers.update(original_headers)

    def _wait_for_slot(
        self,
        host: str,
        policy: HostPolicy,
        *,
        use_internal_gate: bool = True,
        probe_owner: bool = False,
    ) -> bool:
        now = self._clock()
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            if not probe_owner and state.open_until > now:
                raise ProviderHttpError(
                    f"provider host {host} is cooling down",
                    retryable=True,
                    kind="circuit_open",
                )
            if state.open_until and not probe_owner:
                if state.probe_in_flight:
                    raise ProviderHttpError(
                        f"provider host {host} is being probed",
                        retryable=True,
                        kind="circuit_open",
                    )
                state.probe_in_flight = True
                self._sessions.pop(host, None)
                self._host_uas.pop(host, None)
                self._host_headers.pop(host, None)
            required = max(0.0, policy.minimum_interval) if use_internal_gate else 0.0
            if required:
                required += max(0.0, self._random_uniform(*policy.jitter))
            delay = max(0.0, state.next_allowed_at - now)
            state.next_allowed_at = max(now, state.next_allowed_at) + required
        if delay > 0:
            self._sleep(delay)
        return probe_owner or bool(state.open_until)

    def _clear_probe(self, host: str) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.probe_in_flight = False

    def _record_timing(self, host: str, started_at: float, retry_count: int) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.last_request_seconds = max(0.0, self._clock() - started_at)
            state.last_retry_count = retry_count

    def _record_success(self, host: str) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.failures = 0
            state.open_until = 0.0
            state.probe_in_flight = False

    def _record_failure(self, host: str, policy: HostPolicy) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.failures += 1
            state.probe_in_flight = False
            if state.failures >= max(1, policy.failure_threshold):
                state.open_until = self._clock() + max(0.0, policy.cooldown_seconds)

    def _record_non_retryable_failure(self, host: str) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.probe_in_flight = False

    def _backoff(
        self,
        policy: HostPolicy,
        attempt: int,
        *,
        response: requests.Response | None = None,
    ) -> None:
        retry_after = self._retry_after(response)
        if retry_after is not None:
            if retry_after > policy.max_retry_after_seconds:
                raise ProviderHttpError(
                    "provider Retry-After exceeds the bounded retry wait",
                    retryable=True,
                    kind="retry_after_exceeded",
                )
            self._sleep(retry_after)
            return
        base = max(0.0, policy.retry_backoff) * (2**attempt)
        self._sleep(base + self._random_uniform(0.0, max(0.0, policy.jitter[1])))

    @staticmethod
    def _retry_after(response: requests.Response | None) -> float | None:
        if response is None:
            return None
        headers = getattr(response, "headers", {}) or {}
        raw = headers.get("Retry-After") if hasattr(headers, "get") else None
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(str(raw))
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

    def _policy(self, host: str) -> HostPolicy:
        return self._policies.get(host, self._default_policy)

    @staticmethod
    def _host(url: str) -> str:
        return (urlsplit(url).netloc or url).lower()

    @staticmethod
    def _cache_key(url: str, params: Mapping[str, Any] | None, requested_date: str | None) -> str:
        parts = urlsplit(url)
        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        normalized_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))
        encoded = urlencode(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        return "|".join((normalized_url, encoded, str(requested_date or "")))


__all__ = ["HostPolicy", "MODERN_USER_AGENTS", "ProviderHttpClient", "ProviderHttpError"]
