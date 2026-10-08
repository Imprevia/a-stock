"""Engine-neutral, policy-governed HTTP transport for market-data providers."""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


_SENSITIVE_NAME_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "proxy",
    "secret",
    "token",
    "api-key",
    "apikey",
    "api_key",
)

_CHALLENGE_MARKERS = (
    "captcha",
    "cf-chl-",
    "challenge-platform",
    "verify you are human",
    "security verification",
    "访问验证",
    "验证码",
)


def _is_sensitive_name(name: object) -> bool:
    normalized = str(name).strip().lower()
    return any(fragment in normalized for fragment in _SENSITIVE_NAME_FRAGMENTS)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = (_canonical_value(item) for item in value)
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, bytes):
        return {"bytesSha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    host = (parts.hostname or parts.netloc).lower()
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", query, ""))


def redacted_endpoint(url: str | None) -> str | None:
    """Return a diagnostic endpoint without userinfo, query values or fragments."""

    if not url:
        return None
    parts = urlsplit(str(url))
    host = (parts.hostname or "").lower()
    if not host:
        return "<redacted-endpoint>"
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    scheme = parts.scheme.lower() or "https"
    return urlunsplit((scheme, host, parts.path or "/", "", ""))


def normalized_host(url_or_host: str) -> str:
    parts = urlsplit(url_or_host if "://" in url_or_host else f"//{url_or_host}")
    host = (parts.hostname or url_or_host).lower()
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return host


def _redacted_response_evidence(
    response: "TransportResponse",
    request: "TransportRequest",
) -> dict[str, Any]:
    """Keep only bounded provider error fields needed for adapter diagnostics."""

    try:
        payload = response.json()
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, Mapping):
        return {}

    secrets: list[str] = []
    for name, value in request.headers.items():
        if _is_sensitive_name(name) and value:
            secrets.append(str(value))
    for name, value in request.params.items():
        if _is_sensitive_name(name) and value not in (None, ""):
            secrets.append(str(value))
    for name, value in parse_qsl(urlsplit(request.url).query, keep_blank_values=True):
        if _is_sensitive_name(name) and value:
            secrets.append(str(value))

    evidence: dict[str, Any] = {}
    limits = {"code": 40, "message": 160, "request_id": 80}
    for name, max_length in limits.items():
        value = payload.get(name)
        if value in (None, "") or isinstance(value, (Mapping, list, tuple, set)):
            continue
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        for secret in secrets:
            text = text.replace(secret, "<redacted>")
        if len(text) > max_length:
            text = f"{text[:max_length]}..."
        if text:
            evidence[name] = text
    return evidence


class TransportFailureCategory(str, Enum):
    """Stable failure classes emitted below the provider adapter boundary."""

    CONFIGURATION = "configuration"
    ENGINE_UNAVAILABLE = "engine-unavailable"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate-limit"
    PERMISSION = "permission"
    CHALLENGE = "challenge"
    HTTP_STATUS = "http-status"
    CONTRACT = "contract"
    RESPONSE_TOO_LARGE = "response-too-large"
    INVALID_RESPONSE = "invalid-response"
    REQUEST_BUDGET_EXHAUSTED = "request-budget-exhausted"
    CIRCUIT_OPEN = "circuit-open"
    RETRY_AFTER_EXCEEDED = "retry-after-exceeded"
    INTERNAL = "internal"


