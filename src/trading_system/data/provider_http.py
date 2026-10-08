"""Compatibility facade over the engine-neutral provider transport gateway."""

from __future__ import annotations

import inspect
import random
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .provider_transport import (
    HostPolicy,
    RequestEngine,
    RequestEngineRegistry,
    RequestsTransportEngine,
    TransportEngine,
    TransportEngineRegistry,
    TransportFailure,
    TransportFailureCategory,
    TransportPolicyGateway,
    TransportRequest,
    TransportResponse,
    build_default_transport_gateway,
    configure_process_transport_gateway,
    get_process_transport_gateway,
    normalized_host,
    redacted_endpoint,
    reset_process_transport_gateway_for_testing,
)
from .provider_scrapling import ScraplingStaticEngineConfig, ScraplingStaticHttpEngine


MODERN_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)


def build_requests_compatibility_session() -> requests.Session:
    """Create native sessions only inside the registered transport boundary."""

    return requests.Session()


class ProviderHttpError(RuntimeError):
    """Legacy classified failure used by existing provider fallbacks."""

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


class _ProviderSessionRouter:
    """Route one requests-engine attempt to the facade's host session."""

    def __init__(self, client: "ProviderHttpClient") -> None:
        self._client = client

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._client._request_native_once(method, url, **kwargs)


