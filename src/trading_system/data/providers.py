"""Provider quality, fallback, and after-market snapshot boundaries."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_GLOBAL_EASTMONEY_LIMITER: "SerialRateLimiter | None" = None


@dataclass(frozen=True)
class ProviderQuality:
    dataset: str
    provider: str
    status: str
    observations: int
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


class ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SerialRateLimiter:
    """Shared serial limiter with injectable timing for deterministic tests."""

    def __init__(
        self,
        minimum_interval: float = 1.0,
        jitter: tuple[float, float] = (0.05, 0.25),
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if minimum_interval < 1.0:
            raise ValueError("Eastmoney minimum interval must be at least 1 second")
        self.minimum_interval = minimum_interval
        self.jitter = jitter
        self.clock = clock
        self.sleeper = sleeper
        self.random_uniform = random_uniform
        self._last_request_at: float | None = None
        self._request_lock = threading.Lock()

    def acquire(self) -> None:
        with self._request_lock:
            self._acquire_unlocked()

    def run(self, operation: Callable[[], Any]) -> Any:
        """Serialize the complete provider request, including rate-limit waiting."""
        with self._request_lock:
            self._acquire_unlocked()
            return operation()

    def _acquire_unlocked(self) -> None:
        now = self.clock()
        if self._last_request_at is not None:
            required = self.minimum_interval + self.random_uniform(*self.jitter)
            remaining = required - (now - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()
        self._last_request_at = now


class EastmoneyClient:
    """Rate-limited shared Eastmoney session; HTTP 403 is never retried blindly."""

    def __init__(
        self,
        timeout: float = 8.0,
        limiter: SerialRateLimiter | None = None,
        session: requests.Session | None = None,
        retry_total: int = 2,
        retry_backoff: float = 0.6,
    ) -> None:
        global _GLOBAL_EASTMONEY_LIMITER
        self.timeout = timeout
        if _GLOBAL_EASTMONEY_LIMITER is None:
            _GLOBAL_EASTMONEY_LIMITER = SerialRateLimiter()
        self.limiter = limiter or _GLOBAL_EASTMONEY_LIMITER
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        mount = getattr(self.session, "mount", None)
        if callable(mount):
            retry = Retry(
                total=retry_total,
                connect=retry_total,
                read=retry_total,
                status=retry_total,
                backoff_factor=retry_backoff,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry)
            mount("https://", adapter)
            mount("http://", adapter)

    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.limiter.run(lambda: self.session.get(url, params=params, timeout=self.timeout))
        except requests.RequestException as exc:
            raise ProviderFailure(str(exc), retryable=True) from exc
        status_code = getattr(response, "status_code", 200)
        if status_code == 403:
            raise ProviderFailure("Eastmoney returned HTTP 403", status_code=403, retryable=False)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            retryable = status_code == 429 or status_code >= 500
            raise ProviderFailure(str(exc), status_code=status_code, retryable=retryable) from exc
        return response.json()


class FallbackChain:
    """Run providers serially and retain an auditable degradation record."""

    def __init__(self, providers: Iterable[tuple[str, Callable[[], Any]]]) -> None:
        self.providers = tuple(providers)

    def fetch(self, dataset: str) -> tuple[Any | None, ProviderQuality]:
        warnings: list[str] = []
        for index, (name, provider) in enumerate(self.providers):
            try:
                value = provider()
                status = "ok" if index == 0 else "fallback"
                return value, ProviderQuality(dataset, name, status, _observation_count(value), tuple(warnings))
            except ProviderFailure as exc:
                warnings.append(f"{name}: {exc}")
            except Exception as exc:  # provider boundary must preserve later fallbacks
                warnings.append(f"{name}: {exc}")
        return None, ProviderQuality(dataset, "none", "failed", 0, tuple(warnings))


def _observation_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, dict, set)):
        return len(value)
    return 1


def create_after_market_snapshot(as_of: date, service: Any | None = None) -> dict[str, Any]:
    """Create a real-data partial snapshot without inventing unavailable breadth data.

    The existing market-environment service supplies the index slice. Chapter 01
    needs several additional datasets, so this first-stage provider deliberately
    marks the snapshot insufficient until those inputs are connected.
    """

    from src.market_environment.service import MarketEnvironmentService

    market_service = service or MarketEnvironmentService()
    created_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    try:
        payload = market_service.get(as_of)
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "asOf": as_of.isoformat(),
            "createdAt": created_at,
            "status": "insufficient",
            "providerQuality": [ProviderQuality("index-daily", "fallback-chain", "failed", 0, (str(exc),)).to_dict()],
            "metrics": {},
            "events": [],
            "warnings": [f"index provider failed: {exc}", "chapter 01 requires breadth, limit, sector, active-security, and event datasets"],
        }

    indices = payload.get("indices", [])
    valid_ma = [
        item
        for item in indices
        if all(item.get("movingAverages", {}).get(key) is not None for key in ("ma5", "ma10", "ma20"))
    ]
    bullish = [
        item
        for item in valid_ma
        if item["close"] > item["movingAverages"]["ma5"] > item["movingAverages"]["ma10"] > item["movingAverages"]["ma20"]
    ]
    positions = [item.get("rangePosition60") for item in indices if item.get("rangePosition60") is not None]
    turnover = [item.get("amountRatio20") for item in indices if item.get("amountRatio20") is not None]
    warnings = list(payload.get("summary", {}).get("warnings", []))
    warnings.append("chapter 01 breadth, limit, tier-risk, sector, active-security, and event datasets are not yet connected")
    sources = sorted({item.get("dataQuality", {}).get("source", "unknown") for item in indices})
    status = "fallback" if warnings else "ok"
    return {
        "schemaVersion": 1,
        "asOf": payload.get("asOf", as_of.isoformat()),
        "createdAt": payload.get("generatedAt", created_at),
        "status": "insufficient",
        "providerQuality": [
            ProviderQuality("index-daily", "+".join(sources), status, len(indices), tuple(warnings[:-1])).to_dict(),
            ProviderQuality("chapter-01-extended", "not-connected", "missing", 0, (warnings[-1],)).to_dict(),
        ],
        "metrics": {
            "index.bullish_ratio": len(bullish) / len(valid_ma) if valid_ma else None,
            "index.range_position_60": sum(positions) / len(positions) if positions else None,
            "market.turnover_ratio_20": sum(turnover) / len(turnover) if turnover else None,
        },
        "events": [],
        "warnings": warnings,
    }
