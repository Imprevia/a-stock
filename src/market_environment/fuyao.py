"""Strict client for the Fuyao dated A-share limit-pool APIs."""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

import requests


FUYAO_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
FUYAO_BASE_URL = "https://fuyao.aicubes.cn"
MARKET_TIME_ZONE = ZoneInfo("Asia/Shanghai")
_THSCODE_RE = re.compile(r"^(?P<ticker>\d{6})\.(?P<exchange>SH|SZ|BJ)$")


class FuyaoError(RuntimeError):
    """Base error that is safe to expose without leaking request headers."""


class FuyaoConfigurationError(FuyaoError):
    pass


class FuyaoTransportError(FuyaoError):
    pass


class FuyaoPermissionError(FuyaoError):
    pass


class FuyaoContractError(FuyaoError):
    pass


class FuyaoNonTradingDayError(FuyaoError):
    pass


@dataclass(frozen=True)
class FuyaoPoolResult:
    rows: tuple[dict[str, Any], ...]
    total: int
    pages: int


@dataclass(frozen=True)
class FuyaoLimitDataset:
    as_of: date
    pools: Mapping[str, FuyaoPoolResult]
    tickers: Mapping[str, dict[str, Any]]
    warnings: tuple[str, ...] = ()


class FuyaoClient:
    """Small synchronous client with bounded retry and strict pagination checks."""

    _POOL_PATHS = {
        "limit_up": "/api/a-share/special-data/limit-up-pool",
        "limit_down": "/api/a-share/special-data/limit-down-pool",
        "failed_limit_up": "/api/a-share/special-data/limit-break-pool",
    }
    _RETRYABLE_ENVELOPE_CODES = frozenset({4001, 5001, 5002, 5003})
    _PERMISSION_CODES = frozenset({2001, 2003})
    _PAGE_SIZE = 200
    _MAX_POOL_PAGES = 100

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 8.0,
        session: requests.Session | None = None,
        base_url: str = FUYAO_BASE_URL,
        max_retries: int = 2,
        backoff_seconds: float = 0.2,
        ticker_cache_ttl_seconds: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv(FUYAO_API_KEY_ENV, "")).strip()
        self.timeout = timeout
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.ticker_cache_ttl_seconds = max(0.0, float(ticker_cache_ttl_seconds))
        self._sleep = sleep
        self._monotonic = monotonic
        self._ticker_cache: dict[str, dict[str, Any]] | None = None
        self._ticker_cache_created_at: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self) -> None:
        if not self.configured:
            raise FuyaoConfigurationError(f"{FUYAO_API_KEY_ENV} is required for limits V1 collection")

    def fetch_trading_days(self) -> tuple[date, ...]:
        data = self._request_data("/api/a-share/calendar/trading-days")
        items = data.get("item")
        if not isinstance(items, list) or not items:
            raise FuyaoContractError("trading calendar response has no rows")
        sessions: list[date] = []
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise FuyaoContractError(f"trading calendar row {index} is malformed")
            raw_date = item.get("date")
            raw_ms = item.get("date_ms")
            try:
                session = datetime.strptime(str(raw_date), "%Y%m%d").date()
                timestamp_value = datetime.fromtimestamp(int(raw_ms) / 1000, MARKET_TIME_ZONE)
                timestamp_session = timestamp_value.date()
            except (TypeError, ValueError, OSError) as exc:
                raise FuyaoContractError(f"trading calendar row {index} has an invalid date") from exc
            if session != timestamp_session:
                raise FuyaoContractError(f"trading calendar row {index} has conflicting date evidence")
            if timestamp_value.time() != clock_time():
                raise FuyaoContractError(f"trading calendar row {index} is not Shanghai midnight")
            sessions.append(session)
        if sessions != sorted(set(sessions)):
            raise FuyaoContractError("trading calendar is not strictly ascending and unique")
        return tuple(sessions)

    def fetch_tickers(self, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
        cache_is_fresh = bool(
            self._ticker_cache is not None
            and self._ticker_cache_created_at is not None
            and self._monotonic() - self._ticker_cache_created_at < self.ticker_cache_ttl_seconds
        )
        if cache_is_fresh and not refresh:
            return dict(self._ticker_cache)
        limit = 10_000
        offset = 0
        result: dict[str, dict[str, Any]] = {}
        for _page in range(100):
            data = self._request_data(
                "/api/meta/tickers/list",
                params={"asset_type": "a-share", "limit": limit, "offset": offset},
            )
            items = data.get("item")
            if not isinstance(items, list):
                raise FuyaoContractError("ticker response is missing item rows")
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    raise FuyaoContractError(f"ticker row {offset + index} is malformed")
                normalized = dict(item)
                identity = self._validated_identity(normalized, context=f"ticker row {offset + index}")
                if identity in result:
                    raise FuyaoContractError(f"ticker response contains duplicate identity {identity}")
                result[identity] = normalized
            if len(items) < limit:
                if not result:
                    raise FuyaoContractError("ticker response has no A-share rows")
                self._ticker_cache = dict(result)
                self._ticker_cache_created_at = self._monotonic()
                return dict(result)
            offset += limit
        raise FuyaoContractError("ticker pagination exceeded the safety bound")

    def fetch_limit_pool(self, pool_type: str, as_of: date) -> FuyaoPoolResult:
        path = self._POOL_PATHS.get(pool_type)
        if path is None:
            raise ValueError(f"unsupported Fuyao pool type: {pool_type}")
        date_ms = int(datetime.combine(as_of, clock_time(), MARKET_TIME_ZONE).timestamp() * 1000)
        expected_total: int | None = None
        expected_pages: int | None = None
        all_rows: list[dict[str, Any]] = []
        expected_timestamp: int | None = None
        page = 1
        while True:
            data = self._request_data(
                path,
                params={"date_ms": date_ms, "page": page, "size": self._PAGE_SIZE},
            )
            pagination = data.get("pagination")
            items = data.get("item")
            if not isinstance(pagination, Mapping) or not isinstance(items, list):
                raise FuyaoContractError(f"{pool_type} response is missing pagination or item")
            try:
                timestamp = int(data["timestamp"])
                total = int(pagination["total"])
                pages = int(pagination["pages"])
                response_size = int(pagination["size"])
                response_page = int(pagination["page"])
            except (KeyError, TypeError, ValueError) as exc:
                raise FuyaoContractError(f"{pool_type} pagination is malformed") from exc
            calculated_pages = math.ceil(total / self._PAGE_SIZE) if total else 0
            empty_pages_valid = total == 0 and pages in {0, 1}
            if total < 0 or (pages != calculated_pages and not empty_pages_valid):
                raise FuyaoContractError(f"{pool_type} pagination total/pages conflict")
            if pages > self._MAX_POOL_PAGES:
                raise FuyaoContractError(f"{pool_type} pagination exceeds the safety bound")
            if response_size != self._PAGE_SIZE or response_page != page:
                raise FuyaoContractError(f"{pool_type} pagination echo does not match the request")
            if expected_total is None:
                expected_total, expected_pages = total, pages
            elif total != expected_total or pages != expected_pages:
                raise FuyaoContractError(f"{pool_type} pagination changed while fetching pages")
            expected_items = (
                0
                if total == 0
                else self._PAGE_SIZE
                if page < pages
                else total - self._PAGE_SIZE * (pages - 1)
            )
            if len(items) != expected_items:
                raise FuyaoContractError(
                    f"{pool_type} page {page} returned {len(items)} of {expected_items} expected rows"
                )
            if expected_timestamp is None:
                expected_timestamp = timestamp
            elif timestamp != expected_timestamp:
                raise FuyaoContractError(f"{pool_type} pages contain mixed snapshot timestamps")
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    raise FuyaoContractError(f"{pool_type} row {(page - 1) * self._PAGE_SIZE + index} is malformed")
                normalized = dict(item)
                self._validated_identity(normalized, context=f"{pool_type} row")
                all_rows.append(normalized)
            if total == 0 or page >= pages:
                break
            page += 1

        unique_rows: dict[str, dict[str, Any]] = {}
        for row in all_rows:
            unique_rows[str(row["thscode"]).upper()] = row
        if expected_total is None or len(unique_rows) != expected_total:
            raise FuyaoContractError(
                f"{pool_type} pagination incomplete after deduplication: "
                f"{len(unique_rows)} of {expected_total if expected_total is not None else 'unknown'}"
            )
        return FuyaoPoolResult(
            rows=tuple(unique_rows.values()),
            total=expected_total,
            pages=expected_pages or 0,
        )

    def fetch_limit_dataset(
        self,
        as_of: date,
        *,
        trading_days: tuple[date, ...] | None = None,
    ) -> FuyaoLimitDataset:
        sessions = trading_days if trading_days is not None else self.fetch_trading_days()
        if as_of not in sessions:
            raise FuyaoNonTradingDayError(f"{as_of.isoformat()} is not present in the Fuyao trading calendar")
        warnings: list[str] = []
        try:
            tickers = self.fetch_tickers()
        except FuyaoError as exc:
            tickers = {}
            warnings.append(f"Fuyao code-table enrichment unavailable: {exc}")
        pools = {
            pool_type: self.fetch_limit_pool(pool_type, as_of)
            for pool_type in ("limit_up", "failed_limit_up", "limit_down")
        }
        return FuyaoLimitDataset(
            as_of=as_of,
            pools=pools,
            tickers=tickers,
            warnings=tuple(warnings),
        )

    def _request_data(self, path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.require_configured()
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=dict(params or {}),
                    headers={"X-api-key": self.api_key},
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise FuyaoTransportError("Fuyao network request failed after retries") from exc

            status = int(getattr(response, "status_code", 0))
            if status == 429 or 500 <= status < 600:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise FuyaoTransportError(f"Fuyao HTTP {status} after retries")
            if status < 200 or status >= 300:
                raise FuyaoTransportError(f"Fuyao HTTP {status}")
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise FuyaoContractError("Fuyao response is not valid JSON") from exc
            if not isinstance(payload, Mapping):
                raise FuyaoContractError("Fuyao response envelope is malformed")
            try:
                code = int(payload.get("code"))
            except (TypeError, ValueError) as exc:
                raise FuyaoContractError("Fuyao response envelope has no valid code") from exc
            if code in self._RETRYABLE_ENVELOPE_CODES:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise FuyaoTransportError(f"Fuyao response code {code} after retries")
            if code in self._PERMISSION_CODES:
                raise FuyaoPermissionError(f"Fuyao authentication or permission denied (code={code})")
            if code != 0:
                raise FuyaoError(f"Fuyao request rejected (code={code})")
            data = payload.get("data")
            if not isinstance(data, Mapping):
                raise FuyaoContractError("Fuyao success envelope is missing data")
            return dict(data)
        raise AssertionError("unreachable retry loop")

    def _backoff(self, attempt: int) -> None:
        self._sleep(self.backoff_seconds * (2**attempt))

    @staticmethod
    def _validated_identity(row: Mapping[str, Any], *, context: str) -> str:
        identity = str(row.get("thscode") or "").strip().upper()
        match = _THSCODE_RE.fullmatch(identity)
        ticker = str(row.get("ticker") or "").strip()
        if match is None or ticker != match.group("ticker"):
            raise FuyaoContractError(f"{context} has an invalid standard security identity")
        return identity


__all__ = [
    "FUYAO_API_KEY_ENV",
    "FuyaoClient",
    "FuyaoConfigurationError",
    "FuyaoContractError",
    "FuyaoError",
    "FuyaoLimitDataset",
    "FuyaoNonTradingDayError",
    "FuyaoPermissionError",
    "FuyaoPoolResult",
    "FuyaoTransportError",
]