class ProviderHttpClient:
    """Backward-compatible GET facade backed by one transport policy gateway.

    Existing providers continue to consume ``status_code``, ``headers``,
    ``content``, ``text``, ``json`` and ``raise_for_status``. New source
    adapters can use :meth:`get_transport` or inject a process-shared gateway.
    """

    def __init__(
        self,
        *,
        session: requests.Session | Any | None = None,
        session_factory: Callable[[str], requests.Session | Any] | None = None,
        policies: Mapping[str, HostPolicy] | None = None,
        default_policy: HostPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        ua_selector: Callable[[tuple[str, ...]], str] | None = None,
        request_date: Callable[[], str] | None = None,
        gateway: TransportPolicyGateway | None = None,
    ) -> None:
        self._provided_session = session
        self.session_factory = session_factory or (lambda _host: requests.Session())
        self._clock = clock
        self._ua_selector = ua_selector or (
            (lambda pool: pool[0])
            if gateway is not None
            else (lambda pool: random.choice(pool))
        )
        self._request_date = request_date or (
            lambda: datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        )
        self._sessions: dict[str, requests.Session | Any] = {}
        self._host_uas: dict[str, str] = {}
        self._host_headers: dict[str, dict[str, str]] = {}
        self._session_lock = threading.RLock()

        if gateway is None:
            engine = RequestsTransportEngine(
                session=_ProviderSessionRouter(self),
                clock=clock,
            )
            registry = TransportEngineRegistry((engine,))
            gateway = TransportPolicyGateway(
                registry,
                policies=policies,
                default_policy=default_policy,
                clock=clock,
                sleeper=sleeper,
                random_uniform=random_uniform,
            )
        else:
            if policies is not None or default_policy is not None:
                raise ValueError("host policies belong to the injected transport gateway")
        self.gateway = gateway

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | tuple[float, float] | None = None,
        cache_ttl: float | None = None,
        requested_date: str | None = None,
        source_id: str | None = None,
        validator: Callable[[TransportResponse], bool] | None = None,
        gate: Callable[[Callable[[], TransportResponse]], TransportResponse] | None = None,
        engine: str = "requests",
        authentication_scope: str | bytes | None = None,
        tenant_scope: str | bytes | None = None,
        max_response_bytes: int | None = None,
    ) -> TransportResponse:
        host = normalized_host(url)
        request = TransportRequest(
            "GET",
            url,
            params=params,
            headers=self._headers_for(host),
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            requested_date=requested_date or self._request_date(),
            source_id=source_id,
            engine=engine,
            authentication_scope=authentication_scope,
            tenant_scope=tenant_scope,
        )
        try:
            return self.gateway.request(
                request,
                cache_ttl=cache_ttl,
                validator=validator,
                gate=gate,
            )
        except TransportFailure as exc:
            raise ProviderHttpError(
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                kind=self._legacy_failure_kind(exc),
            ) from exc

    def get_transport(self, url: str, **kwargs: Any) -> TransportResponse:
        return self.get(url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        return self.get(url, **kwargs).content

    def reset_host(self, host: str) -> None:
        normalized = normalized_host(host)
        with self._session_lock:
            self._sessions.pop(normalized, None)
            self._host_uas.pop(normalized, None)
            self._host_headers.pop(normalized, None)
        self.gateway.reset_host(normalized)

    def host_diagnostics(self, host: str) -> dict[str, Any]:
        normalized = normalized_host(host)
        diagnostics = self.gateway.host_diagnostics(normalized)
        diagnostics["userAgent"] = self._host_uas.get(normalized)
        return diagnostics

    def _policy(self, host: str) -> HostPolicy:
        """Compatibility accessor; policy state remains owned by the gateway."""

        return self.gateway.policy_for(host)

    def _headers_for(self, host: str) -> dict[str, str]:
        with self._session_lock:
            headers = self._host_headers.get(host)
            if headers is None:
                user_agent = self._ua_selector(MODERN_USER_AGENTS)
                self._host_uas[host] = user_agent
                headers = {
                    "User-Agent": user_agent,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                }
                self._host_headers[host] = headers
            return dict(headers)

    def _session_for(self, host: str) -> requests.Session | Any:
        with self._session_lock:
            session = self._sessions.get(host)
            if session is not None:
                return session
            if self._provided_session is not None:
                session = self._provided_session
            else:
                try:
                    session = self.session_factory(host)
                except TypeError:
                    session = self.session_factory()  # type: ignore[call-arg]
            self._sessions[host] = session
            if self._provided_session is None:
                session.headers.update(self._headers_for(host))
            return session

    def _request_native_once(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | tuple[float, float] | None = None,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        stream: bool = False,
    ) -> Any:
        if method.upper() != "GET" or data is not None:
            raise TransportFailure(
                "legacy provider HTTP facade supports GET requests only",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine="requests",
                final_url=url,
            )
        host = normalized_host(url)
        session = self._session_for(host)
        request_kwargs: dict[str, Any] = {
            "params": dict(params or {}),
            "timeout": timeout,
        }
        get = session.get
        if stream and self._accepts_keyword(get, "stream"):
            request_kwargs["stream"] = True
        if self._provided_session is None:
            return get(url, **request_kwargs)
        request_headers = dict(headers or self._headers_for(host))
        if self._accepts_keyword(get, "headers"):
            return get(
                url,
                headers=request_headers,
                **request_kwargs,
            )
        # Tiny deterministic test doubles may not implement Session's
        # per-call headers argument. Adapt before invocation so one gateway
        # attempt can never become two upstream calls after a TypeError.
        with self._session_lock:
            original_headers = dict(session.headers)
            session.headers.update(request_headers)
            try:
                return get(url, **request_kwargs)
            finally:
                session.headers.clear()
                session.headers.update(original_headers)

    @staticmethod
    def _accepts_keyword(operation: Callable[..., Any], name: str) -> bool:
        try:
            parameters = inspect.signature(operation).parameters
        except (TypeError, ValueError):
            return True
        return name in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    @staticmethod
    def _legacy_failure_kind(failure: TransportFailure) -> str:
        category = failure.category
        if category in {TransportFailureCategory.NETWORK, TransportFailureCategory.TIMEOUT}:
            return "network"
        if category is TransportFailureCategory.PERMISSION:
            return "permission"
        if category is TransportFailureCategory.CHALLENGE:
            return "challenge"
        if category is TransportFailureCategory.HTTP_STATUS:
            return "http-retryable" if failure.retryable else "http-client-error"
        if category is TransportFailureCategory.RATE_LIMIT:
            return "http-retryable"
        if category in {
            TransportFailureCategory.CONTRACT,
            TransportFailureCategory.INVALID_RESPONSE,
            TransportFailureCategory.RESPONSE_TOO_LARGE,
        }:
            return "contract"
        if category is TransportFailureCategory.REQUEST_BUDGET_EXHAUSTED:
            return "request_budget_exhausted"
        if category is TransportFailureCategory.CIRCUIT_OPEN:
            return "circuit_open"
        if category is TransportFailureCategory.RETRY_AFTER_EXCEEDED:
            return "retry_after_exceeded"
        return category.value

    @staticmethod
    def _host(url: str) -> str:
        return normalized_host(url)


__all__ = [
    "HostPolicy",
    "MODERN_USER_AGENTS",
    "ProviderHttpClient",
    "ProviderHttpError",
    "RequestEngine",
    "RequestEngineRegistry",
    "RequestsTransportEngine",
    "ScraplingStaticEngineConfig",
    "ScraplingStaticHttpEngine",
    "TransportEngine",
    "TransportEngineRegistry",
    "TransportFailure",
    "TransportFailureCategory",
    "TransportPolicyGateway",
    "TransportRequest",
    "TransportResponse",
    "build_default_transport_gateway",
    "build_requests_compatibility_session",
    "configure_process_transport_gateway",
    "get_process_transport_gateway",
    "redacted_endpoint",
    "reset_process_transport_gateway_for_testing",
]
