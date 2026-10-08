"""Optional static Scrapling engine with fail-closed source authorization."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .provider_transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportRequest,
    TransportResponse,
    normalized_host,
)


@dataclass(frozen=True, slots=True)
class ScraplingStaticEngineConfig:
    """Explicit opt-in for authorized host/source pairs; empty by default."""

    enabled: bool = False
    allowlist: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized: set[tuple[str, str]] = set()
        for entry in self.allowlist:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValueError("Scrapling allowlist entries must be (host, source_id) pairs")
            raw_host, raw_source = entry
            host = normalized_host(str(raw_host).strip())
            source = str(raw_source).strip()
            if not host or not source or "*" in {host, source}:
                raise ValueError("Scrapling allowlist host and source must be explicit")
            normalized.add((host, source))
        object.__setattr__(self, "allowlist", frozenset(normalized))

    def permits(self, url: str, source_id: str | None) -> bool:
        if not self.enabled or source_id is None:
            return False
        return (normalized_host(url), source_id) in self.allowlist


class ScraplingStaticHttpEngine:
    """Single-attempt adapter over Scrapling's non-browser ``Fetcher``."""

    name = "scrapling"
    internal_retries = 0
    blocked_request_escalation = False
    proxy_rotation = False
    challenge_solving = False
    browser_enabled = False

    def __init__(
        self,
        config: ScraplingStaticEngineConfig | None = None,
        *,
        fetcher: Any | None = None,
        fetcher_loader: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if fetcher is not None and fetcher_loader is not None:
            raise ValueError("provide either a Scrapling fetcher or loader, not both")
        self.config = config or ScraplingStaticEngineConfig()
        self._fetcher = fetcher
        self._fetcher_loader = fetcher_loader or self._load_optional_fetcher
        self._clock = clock
        self._loader_lock = threading.Lock()

    def send(self, request: TransportRequest) -> TransportResponse:
        self._validate_request(request)
        fetcher = self._resolve_fetcher(request.url)
        started_at = self._clock()
        kwargs: dict[str, Any] = {
            "params": dict(request.params),
            "headers": dict(request.headers),
            "retries": self.internal_retries,
        }
        if request.timeout is not None:
            kwargs["timeout"] = request.timeout
        try:
            native_response = fetcher.get(request.url, **kwargs)
        except TransportFailure:
            raise
        except ImportError:
            raise self._engine_unavailable(request.url) from None
        except Exception as exc:
            exception_name = type(exc).__name__.lower()
            category = (
                TransportFailureCategory.TIMEOUT
                if "timeout" in exception_name
                else TransportFailureCategory.NETWORK
            )
            raise TransportFailure(
                "Scrapling static request failed",
                category=category,
                retryable=True,
                engine=self.name,
                final_url=request.url,
                elapsed_seconds=self._clock() - started_at,
            ) from None
        return self._normalize_response(
            native_response,
            request,
            elapsed_seconds=self._clock() - started_at,
        )

    def _validate_request(self, request: TransportRequest) -> None:
        if request.engine != self.name:
            raise TransportFailure(
                "transport request selected another engine",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
                final_url=request.url,
            )
        parts = urlsplit(request.url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise TransportFailure(
                "Scrapling requires an absolute HTTP(S) URL",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
            )
        if request.method != "GET" or request.body is not None:
            raise TransportFailure(
                "Scrapling static engine supports bodyless GET requests only",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
                final_url=request.url,
            )
        if not self.config.permits(request.url, request.source_id):
            raise TransportFailure(
                "Scrapling engine is disabled or source/host is not allowlisted",
                category=TransportFailureCategory.CONFIGURATION,
                retryable=False,
                engine=self.name,
                final_url=request.url,
            )

    def _resolve_fetcher(self, url: str) -> Any:
        if self._fetcher is not None:
            return self._fetcher
        with self._loader_lock:
            if self._fetcher is not None:
                return self._fetcher
            try:
                fetcher = self._fetcher_loader()
            except (AttributeError, ImportError, ModuleNotFoundError):
                raise self._engine_unavailable(url) from None
            if not callable(getattr(fetcher, "get", None)):
                raise self._engine_unavailable(url)
            self._fetcher = fetcher
            return fetcher

    @staticmethod
    def _load_optional_fetcher() -> Any:
        module = importlib.import_module("scrapling.fetchers")
        return getattr(module, "Fetcher")

    def _normalize_response(
        self,
        response: Any,
        request: TransportRequest,
        *,
        elapsed_seconds: float,
    ) -> TransportResponse:
        status: int | None = None
        final_url = request.url
        try:
            status = self._response_status(response)
            headers = self._response_headers(response)
            final_url = str(
                getattr(response, "url", None)
                or getattr(response, "final_url", None)
                or request.url
            )
            body = self._response_body(response)
        except (TypeError, ValueError, AttributeError):
            raise TransportFailure(
                "Scrapling response could not be normalized",
                category=TransportFailureCategory.INVALID_RESPONSE,
                retryable=False,
                status_code=status,
                engine=self.name,
                final_url=final_url,
                elapsed_seconds=elapsed_seconds,
            ) from None
        if request.max_response_bytes is not None and len(body) > request.max_response_bytes:
            raise TransportFailure(
                "transport response exceeds the configured size bound",
                category=TransportFailureCategory.RESPONSE_TOO_LARGE,
                retryable=False,
                status_code=status,
                engine=self.name,
                final_url=final_url,
                elapsed_seconds=elapsed_seconds,
            )
        return TransportResponse(
            status,
            headers=headers,
            body=body,
            final_url=final_url,
            elapsed_seconds=elapsed_seconds,
            engine=self.name,
        )

    @staticmethod
    def _response_status(response: Any) -> int:
        raw_status = getattr(response, "status_code", None)
        if raw_status is None:
            raw_status = getattr(response, "status", None)
        if isinstance(raw_status, bool) or raw_status is None:
            raise ValueError("missing response status")
        status = int(raw_status)
        if status < 100 or status > 599:
            raise ValueError("invalid response status")
        return status

    @staticmethod
    def _response_headers(response: Any) -> dict[str, str]:
        raw_headers = getattr(response, "headers", None)
        if raw_headers is None:
            return {}
        if not isinstance(raw_headers, Mapping):
            raw_headers = dict(raw_headers)
        return {str(key): str(value) for key, value in raw_headers.items()}

    @staticmethod
    def _response_body(response: Any) -> bytes:
        missing = object()
        for attribute in ("content", "body", "text"):
            raw_body = getattr(response, attribute, missing)
            if raw_body is missing or raw_body is None:
                continue
            if isinstance(raw_body, str):
                return raw_body.encode("utf-8")
            if isinstance(raw_body, (bytes, bytearray, memoryview)):
                return bytes(raw_body)
        raise TypeError("missing response body")

    def _engine_unavailable(self, url: str) -> TransportFailure:
        return TransportFailure(
            "Scrapling static engine dependency is unavailable",
            category=TransportFailureCategory.ENGINE_UNAVAILABLE,
            retryable=False,
            engine=self.name,
            final_url=url,
        )


__all__ = ["ScraplingStaticEngineConfig", "ScraplingStaticHttpEngine"]