class TransportFailure(RuntimeError):
    """Redaction-safe failure emitted by an engine or the policy gateway."""

    def __init__(
        self,
        message: str,
        *,
        category: TransportFailureCategory | str = TransportFailureCategory.NETWORK,
        retryable: bool = True,
        status_code: int | None = None,
        engine: str = "requests",
        final_url: str | None = None,
        elapsed_seconds: float | None = None,
        response_evidence: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.category = TransportFailureCategory(category)
        self.kind = self.category.value
        self.retryable = bool(retryable)
        self.status_code = status_code
        self.engine = str(engine or "requests")
        self.final_url = redacted_endpoint(final_url)
        self.elapsed_seconds = (
            None if elapsed_seconds is None else max(0.0, float(elapsed_seconds))
        )
        self.response_evidence = dict(response_evidence or {})
        # ``cause`` is intentionally not retained: native exception text may
        # include credentials or a secret-bearing URL. Exception chaining is
        # still available to local callers when the failure is raised.
        del cause

    @property
    def failure_category(self) -> TransportFailureCategory:
        return self.category


class TransportRequest:
    """Engine-neutral description of one authorized HTTP attempt.

    Raw authentication and tenant scopes are immediately reduced to a SHA-256
    digest. They are never retained on this object or exposed through request
    identities and diagnostics.
    """

    __slots__ = (
        "method",
        "url",
        "params",
        "headers",
        "body",
        "timeout",
        "allow_redirects",
        "max_response_bytes",
        "requested_date",
        "source_id",
        "engine",
        "authentication_scope_digest",
    )

    def __init__(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        timeout: float | tuple[float, float] | None = None,
        allow_redirects: bool = True,
        max_response_bytes: int | None = None,
        requested_date: str | date | None = None,
        source_id: str | None = None,
        engine: str = "requests",
        authentication_scope: str | bytes | None = None,
        tenant_scope: str | bytes | None = None,
        authentication_scope_digest: str | None = None,
    ) -> None:
        normalized_method = str(method or "").strip().upper()
        if not normalized_method:
            raise ValueError("transport request method must not be empty")
        if not str(url or "").strip():
            raise ValueError("transport request URL must not be empty")
        if max_response_bytes is not None and max_response_bytes <= 0:
            raise ValueError("transport response bound must be positive")
        if body is not None and not isinstance(body, (bytes, str)):
            raise TypeError("transport request body must be bytes, text or None")
        normalized_engine = str(engine or "").strip().lower()
        if not normalized_engine:
            raise ValueError("transport request engine must not be empty")

        normalized_headers = {
            str(key): str(value) for key, value in (headers or {}).items()
        }
        normalized_params = dict(params or {})
        scope_evidence: list[Any] = []
        if authentication_scope is not None:
            scope_evidence.append(("authentication", authentication_scope))
        if tenant_scope is not None:
            scope_evidence.append(("tenant", tenant_scope))
        for name, value in normalized_headers.items():
            if _is_sensitive_name(name):
                scope_evidence.append((f"header:{name.lower()}", value))
        for name, value in normalized_params.items():
            if _is_sensitive_name(name):
                scope_evidence.append((f"parameter:{str(name).lower()}", value))
        url_parts = urlsplit(str(url))
        if url_parts.username is not None or url_parts.password is not None:
            scope_evidence.append(
                ("url-userinfo", (url_parts.username or "", url_parts.password or ""))
            )
        for name, value in parse_qsl(url_parts.query, keep_blank_values=True):
            if _is_sensitive_name(name):
                scope_evidence.append((f"query:{name.lower()}", value))
        if authentication_scope_digest is not None:
            digest = str(authentication_scope_digest).strip().lower()
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("authentication scope digest must be a SHA-256 hex digest")
        elif scope_evidence:
            digest = _sha256_json(scope_evidence)
        else:
            digest = None

        self.method = normalized_method
        self.url = str(url)
        self.params = normalized_params
        self.headers = normalized_headers
        self.body = body
        self.timeout = timeout
        self.allow_redirects = bool(allow_redirects)
        self.max_response_bytes = max_response_bytes
        self.requested_date = (
            requested_date.isoformat() if isinstance(requested_date, date) else requested_date
        )
        self.source_id = str(source_id).strip() if source_id is not None else None
        if self.source_id == "":
            raise ValueError("transport request source id must not be empty")
        self.engine = normalized_engine
        self.authentication_scope_digest = digest

    def with_timeout(self, timeout: float | tuple[float, float]) -> "TransportRequest":
        return TransportRequest(
            self.method,
            self.url,
            params=self.params,
            headers=self.headers,
            body=self.body,
            timeout=timeout,
            allow_redirects=self.allow_redirects,
            max_response_bytes=self.max_response_bytes,
            requested_date=self.requested_date,
            source_id=self.source_id,
            engine=self.engine,
            authentication_scope_digest=self.authentication_scope_digest,
        )


class TransportResponse:
    """Normalized response exposed to provider validators and adapters."""

    __slots__ = (
        "status_code",
        "headers",
        "body",
        "final_url",
        "elapsed_seconds",
        "engine",
    )

    def __init__(
        self,
        status_code: int,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | bytearray | str = b"",
        final_url: str = "",
        elapsed_seconds: float | None = None,
        engine: str = "requests",
    ) -> None:
        self.status_code = int(status_code)
        self.headers = {str(key): str(value) for key, value in (headers or {}).items()}
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = bytes(body)
        self.final_url = str(final_url or "")
        self.elapsed_seconds = (
            None if elapsed_seconds is None else max(0.0, float(elapsed_seconds))
        )
        self.engine = str(engine or "requests").lower()

    @property
    def content(self) -> bytes:
        return self.body

    @property
    def url(self) -> str:
        return self.final_url

    @property
    def encoding(self) -> str:
        content_type = next(
            (
                value
                for key, value in self.headers.items()
                if key.strip().lower() == "content-type"
            ),
            "",
        )
        for item in content_type.split(";"):
            if item.strip().lower().startswith("charset="):
                return item.split("=", 1)[1].strip().strip('"') or "utf-8"
        return "utf-8"

    @property
    def text(self) -> str:
        return self.body.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.body)

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        if self.status_code in {401, 403}:
            category = TransportFailureCategory.PERMISSION
            retryable = False
        elif self.status_code == 429:
            category = TransportFailureCategory.RATE_LIMIT
            retryable = True
        elif self.status_code == 408:
            category = TransportFailureCategory.TIMEOUT
            retryable = True
        else:
            category = TransportFailureCategory.HTTP_STATUS
            retryable = self.status_code >= 500
        raise TransportFailure(
            f"provider HTTP status {self.status_code}",
            category=category,
            retryable=retryable,
            status_code=self.status_code,
            engine=self.engine,
            final_url=self.final_url,
        )

    @classmethod
    def from_requests(
        cls,
        response: Any,
        *,
        engine: str = "requests",
        elapsed_seconds: float | None = None,
        max_response_bytes: int | None = None,
    ) -> "TransportResponse":
        missing = object()
        raw_body = getattr(response, "content", missing)
        if raw_body is missing:
            raw_text = getattr(response, "text", missing)
            if raw_text is not missing:
                body = str(raw_text).encode("utf-8")
            else:
                decode_json = getattr(response, "json", None)
                body = (
                    b""
                    if not callable(decode_json)
                    else json.dumps(
                        decode_json(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
        else:
            body = bytes(raw_body or b"")
        if max_response_bytes is not None and len(body) > max_response_bytes:
            raise TransportFailure(
                "transport response exceeds the configured size bound",
                category=TransportFailureCategory.RESPONSE_TOO_LARGE,
                retryable=False,
                engine=engine,
                status_code=getattr(response, "status_code", None),
                final_url=str(getattr(response, "url", "") or ""),
                elapsed_seconds=elapsed_seconds,
            )
        raw_headers = getattr(response, "headers", {}) or {}
        return cls(
            int(getattr(response, "status_code", 200) or 200),
            headers={str(key): str(value) for key, value in raw_headers.items()},
            body=body,
            final_url=str(getattr(response, "url", "") or ""),
            elapsed_seconds=elapsed_seconds,
            engine=engine,
        )


@runtime_checkable
class RequestEngine(Protocol):
    """Protocol for engines that execute exactly one authorized attempt."""

    name: str

    def send(self, request: TransportRequest) -> TransportResponse:
        """Issue one upstream request without retrying or switching engine."""


TransportEngine = RequestEngine


class RequestsTransportEngine:
    """Default requests-backed engine with no retry or policy state."""

    name = "requests"

    def __init__(
        self,
        session: Any | None = None,
        *,
        max_response_bytes: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.max_response_bytes = max_response_bytes
        self._clock = clock

    def send(self, request: TransportRequest) -> TransportResponse:
        if request.engine != self.name:
            raise TransportFailure(
                f"request engine {request.engine!r} does not match {self.name!r}",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
                final_url=request.url,
            )
        started_at = self._clock()
        response_bound = (
            request.max_response_bytes
            if request.max_response_bytes is not None
            else self.max_response_bytes
        )
        kwargs: dict[str, Any] = {
            "params": dict(request.params),
            "timeout": request.timeout,
        }
        if not request.allow_redirects:
            kwargs["allow_redirects"] = False
        if request.headers:
            kwargs["headers"] = dict(request.headers)
        if request.body is not None:
            kwargs["data"] = (
                request.body.encode("utf-8")
                if isinstance(request.body, str)
                else request.body
            )
        if response_bound is not None:
            kwargs["stream"] = True
        try:
            response = self._send_native(request.method, request.url, kwargs)
        except TransportFailure:
            raise
        except requests.Timeout:
            raise TransportFailure(
                "provider request timed out",
                category=TransportFailureCategory.TIMEOUT,
                retryable=True,
                engine=self.name,
                final_url=request.url,
                elapsed_seconds=self._clock() - started_at,
            ) from None
        except requests.RequestException:
            raise TransportFailure(
                "provider network request failed",
                category=TransportFailureCategory.NETWORK,
                retryable=True,
                engine=self.name,
                final_url=request.url,
                elapsed_seconds=self._clock() - started_at,
            ) from None
        except (ConnectionError, OSError):
            raise TransportFailure(
                "provider network request failed",
                category=TransportFailureCategory.NETWORK,
                retryable=True,
                engine=self.name,
                final_url=request.url,
                elapsed_seconds=self._clock() - started_at,
            ) from None
        try:
            if response_bound is not None and callable(
                getattr(response, "iter_content", None)
            ):
                return self._normalize_bounded_response(
                    response,
                    response_bound,
                    elapsed_seconds=self._clock() - started_at,
                )
            return TransportResponse.from_requests(
                response,
                engine=self.name,
                elapsed_seconds=self._clock() - started_at,
                max_response_bytes=response_bound,
            )
        except TransportFailure:
            raise
        except requests.Timeout:
            raise TransportFailure(
                "provider response read timed out",
                category=TransportFailureCategory.TIMEOUT,
                retryable=True,
                engine=self.name,
                final_url=str(getattr(response, "url", "") or request.url),
                elapsed_seconds=self._clock() - started_at,
            ) from None
        except requests.RequestException:
            raise TransportFailure(
                "provider response read failed",
                category=TransportFailureCategory.NETWORK,
                retryable=True,
                engine=self.name,
                final_url=str(getattr(response, "url", "") or request.url),
                elapsed_seconds=self._clock() - started_at,
            ) from None
        except (TypeError, ValueError, UnicodeError):
            raise TransportFailure(
                "provider response could not be normalized",
                category=TransportFailureCategory.INVALID_RESPONSE,
                retryable=False,
                engine=self.name,
                status_code=getattr(response, "status_code", None),
                final_url=str(getattr(response, "url", "") or request.url),
                elapsed_seconds=self._clock() - started_at,
            ) from None

    def request(self, request: TransportRequest) -> TransportResponse:
        return self.send(request)

    def _normalize_bounded_response(
        self,
        response: Any,
        response_bound: int,
        *,
        elapsed_seconds: float,
    ) -> TransportResponse:
        chunks: list[bytes] = []
        observed = 0
        try:
            for chunk in response.iter_content(chunk_size=min(65536, response_bound + 1)):
                if not chunk:
                    continue
                value = bytes(chunk)
                observed += len(value)
                if observed > response_bound:
                    raise TransportFailure(
                        "transport response exceeds the configured size bound",
                        category=TransportFailureCategory.RESPONSE_TOO_LARGE,
                        retryable=False,
                        engine=self.name,
                        status_code=getattr(response, "status_code", None),
                        final_url=str(getattr(response, "url", "") or ""),
                        elapsed_seconds=elapsed_seconds,
                    )
                chunks.append(value)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        raw_headers = getattr(response, "headers", {}) or {}
        return TransportResponse(
            int(getattr(response, "status_code", 200) or 200),
            headers={str(key): str(value) for key, value in raw_headers.items()},
            body=b"".join(chunks),
            final_url=str(getattr(response, "url", "") or ""),
            elapsed_seconds=elapsed_seconds,
            engine=self.name,
        )

    def _send_native(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        request_method = getattr(self.session, "request", None)
        if callable(request_method):
            return request_method(method, url, **kwargs)
        method_method = getattr(self.session, method.lower(), None)
        if not callable(method_method):
            raise TransportFailure(
                f"requests session does not support HTTP method {method}",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
                final_url=url,
            )
        return method_method(url, **kwargs)


class TransportEngineRegistry:
    """Complete, fail-closed registry of request engines."""

    def __init__(
        self,
        engines: Iterable[RequestEngine] = (),
        *,
        default_engine: str = "requests",
    ) -> None:
        self.default_engine = str(default_engine).strip().lower()
        if not self.default_engine:
            raise ValueError("default transport engine must not be empty")
        self._engines: dict[str, RequestEngine] = {}
        for engine in engines:
            self.register(engine)
        if self.default_engine not in self._engines:
            raise ValueError(
                f"default transport engine {self.default_engine!r} is not registered"
            )

    def register(self, engine: RequestEngine) -> None:
        name = str(getattr(engine, "name", "")).strip().lower()
        if not name or not callable(getattr(engine, "send", None)):
            raise TypeError("transport engine must provide a name and send(request)")
        if name in self._engines:
            raise ValueError(f"duplicate transport engine registration: {name}")
        self._engines[name] = engine

    def resolve(self, name: str | None = None) -> RequestEngine:
        selected = str(name or self.default_engine).strip().lower()
        engine = self._engines.get(selected)
        if engine is None:
            raise TransportFailure(
                f"transport engine {selected!r} is unavailable",
                category=TransportFailureCategory.ENGINE_UNAVAILABLE,
                retryable=False,
                engine=selected or "unknown",
            )
        return engine

    def require(self, names: Iterable[str]) -> None:
        missing = sorted(
            str(name).strip().lower()
            for name in names
            if str(name).strip().lower() not in self._engines
        )
        if missing:
            raise ValueError(f"missing transport engine registrations: {', '.join(missing)}")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._engines))


RequestEngineRegistry = TransportEngineRegistry


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
    last_engine: str | None = None
    last_endpoint: str | None = None
    last_failure: str | None = None
    last_request_identity: str | None = None
    last_authentication_scope_digest: str | None = None


@dataclass
class _Inflight:
    event: threading.Event
    response: TransportResponse | None = None
    error: BaseException | None = None


class TransportPolicyGateway:
    """Authoritative host policy boundary shared by all request engines."""

    def __init__(
        self,
        engine_registry: TransportEngineRegistry | None = None,
        *,
        engines: Iterable[RequestEngine] | None = None,
        policies: Mapping[str, HostPolicy] | None = None,
        default_policy: HostPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        challenge_detector: Callable[[TransportResponse], bool] | None = None,
    ) -> None:
        if engine_registry is not None and engines is not None:
            raise ValueError("provide either engine_registry or engines, not both")
        self.engine_registry = engine_registry or TransportEngineRegistry(
            engines or (RequestsTransportEngine(clock=clock),)
        )
        self._policies = {
            normalized_host(host): policy for host, policy in (policies or {}).items()
        }
        self._default_policy = default_policy or HostPolicy()
        self._clock = clock
        self._sleep = sleeper
        self._random_uniform = random_uniform
        self._challenge_detector = challenge_detector or self._default_challenge_detector
        self._states: dict[str, _HostState] = {}
        self._cache: dict[str, tuple[float, TransportResponse]] = {}
        self._cache_hosts: dict[str, str] = {}
        self._inflight: dict[str, _Inflight] = {}
        self._lock = threading.RLock()

    def request(
        self,
        request: TransportRequest,
        *,
        cache_ttl: float | None = None,
        validator: Callable[[TransportResponse], bool] | None = None,
        gate: Callable[[Callable[[], TransportResponse]], TransportResponse] | None = None,
    ) -> TransportResponse:
        engine = self.engine_registry.resolve(request.engine)
        host = normalized_host(request.url)
        policy = self._policy(host)
        if request.timeout is None:
            request = request.with_timeout(policy.timeout)
        cache_seconds = (
            policy.cache_ttl_seconds if cache_ttl is None else max(0.0, cache_ttl)
        )
        identity = self.request_identity(request, gated=gate is not None)

        with self._lock:
            if cache_seconds > 0:
                cached = self._cache.get(identity)
                if cached is not None and cached[0] > self._clock():
                    self._validate_response(cached[1], validator, host, cached=True)
                    return cached[1]
                if cached is not None:
                    self._cache.pop(identity, None)
                    self._cache_hosts.pop(identity, None)
            current = self._inflight.get(identity)
            if current is None:
                current = _Inflight(event=threading.Event())
                self._inflight[identity] = current
                owner = True
            else:
                owner = False

        if not owner:
            current.event.wait()
            if current.error is not None:
                raise current.error
            if current.response is None:
                raise TransportFailure(
                    "provider request completed without a response",
                    category=TransportFailureCategory.INTERNAL,
                    retryable=False,
                    engine=engine.name,
                )
            self._validate_response(current.response, validator, host, cached=True)
            return current.response

        try:
            response = self._request_with_policy(
                request,
                engine,
                host=host,
                policy=policy,
                identity=identity,
                validator=validator,
                gate=gate,
            )
            if cache_seconds > 0:
                with self._lock:
                    self._cache[identity] = (self._clock() + cache_seconds, response)
                    self._cache_hosts[identity] = host
            current.response = response
            return response
        except BaseException as exc:
            current.error = exc
            raise
        finally:
            with self._lock:
                self._inflight.pop(identity, None)
                current.event.set()

    def request_identity(self, request: TransportRequest, *, gated: bool = False) -> str:
        body = request.body
        body_digest = None
        if body is not None:
            encoded_body = body.encode("utf-8") if isinstance(body, str) else body
            body_digest = hashlib.sha256(encoded_body).hexdigest()
        identity = {
            "method": request.method,
            "url": _normalized_url(request.url),
            "params": request.params,
            "headers": {
                str(key).strip().lower(): value
                for key, value in sorted(
                    request.headers.items(), key=lambda pair: str(pair[0]).lower()
                )
            },
            "bodySha256": body_digest,
            "allowRedirects": request.allow_redirects,
            "maxResponseBytes": request.max_response_bytes,
            "requestedDate": request.requested_date,
            "sourceId": request.source_id,
            "engine": request.engine,
            "authenticationScopeDigest": request.authentication_scope_digest,
            "gate": "external" if gated else "internal",
        }
        return _sha256_json(identity)

    def host_diagnostics(self, host: str) -> dict[str, Any]:
        normalized = normalized_host(host)
        with self._lock:
            state = self._states.get(normalized, _HostState())
            now = self._clock()
            return {
                "host": normalized,
                "engine": state.last_engine,
                "endpoint": state.last_endpoint,
                "requestIdentity": state.last_request_identity,
                "authenticationScopeDigest": state.last_authentication_scope_digest,
                "requestsUsed": state.requests_used,
                "budgetWindowSeconds": self._policy(normalized).budget_window_seconds,
                "failures": state.failures,
                "lastFailure": state.last_failure,
                "cooldownRemaining": max(0.0, state.open_until - now),
                "lastRequestSeconds": state.last_request_seconds,
                "lastRetryCount": state.last_retry_count,
            }

    def reset_host(self, host: str) -> None:
        normalized = normalized_host(host)
        with self._lock:
            self._states.pop(normalized, None)
            stale_keys = [
                key for key, cache_host in self._cache_hosts.items() if cache_host == normalized
            ]
            for key in stale_keys:
                self._cache.pop(key, None)
                self._cache_hosts.pop(key, None)

    def policy_for(self, host: str) -> HostPolicy:
        """Return the effective immutable policy for compatibility diagnostics."""

        return self._policy(normalized_host(host))

    def _request_with_policy(
        self,
        request: TransportRequest,
        engine: RequestEngine,
        *,
        host: str,
        policy: HostPolicy,
        identity: str,
        validator: Callable[[TransportResponse], bool] | None,
        gate: Callable[[Callable[[], TransportResponse]], TransportResponse] | None,
    ) -> TransportResponse:
        started_at = self._clock()
        probe_owner = False
        retry_count = 0
        try:
            for attempt in range(policy.max_retries + 1):
                probe_owner = self._wait_for_slot(
                    host,
                    policy,
                    use_internal_gate=gate is None,
                    probe_owner=probe_owner,
                )
                self._authorize_attempt(
                    host,
                    policy,
                    engine=engine.name,
                    request=request,
                    identity=identity,
                )
                operation = lambda: engine.send(request)
                try:
                    response = gate(operation) if gate is not None else operation()
                except TransportFailure as failure:
                    failure = self._govern_engine_failure(failure, host, engine.name)
                    self._record_failure_category(host, failure.category)
                    if failure.retryable and attempt < policy.max_retries:
                        retry_count += 1
                        try:
                            self._backoff(
                                policy,
                                attempt,
                                engine=engine.name,
                                final_url=request.url,
                            )
                        except TransportFailure as backoff_failure:
                            self._record_failure_category(host, backoff_failure.category)
                            self._record_retryable_failure(host, policy)
                            raise
                        continue
                    if failure.retryable:
                        self._record_retryable_failure(host, policy)
                    else:
                        self._record_non_retryable_failure(host)
                    raise failure from None
                except Exception:
                    failure = TransportFailure(
                        "transport engine raised an unclassified failure",
                        category=TransportFailureCategory.INTERNAL,
                        retryable=False,
                        engine=engine.name,
                        final_url=request.url,
                    )
                    self._record_failure_category(host, failure.category)
                    self._record_non_retryable_failure(host)
                    raise failure from None

                if not isinstance(response, TransportResponse):
                    failure = TransportFailure(
                        "transport engine returned an invalid response contract",
                        category=TransportFailureCategory.CONTRACT,
                        retryable=False,
                        engine=engine.name,
                        final_url=request.url,
                    )
                    self._record_failure_category(host, failure.category)
                    self._record_non_retryable_failure(host)
                    raise failure
                if response.engine != engine.name:
                    response = TransportResponse(
                        response.status_code,
                        headers=response.headers,
                        body=response.body,
                        final_url=response.final_url,
                        elapsed_seconds=response.elapsed_seconds,
                        engine=engine.name,
                    )

                failure = self._response_failure(response, host, request)
                if failure is not None:
                    self._record_failure_category(host, failure.category)
                    if failure.retryable and attempt < policy.max_retries:
                        retry_count += 1
                        try:
                            self._backoff(
                                policy,
                                attempt,
                                response=response,
                                engine=engine.name,
                                final_url=request.url,
                                response_evidence=failure.response_evidence,
                            )
                        except TransportFailure as backoff_failure:
                            self._record_failure_category(host, backoff_failure.category)
                            self._record_retryable_failure(host, policy)
                            raise
                        continue
                    if failure.retryable:
                        self._record_retryable_failure(host, policy)
                    else:
                        self._record_non_retryable_failure(host)
                    raise failure

                self._validate_response(response, validator, host, cached=False)
                self._record_success(host)
                return response
        finally:
            if probe_owner:
                self._clear_probe(host)
            self._record_timing(host, started_at, retry_count)
        raise TransportFailure(
            "provider request failed without a classified result",
            category=TransportFailureCategory.INTERNAL,
            retryable=False,
            engine=engine.name,
        )

    def _response_failure(
        self,
        response: TransportResponse,
        host: str,
        request: TransportRequest,
    ) -> TransportFailure | None:
        status = response.status_code
        response_evidence = _redacted_response_evidence(response, request)
        if status in {401, 403}:
            return TransportFailure(
                f"provider HTTP status {status} from {host}",
                category=TransportFailureCategory.PERMISSION,
                retryable=False,
                status_code=status,
                engine=response.engine,
                final_url=response.final_url,
                response_evidence=response_evidence,
            )
        try:
            challenged = self._challenge_detector(response)
        except Exception:
            return TransportFailure(
                f"provider challenge detector failed for {host}",
                category=TransportFailureCategory.CONTRACT,
                retryable=False,
                status_code=status,
                engine=response.engine,
                final_url=response.final_url,
                response_evidence=response_evidence,
            )
        if challenged:
            return TransportFailure(
                f"provider access-control challenge from {host}",
                category=TransportFailureCategory.CHALLENGE,
                retryable=False,
                status_code=status,
                engine=response.engine,
                final_url=response.final_url,
                response_evidence=response_evidence,
            )
        if status == 429:
            category = TransportFailureCategory.RATE_LIMIT
        elif status == 408:
            category = TransportFailureCategory.TIMEOUT
        elif status >= 500:
            category = TransportFailureCategory.HTTP_STATUS
        elif status >= 400:
            return TransportFailure(
                f"provider HTTP status {status} from {host}",
                category=TransportFailureCategory.HTTP_STATUS,
                retryable=False,
                status_code=status,
                engine=response.engine,
                final_url=response.final_url,
                response_evidence=response_evidence,
            )
        else:
            return None
        return TransportFailure(
            f"provider HTTP status {status} from {host}",
            category=category,
            retryable=True,
            status_code=status,
            engine=response.engine,
            final_url=response.final_url,
            response_evidence=response_evidence,
        )

    @staticmethod
    def _govern_engine_failure(
        failure: TransportFailure,
        host: str,
        engine: str,
    ) -> TransportFailure:
        retryable_categories = {
            TransportFailureCategory.NETWORK,
            TransportFailureCategory.TIMEOUT,
            TransportFailureCategory.RATE_LIMIT,
            TransportFailureCategory.HTTP_STATUS,
        }
        retryable = failure.retryable and failure.category in retryable_categories
        if failure.status_code in {401, 403}:
            retryable = False
        return TransportFailure(
            f"provider {failure.category.value} failure for {host}",
            category=failure.category,
            retryable=retryable,
            status_code=failure.status_code,
            engine=engine,
            final_url=failure.final_url,
            elapsed_seconds=failure.elapsed_seconds,
            response_evidence=failure.response_evidence,
        )

    def _validate_response(
        self,
        response: TransportResponse,
        validator: Callable[[TransportResponse], bool] | None,
        host: str,
        *,
        cached: bool,
    ) -> None:
        if validator is None:
            return
        try:
            valid = bool(validator(response))
        except Exception:
            prefix = "cached " if cached else ""
            failure = TransportFailure(
                f"provider {prefix}response contract rejected for {host}",
                category=TransportFailureCategory.CONTRACT,
                retryable=False,
                status_code=response.status_code,
                engine=response.engine,
                final_url=response.final_url,
            )
            self._record_failure_category(host, failure.category)
            self._record_non_retryable_failure(host)
            raise failure from None
        if not valid:
            prefix = "cached " if cached else ""
            failure = TransportFailure(
                f"provider {prefix}response contract rejected for {host}",
                category=TransportFailureCategory.CONTRACT,
                retryable=False,
                status_code=response.status_code,
                engine=response.engine,
                final_url=response.final_url,
            )
            self._record_failure_category(host, failure.category)
            self._record_non_retryable_failure(host)
            raise failure

    def _authorize_attempt(
        self,
        host: str,
        policy: HostPolicy,
        *,
        engine: str,
        request: TransportRequest,
        identity: str,
    ) -> None:
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
            state.last_engine = engine
            state.last_endpoint = redacted_endpoint(request.url)
            state.last_request_identity = identity
            state.last_authentication_scope_digest = request.authentication_scope_digest
            if state.requests_used > policy.request_budget:
                state.last_failure = (
                    TransportFailureCategory.REQUEST_BUDGET_EXHAUSTED.value
                )
                raise TransportFailure(
                    f"provider request budget exceeded for {host}",
                    category=TransportFailureCategory.REQUEST_BUDGET_EXHAUSTED,
                    retryable=False,
                    engine=engine,
                    final_url=request.url,
                )

    def _wait_for_slot(
        self,
        host: str,
        policy: HostPolicy,
        *,
        use_internal_gate: bool,
        probe_owner: bool,
    ) -> bool:
        now = self._clock()
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            if not probe_owner and state.open_until > now:
                state.last_failure = TransportFailureCategory.CIRCUIT_OPEN.value
                raise TransportFailure(
                    f"provider host {host} is cooling down",
                    category=TransportFailureCategory.CIRCUIT_OPEN,
                    retryable=True,
                    engine=state.last_engine or "requests",
                )
            if state.open_until and not probe_owner:
                if state.probe_in_flight:
                    state.last_failure = TransportFailureCategory.CIRCUIT_OPEN.value
                    raise TransportFailure(
                        f"provider host {host} is being probed",
                        category=TransportFailureCategory.CIRCUIT_OPEN,
                        retryable=True,
                        engine=state.last_engine or "requests",
                    )
                state.probe_in_flight = True
            required = max(0.0, policy.minimum_interval) if use_internal_gate else 0.0
            if required:
                required += max(0.0, self._random_uniform(*policy.jitter))
            delay = max(0.0, state.next_allowed_at - now)
            state.next_allowed_at = max(now, state.next_allowed_at) + required
        if delay > 0:
            self._sleep(delay)
        return probe_owner or bool(state.open_until)

    def _backoff(
        self,
        policy: HostPolicy,
        attempt: int,
        *,
        response: TransportResponse | None = None,
        engine: str = "requests",
        final_url: str | None = None,
        response_evidence: Mapping[str, Any] | None = None,
    ) -> None:
        retry_after = self._retry_after(response)
        if retry_after is not None:
            if retry_after > policy.max_retry_after_seconds:
                raise TransportFailure(
                    "provider Retry-After exceeds the bounded retry wait",
                    category=TransportFailureCategory.RETRY_AFTER_EXCEEDED,
                    retryable=True,
                    status_code=response.status_code if response is not None else None,
                    engine=response.engine if response is not None else engine,
                    final_url=(
                        response.final_url or final_url
                        if response is not None
                        else final_url
                    ),
                    response_evidence=response_evidence,
                )
            self._sleep(retry_after)
            return
        base = max(0.0, policy.retry_backoff) * (2**attempt)
        self._sleep(base + self._random_uniform(0.0, max(0.0, policy.jitter[1])))

    @staticmethod
    def _retry_after(response: TransportResponse | None) -> float | None:
        if response is None:
            return None
        raw = next(
            (
                value
                for key, value in response.headers.items()
                if key.strip().lower() == "retry-after"
            ),
            None,
        )
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

    @staticmethod
    def _default_challenge_detector(response: TransportResponse) -> bool:
        content_type = next(
            (
                value.lower()
                for key, value in response.headers.items()
                if key.strip().lower() == "content-type"
            ),
            "",
        )
        sample = response.body[:65536].decode("utf-8", errors="ignore").lower()
        is_html = "text/html" in content_type or "<html" in sample or "<!doctype" in sample
        return is_html and any(marker in sample for marker in _CHALLENGE_MARKERS)

    def _record_failure_category(
        self,
        host: str,
        category: TransportFailureCategory,
    ) -> None:
        with self._lock:
            self._states.setdefault(host, _HostState()).last_failure = category.value

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
            state.last_failure = None

    def _record_retryable_failure(self, host: str, policy: HostPolicy) -> None:
        with self._lock:
            state = self._states.setdefault(host, _HostState())
            state.failures += 1
            state.probe_in_flight = False
            if state.failures >= max(1, policy.failure_threshold):
                state.open_until = self._clock() + max(0.0, policy.cooldown_seconds)

    def _record_non_retryable_failure(self, host: str) -> None:
        with self._lock:
            self._states.setdefault(host, _HostState()).probe_in_flight = False

    def _clear_probe(self, host: str) -> None:
        with self._lock:
            self._states.setdefault(host, _HostState()).probe_in_flight = False

    def _policy(self, host: str) -> HostPolicy:
        return self._policies.get(host, self._default_policy)


_PROCESS_GATEWAY_LOCK = threading.Lock()
_PROCESS_GATEWAY: TransportPolicyGateway | None = None


def build_default_transport_gateway(
    **kwargs: Any,
) -> TransportPolicyGateway:
    """Build a requests-only gateway without mutating process shared state."""

    clock = kwargs.get("clock", time.monotonic)
    registry = TransportEngineRegistry((RequestsTransportEngine(clock=clock),))
    return TransportPolicyGateway(registry, **kwargs)


def get_process_transport_gateway(
    *,
    engine_registry: TransportEngineRegistry | None = None,
    **kwargs: Any,
) -> TransportPolicyGateway:
    """Return the process-wide composition-root gateway singleton."""

    global _PROCESS_GATEWAY
    with _PROCESS_GATEWAY_LOCK:
        if _PROCESS_GATEWAY is None:
            if engine_registry is None:
                _PROCESS_GATEWAY = build_default_transport_gateway(**kwargs)
            else:
                _PROCESS_GATEWAY = TransportPolicyGateway(
                    engine_registry,
                    **kwargs,
                )
        elif engine_registry is not None or kwargs:
            raise RuntimeError("process transport gateway is already configured")
        return _PROCESS_GATEWAY


def configure_process_transport_gateway(
    gateway: TransportPolicyGateway,
) -> TransportPolicyGateway:
    """Install one explicitly composed process gateway, failing on replacement."""

    global _PROCESS_GATEWAY
    with _PROCESS_GATEWAY_LOCK:
        if _PROCESS_GATEWAY is not None and _PROCESS_GATEWAY is not gateway:
            raise RuntimeError("process transport gateway is already configured")
        _PROCESS_GATEWAY = gateway
        return gateway


def reset_process_transport_gateway_for_testing() -> None:
    """Clear singleton state for deterministic offline tests only."""

    global _PROCESS_GATEWAY
    with _PROCESS_GATEWAY_LOCK:
        _PROCESS_GATEWAY = None


__all__ = [
    "HostPolicy",
    "RequestEngine",
    "RequestEngineRegistry",
    "RequestsTransportEngine",
    "TransportEngine",
    "TransportEngineRegistry",
    "TransportFailure",
    "TransportFailureCategory",
    "TransportPolicyGateway",
    "TransportRequest",
    "TransportResponse",
    "build_default_transport_gateway",
    "configure_process_transport_gateway",
    "get_process_transport_gateway",
    "normalized_host",
    "redacted_endpoint",
    "reset_process_transport_gateway_for_testing",
]
