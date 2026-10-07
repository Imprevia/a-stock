"""Offline-friendly Fuyao market-data capability adapters.

This module deliberately sits beside :mod:`fuyao` rather than changing the
limits client.  It provides a small request boundary and conservative
normalizers for the four datasets that are not yet part of the production
limits path.  Every adapter is fail-closed: fields that cannot be proved from
the response remain ``None`` and the result is marked ``insufficient`` or
``ineligible`` instead of being filled from another date.
"""

from __future__ import annotations

import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ....domain.analysis.calculations import Bar
from .request_gate import FuyaoRequestGate, GLOBAL_FUYAO_REQUEST_GATE

FUYAO_MARKET_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
FUYAO_MARKET_BASE_URL = "https://fuyao.aicubes.cn"

_IDENTITY_RE = re.compile(r"^(?P<ticker>\d{6})\.(?P<exchange>SH|SZ|BJ)$")
_THS_INDEX_RE = re.compile(r"^\d{6}\.TI$")
_SHANGHAI_ZONE = ZoneInfo("Asia/Shanghai")
_CODE_TO_IDENTITY = {
    "sh000001": "000001.SH",
    "sz399001": "399001.SZ",
    "sz399006": "399006.SZ",
    "sh000300": "000300.SH",
    "sh000905": "000905.SH",
}


class FuyaoMarketError(RuntimeError):
    """Base error with no request credential or response body in its message."""


class FuyaoMarketConfigurationError(FuyaoMarketError):
    pass


class FuyaoMarketPermissionError(FuyaoMarketError):
    pass


class FuyaoMarketRateLimitError(FuyaoMarketError):
    pass


class FuyaoMarketTransportError(FuyaoMarketError):
    pass


class FuyaoMarketContractError(FuyaoMarketError):
    pass


@dataclass(frozen=True)
class FuyaoMarketResult:
    """A dataset payload plus the quality envelope used by market snapshots."""

    payload: dict[str, Any]
    quality: dict[str, Any]
    status: str
    as_of: date
    observations: int
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result = dict(self.payload)
        result["quality"] = dict(self.quality)
        return result


@dataclass(frozen=True)
class FuyaoMarketResponse:
    data: dict[str, Any]
    status_code: int
    request_count: int


class FuyaoMarketClient:
    """Generic request layer with bounded retries and a request budget.

    The client intentionally accepts a requests-compatible session so tests
    can use fixed, redacted fixtures.  No request is made when the key is
    missing; callers can use the normalizers directly for offline probes.
    """

    _RETRYABLE_CODES = frozenset({4001, 5001, 5002, 5003})
    _SLOW_RETRY_CODES = frozenset({4001, 5003})
    _PERMISSION_CODES = frozenset({2001, 2003})

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 8.0,
        session: requests.Session | None = None,
        base_url: str = FUYAO_MARKET_BASE_URL,
        max_retries: int = 2,
        backoff_seconds: float = 0.2,
        slow_backoff_seconds: float = 2.0,
        min_request_interval_seconds: float = 0.5,
        request_budget: int = 80,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        request_gate: FuyaoRequestGate | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv(FUYAO_MARKET_API_KEY_ENV, "")).strip()
        self.timeout = max(0.1, float(timeout))
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.slow_backoff_seconds = max(self.backoff_seconds, float(slow_backoff_seconds))
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self.request_budget = max(1, int(request_budget))
        self._request_count = 0
        self._sleep = sleep
        self._request_gate = request_gate or (
            GLOBAL_FUYAO_REQUEST_GATE
            if sleep is time.sleep and monotonic is time.monotonic
            else FuyaoRequestGate(
                min_interval_seconds=self.min_request_interval_seconds,
                sleep=sleep,
                monotonic=monotonic,
            )
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def request_count(self) -> int:
        return self._request_count

    def require_configured(self) -> None:
        if not self.configured:
            raise FuyaoMarketConfigurationError(f"{FUYAO_MARKET_API_KEY_ENV} is required")

    def request(self, path: str, *, params: Mapping[str, Any] | None = None) -> FuyaoMarketResponse:
        self.require_configured()
        if self._request_count >= self.request_budget:
            raise FuyaoMarketRateLimitError("Fuyao request budget exceeded")
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            if self._request_count >= self.request_budget:
                raise FuyaoMarketRateLimitError("Fuyao request budget exceeded")
            self._request_count += 1
            try:
                self._request_gate.wait()
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
                raise FuyaoMarketTransportError("Fuyao network request failed after retries") from exc
            status = int(getattr(response, "status_code", 0))
            if status == 429:
                if attempt < self.max_retries:
                    self._backoff(attempt, slow=True)
                    continue
                raise FuyaoMarketRateLimitError(
                    f"Fuyao HTTP {self._http_error_detail(response, status)} after retries"
                )
            if 500 <= status < 600:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise FuyaoMarketTransportError(
                    f"Fuyao {self._http_error_detail(response, status)} after retries"
                )
            if status < 200 or status >= 300:
                detail = self._http_error_detail(response, status)
                if status in {401, 403}:
                    raise FuyaoMarketPermissionError(f"Fuyao authentication or permission denied ({detail})")
                raise FuyaoMarketTransportError(f"Fuyao {detail}")
            try:
                envelope = response.json()
            except (TypeError, ValueError) as exc:
                raise FuyaoMarketContractError("Fuyao response is not valid JSON") from exc
            if not isinstance(envelope, Mapping):
                raise FuyaoMarketContractError("Fuyao response envelope is malformed")
            try:
                code = int(envelope.get("code", envelope.get("status", 0)))
            except (TypeError, ValueError) as exc:
                raise FuyaoMarketContractError("Fuyao response envelope has no valid code") from exc
            if code in self._RETRYABLE_CODES:
                if attempt < self.max_retries:
                    self._backoff(attempt, slow=code in self._SLOW_RETRY_CODES)
                    continue
                raise FuyaoMarketTransportError(
                    f"Fuyao response {self._envelope_error_detail(envelope, code)} after retries"
                )
            if code in self._PERMISSION_CODES:
                raise FuyaoMarketPermissionError(
                    f"Fuyao authentication or permission denied ({self._envelope_error_detail(envelope, code)})"
                )
            if code not in {0, 200}:
                raise FuyaoMarketError(f"Fuyao request rejected ({self._envelope_error_detail(envelope, code)})")
            data = envelope.get("data", envelope.get("result"))
            if not isinstance(data, Mapping):
                raise FuyaoMarketContractError("Fuyao success envelope is missing data")
            return FuyaoMarketResponse(dict(data), status, self._request_count)
        raise AssertionError("unreachable retry loop")

    def _backoff(self, attempt: int, *, slow: bool = False) -> None:
        base = self.slow_backoff_seconds if slow else self.backoff_seconds
        self._sleep(base * (2**attempt))

    def _safe_text(self, value: Any, *, max_length: int = 160) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        if self.api_key:
            text = text.replace(self.api_key, "<redacted>")
        if len(text) > max_length:
            text = f"{text[:max_length]}..."
        return text or None

    def _envelope_error_detail(self, payload: Mapping[str, Any], code: int) -> str:
        parts = [f"code={code}"]
        message = self._safe_text(payload.get("message"))
        request_id = self._safe_text(payload.get("request_id"), max_length=80)
        if message:
            parts.append(f"message={message}")
        if request_id:
            parts.append(f"request_id={request_id}")
        return ", ".join(parts)

    def _http_error_detail(self, response: Any, status: int) -> str:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            return f"HTTP {status}"
        if not isinstance(payload, Mapping):
            return f"HTTP {status}"
        try:
            code = int(payload.get("code"))
        except (TypeError, ValueError):
            parts = [f"HTTP {status}"]
            message = self._safe_text(payload.get("message"))
            request_id = self._safe_text(payload.get("request_id"), max_length=80)
            if message:
                parts.append(f"message={message}")
            if request_id:
                parts.append(f"request_id={request_id}")
            return f"HTTP {status} ({', '.join(parts[1:])})" if len(parts) > 1 else parts[0]
        return f"HTTP {status} ({self._envelope_error_detail(payload, code)})"


class FuyaoMarketAdapter:
    """Normalize fixture/API responses into existing dashboard contracts."""

    INDEX_CODES = dict(_CODE_TO_IDENTITY)

    def __init__(self, client: FuyaoMarketClient | None = None, *, source_revision: str = "fuyao-market-v2") -> None:
        self.client = client or FuyaoMarketClient()
        self.source_revision = source_revision

    # ---- generic helpers -------------------------------------------------
    @staticmethod
    def _value(row: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in row and row[name] not in (None, "", "-"):
                return row[name]
        return None

    @classmethod
    def _float(cls, row: Mapping[str, Any], *names: str) -> float | None:
        value = cls._value(row, *names)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _int(cls, row: Mapping[str, Any], *names: str) -> int | None:
        value = cls._value(row, *names)
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _text(cls, row: Mapping[str, Any], *names: str) -> str | None:
        value = cls._value(row, *names)
        return None if value is None else str(value).strip() or None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if value in (None, "", "-"):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt).date()
            except ValueError:
                continue
        try:
            number = float(text)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, _SHANGHAI_ZONE).date()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @classmethod
    def _row_date(cls, row: Mapping[str, Any]) -> date | None:
        timestamp = cls._value(row, "date_ms", "dateMs")
        if timestamp is not None:
            return cls._timestamp_date(timestamp)
        return cls._parse_date(cls._value(row, "date", "trade_date", "tradeDate", "as_of", "asOf", "timestamp"))

    @classmethod
    def _identity(cls, row: Mapping[str, Any]) -> str | None:
        raw = cls._text(row, "thscode", "ts_code", "security", "identity")
        if raw and _IDENTITY_RE.fullmatch(raw.upper()):
            return raw.upper()
        ticker = cls._text(row, "ticker", "code", "symbol", "f12")
        exchange = cls._text(row, "exchange", "market")
        if ticker and exchange:
            candidate = f"{ticker.zfill(6)}.{exchange.upper()[:2]}"
            if _IDENTITY_RE.fullmatch(candidate):
                return candidate
        return None

    @staticmethod
    def _quality(
        dataset: str,
        status: str,
        observations: int,
        as_of: date,
        warnings: Sequence[str],
        provider_revision: str = "fuyao-market-v2",
    ) -> dict[str, Any]:
        warning_list = list(dict.fromkeys(str(item) for item in warnings if item))
        return {
            "dataset": dataset,
            "source": "fuyao",
            "provider": "fuyao",
            "providerRevision": provider_revision,
            "status": status,
            "observations": observations,
            "asOf": as_of.isoformat(),
            "warning": "; ".join(warning_list) if warning_list else None,
            "warnings": warning_list,
        }

    @classmethod
    def _result(
        cls,
        dataset: str,
        payload: dict[str, Any],
        *,
        status: str,
        as_of: date,
        observations: int,
        warnings: Sequence[str] = (),
        provider_revision: str = "fuyao-market-v2",
        quality_extra: Mapping[str, Any] | None = None,
    ) -> FuyaoMarketResult:
        quality = cls._quality(dataset, status, observations, as_of, warnings, provider_revision)
        if quality_extra:
            quality.update(dict(quality_extra))
        return FuyaoMarketResult(payload, quality, status, as_of, observations, tuple(quality["warnings"]))

    @classmethod
    def _date_guard(cls, rows: Sequence[Mapping[str, Any]], as_of: date) -> tuple[bool, list[str]]:
        dates = {item for row in rows if (item := cls._row_date(row)) is not None}
        if not dates:
            return False, ["response does not prove an exact asOf date"]
        if dates != {as_of}:
            return False, [f"response date mismatch: requested {as_of.isoformat()}, observed {sorted(dates)}"]
        return True, []

    @staticmethod
    def _rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = data.get("item", data.get("rows", data.get("diff", data.get("klines", []))))
        if isinstance(raw, Mapping):
            raw = list(raw.values())
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, Mapping)]

    # ---- core ------------------------------------------------------------
    def normalize_core(
        self,
        rows_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
        as_of: date,
        *,
        quotes_by_code: Mapping[str, Mapping[str, Any]] | None = None,
        min_bars: int = 280,
    ) -> dict[str, FuyaoMarketResult]:
        result: dict[str, FuyaoMarketResult] = {}
        for code, rows in rows_by_code.items():
            canonical = str(code).lower()
            expected_identity = self.INDEX_CODES.get(canonical, canonical.upper())
            bars: list[Bar] = []
            warnings: list[str] = []
            response_identities = {
                identity
                for row in rows
                if (identity := self._identity(row)) is not None
            }
            if response_identities and response_identities != {expected_identity}:
                warnings.append(
                    f"index identity mismatch: expected {expected_identity}, observed {sorted(response_identities)}"
                )
            seen_dates: set[date] = set()
            for row in rows:
                day = self._row_date(row)
                opened = self._float(row, "open", "open_price", "o")
                close = self._float(row, "close", "close_price", "c")
                high = self._float(row, "high", "high_price", "h")
                low = self._float(row, "low", "low_price", "l")
                amount = self._float(row, "amount", "turnover", "成交额", "amt")
                if day is None or None in {opened, close, high, low, amount}:
                    continue
                if day in seen_dates or not (low <= min(opened, close) <= high and low <= max(opened, close) <= high):
                    continue
                seen_dates.add(day)
                bars.append(Bar(day, opened, close, high, low, amount))
            bars.sort(key=lambda item: item.date)
            valid_dates = {bar.date for bar in bars}
            date_warnings: list[str] = []
            if not valid_dates:
                date_ok = False
                date_warnings.append("response does not prove an exact asOf date with a complete OHLC/turnover bar")
            else:
                latest_date = max(valid_dates)
                date_ok = latest_date == as_of and not any(day > as_of for day in valid_dates)
                if latest_date != as_of:
                    date_warnings.append(
                        f"response date mismatch: requested {as_of.isoformat()}, observed latest valid {latest_date.isoformat()}"
                    )
                if any(day > as_of for day in valid_dates):
                    date_warnings.append("response contains valid bars after requested asOf")
            warnings.extend(date_warnings)
            quote = (quotes_by_code or {}).get(canonical)
            quote_price = self._float(quote, "price", "close", "last") if quote else None
            if quote is not None and quote_price is None:
                warnings.append(f"index {expected_identity} quote has no usable price")
            if quote_price is not None and bars:
                deviation = abs(bars[-1].close - quote_price) / max(abs(quote_price), 1e-12)
                if deviation > 0.05:
                    warnings.append(
                        f"index {expected_identity} close does not match the independent quote"
                    )
            identity_ok = not response_identities or response_identities == {expected_identity}
            price_ok = quote_price is None or (bars and abs(bars[-1].close - quote_price) / max(abs(quote_price), 1e-12) <= 0.05)
            if not date_ok or not identity_ok or not price_ok:
                status = "insufficient"
            elif len(bars) < min_bars:
                status = "insufficient"
                warnings.append(f"index {expected_identity} returned {len(bars)} bars; {min_bars} required")
            else:
                status = "ok"
            # The historical contract does not expose a separate percentage
            # change field.  Derive it from the final two validated closes so
            # shadow comparison can use the same date-local fact as the
            # formal provider without consulting a live quote endpoint.
            change_pct = None
            if len(bars) >= 2 and bars[-2].close:
                change_pct = round((bars[-1].close / bars[-2].close - 1.0) * 100.0, 2)
            result[canonical] = self._result(
                "core",
                {
                    "code": canonical,
                    "identity": expected_identity,
                    "bars": bars,
                    "changePct": change_pct,
                    # Fuyao reports turnover directly.  Keep this evidence
                    # explicit because the Sina fallback estimates historical
                    # turnover from a current Tencent quote.
                    "amountEvidence": "direct-turnover",
                },
                status=status,
                as_of=as_of,
                observations=len(bars),
                warnings=warnings,
                provider_revision=self.source_revision,
                quality_extra={
                    "endpoint": "/api/a-share-index/prices/historical",
                    "dateEvidence": {
                        "requested": as_of.isoformat(),
                        "validBars": sorted(day.isoformat() for day in valid_dates),
                        "lastValid": max(valid_dates).isoformat() if valid_dates else None,
                    },
                    "historyWindow": {"observations": len(bars), "minimum": min_bars},
                    "amountEvidence": "direct-turnover",
                },
            )
        return result

    def fetch_core(
        self,
        as_of: date,
        *,
        codes: Sequence[str] | None = None,
        limit: int = 280,
        quotes_by_code: Mapping[str, Mapping[str, Any]] | None = None,
        lookback_days: int = 730,
    ) -> dict[str, FuyaoMarketResult]:
        selected = tuple(codes or self.INDEX_CODES)
        required_bars = max(280, int(limit))
        rows: dict[str, list[dict[str, Any]]] = {}
        end = int(datetime.combine(as_of, datetime.min.time(), _SHANGHAI_ZONE).timestamp() * 1000)
        start_date = as_of - timedelta(days=max(lookback_days, 400))
        start = int(datetime.combine(start_date, datetime.min.time(), _SHANGHAI_ZONE).timestamp() * 1000)
        for code in selected:
            identity = self.INDEX_CODES.get(code, code)
            try:
                response = self.client.request(
                    "/api/a-share-index/prices/historical",
                    params={"thscode": identity, "interval": "1d", "start": start, "end": end},
                )
                response_identity = self._text(response.data, "thscode", "identity")
                if response_identity and response_identity.upper() != identity.upper():
                    raise FuyaoMarketContractError(
                        f"index response identity mismatch: requested {identity}, observed {response_identity}"
                    )
                rows[code] = self._rows(response.data)
            except FuyaoMarketError as exc:
                # Keep the other four index requests useful.  Collection can
                # then fall back only for this index and retain the warning.
                rows[code] = []
                result = self._result(
                    "core",
                    {"code": str(code).lower(), "identity": identity, "bars": []},
                    status="insufficient",
                    as_of=as_of,
                    observations=0,
                    warnings=[str(exc)],
                    provider_revision=self.source_revision,
                    quality_extra={
                        "endpoint": "/api/a-share-index/prices/historical",
                        "dateEvidence": {"requested": as_of.isoformat(), "lastValid": None},
                        "historyWindow": {"observations": 0, "minimum": required_bars},
                    },
                )
                # Store a sentinel row outside normalize_core's input shape;
                # it is replaced below after all requests complete.
                rows[code] = [{"__fuyao_error_result__": result}]
        normalized = self.normalize_core(
            {
                code: [row for row in values if "__fuyao_error_result__" not in row]
                for code, values in rows.items()
            },
            as_of,
            quotes_by_code=quotes_by_code,
            min_bars=required_bars,
        )
        for code, values in rows.items():
            for row in values:
                error_result = row.get("__fuyao_error_result__")
                if isinstance(error_result, FuyaoMarketResult):
                    normalized[code] = error_result
                    break
        return normalized

    # ---- breadth ---------------------------------------------------------
    def normalize_breadth(
        self,
        pages: Sequence[Mapping[str, Any]],
        as_of: date,
        *,
        expected_total: int | None = None,
    ) -> FuyaoMarketResult:
        if pages and not any(isinstance(page, Mapping) and "pagination" in page for page in pages):
            return self._normalize_snapshot_breadth(pages, as_of, expected_total=expected_total)
        rows: list[dict[str, Any]] = []
        totals: set[int] = set()
        identities: set[str] = set()
        warnings: list[str] = []
        for page in pages:
            pagination = page.get("pagination")
            if isinstance(pagination, Mapping):
                total = self._int(pagination, "total", "count")
                if total is not None:
                    totals.add(total)
            page_rows = self._rows(page)
            for row in page_rows:
                identity = self._identity(row)
                if identity is None or identity in identities:
                    warnings.append("missing or duplicate normalized security identity")
                    continue
                identities.add(identity)
                rows.append(row)
        date_ok, date_warnings = self._date_guard(rows, as_of)
        warnings.extend(date_warnings)
        pagination_stable = len(totals) <= 1
        if not pagination_stable:
            warnings.append("pagination total changed between pages")
        total = expected_total if expected_total is not None else (next(iter(totals)) if totals else None)
        if total is None or len(rows) < total:
            warnings.append("full market pagination is not proven")
        returns = [self._float(row, "change_pct", "changePct", "pct_chg", "f3") for row in rows]
        valid = [value for value in returns if value is not None]
        if not date_ok or not pagination_stable or total is None or len(rows) < total:
            status = "insufficient"
        elif not valid:
            status = "ineligible"
            warnings.append("full market snapshot has no valid change_pct values")
        else:
            status = "ok"
        advance = sum(value > 0 for value in valid)
        decline = sum(value < 0 for value in valid)
        flat = len(valid) - advance - decline
        middle = float(median(valid)) if valid else None
        payload = {
            "advanceCount": advance if valid else None,
            "declineCount": decline if valid else None,
            "flatCount": flat if valid else None,
            "validCount": len(valid) if valid else None,
            "advanceRatio": round(advance / len(valid), 4) if valid else None,
            "medianReturn": round(middle, 4) if middle is not None else None,
            "state": "多数上涨" if valid and advance / len(valid) > 0.5 and middle > 0 else "多数下跌" if valid and advance / len(valid) < 0.5 and middle < 0 else "涨跌分化" if valid else "insufficient",
        }
        return self._result("market-breadth", payload, status=status, as_of=as_of, observations=len(valid), warnings=warnings)

    def _normalize_snapshot_breadth(
        self,
        pages: Sequence[Mapping[str, Any]],
        as_of: date,
        *,
        expected_total: int | None = None,
    ) -> FuyaoMarketResult:
        rows: list[dict[str, Any]] = []
        totals: set[int] = set()
        timestamps: set[int] = set()
        invalid_total_pages = 0
        invalid_timestamp_pages = 0
        identities: set[str] = set()
        warnings: list[str] = []
        for page in pages:
            if not isinstance(page, Mapping):
                warnings.append("snapshot page is malformed")
                continue
            try:
                total = int(page["total"])
            except (KeyError, TypeError, ValueError):
                total = -1
            if total >= 0:
                totals.add(total)
            else:
                invalid_total_pages += 1
            raw_timestamp = page.get("timestamp")
            try:
                timestamp = int(raw_timestamp)
            except (TypeError, ValueError):
                timestamp = 0
            if timestamp > 0:
                timestamps.add(timestamp)
            else:
                invalid_timestamp_pages += 1
            page_rows = self._rows(page)
            for row in page_rows:
                identity = self._identity(row)
                if identity is None:
                    warnings.append("snapshot row lacks a valid standard security identity")
                    continue
                if identity in identities:
                    warnings.append(f"snapshot contains duplicate identity {identity}")
                    continue
                identities.add(identity)
                rows.append(row)

        total = expected_total if expected_total is not None else (next(iter(totals)) if len(totals) == 1 else None)
        timestamp_dates = {self._timestamp_date(value) for value in timestamps}
        timestamp_dates.discard(None)
        if not timestamps:
            warnings.append("snapshot has no usable timestamp date evidence")
        elif timestamp_dates != {as_of}:
            warnings.append(
                f"snapshot date mismatch: requested {as_of.isoformat()}, observed "
                f"{sorted(value.isoformat() for value in timestamp_dates) or ['missing']}"
            )
        if len(totals) > 1:
            warnings.append("snapshot total changed between pages")
        if len(timestamps) > 1:
            # Fuyao documents ``timestamp`` as the latest upstream-valid
            # time for each page.  Pages can therefore legitimately differ
            # by a few seconds while still proving the same Shanghai trading
            # date.  Preserve that drift as evidence, but reject a date drift
            # below rather than treating a page-local timestamp as a global
            # snapshot timestamp.
            warnings.append("snapshot timestamps differ between pages; Shanghai date evidence is stable")
        if invalid_total_pages:
            warnings.append("snapshot page is missing a valid total")
        if invalid_timestamp_pages:
            warnings.append("snapshot page is missing a valid timestamp")
        if total is None or len(rows) != total:
            warnings.append("full market pagination is not proven")
        returns = [self._float(row, "price_change_ratio_pct", "change_pct", "changePct") for row in rows]
        valid = [value for value in returns if value is not None and math.isfinite(value)]
        missing_change_pct = len(rows) - len(valid)
        if missing_change_pct:
            warnings.append(
                f"snapshot rows missing valid price_change_ratio_pct: {missing_change_pct}"
            )
        advance = sum(value > 0 for value in valid)
        decline = sum(value < 0 for value in valid)
        flat = sum(value == 0 for value in valid)
        middle = float(median(valid)) if valid else None
        exact = (
            timestamp_dates == {as_of}
            and len(totals) == 1
            and bool(timestamps)
            and invalid_total_pages == 0
            and invalid_timestamp_pages == 0
            and total is not None
            and len(rows) == total
        )
        status = "ok" if exact and valid and missing_change_pct == 0 else (
            "partial" if exact and valid else "insufficient"
        )
        if not valid:
            warnings.append("snapshot has no valid price_change_ratio_pct values")
        payload = {
            "advanceCount": advance if valid else None,
            "declineCount": decline if valid else None,
            "flatCount": flat if valid else None,
            "validCount": len(valid) if valid else None,
            "advanceRatio": round(advance / len(valid), 4) if valid else None,
            "medianReturn": round(middle, 4) if middle is not None else None,
            "state": "多数上涨" if valid and advance / len(valid) > 0.5 and middle > 0 else "多数下跌" if valid and advance / len(valid) < 0.5 and middle < 0 else "涨跌分化" if valid else "insufficient",
        }
        return self._result(
            "market-breadth",
            payload,
            status=status,
            as_of=as_of,
            observations=len(valid),
            warnings=warnings,
            provider_revision=self.source_revision,
            quality_extra={
                "endpoint": "/api/a-share/prices/snapshot",
                "dateCapability": "latest-only",
                "pagination": {"total": total, "pages": len(pages), "observed": len(rows)},
                "timestamps": sorted(timestamps),
                "rawTimestamps": sorted(timestamps),
                "minTimestamp": min(timestamps) if timestamps else None,
                "maxTimestamp": max(timestamps) if timestamps else None,
                "timestampStable": bool(timestamps) and invalid_timestamp_pages == 0 and timestamp_dates == {as_of},
                "timestampExactStable": len(timestamps) == 1 and invalid_timestamp_pages == 0,
                "timestampDateStable": timestamp_dates == {as_of} and invalid_timestamp_pages == 0,
                "timestampDateConsistent": timestamp_dates == {as_of} and invalid_timestamp_pages == 0,
                "timestampSpanMs": (
                    max(self._timestamp_millis(value) for value in timestamps)
                    - min(self._timestamp_millis(value) for value in timestamps)
                    if timestamps
                    else None
                ),
                "fieldCoverage": {
                    "rows": len(rows),
                    "priceChangeRatioPct": len(valid),
                    "missingPriceChangeRatioPct": missing_change_pct,
                },
            },
        )

    def fetch_breadth(
        self,
        as_of: date,
        *,
        pages: Sequence[Mapping[str, Any]] | None = None,
        page_size: int = 500,
        max_pages: int = 50,
    ) -> FuyaoMarketResult:
        if pages is None:
            today = datetime.now(_SHANGHAI_ZONE).date()
            if as_of != today:
                return self._result(
                    "market-breadth",
                    {"state": "insufficient", "advanceCount": None, "declineCount": None, "flatCount": None, "validCount": None, "advanceRatio": None, "medianReturn": None},
                    status="insufficient",
                    as_of=as_of,
                    observations=0,
                    warnings=["Fuyao prices snapshot is latest-only; historical dates require a local exact-date snapshot"],
                    provider_revision=self.source_revision,
                    quality_extra={
                        "endpoint": "/api/a-share/prices/snapshot",
                        "dateCapability": "latest-only",
                    },
                )
            page_size = max(1, int(page_size))
            pages_list: list[Mapping[str, Any]] = []
            offset = 0
            expected_total: int | None = None
            for _ in range(max(1, int(max_pages))):
                response = self.client.request(
                    "/api/a-share/prices/snapshot",
                    params={"limit": page_size, "offset": offset},
                )
                data = response.data
                pages_list.append(data)
                try:
                    total = int(data["total"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise FuyaoMarketContractError("snapshot response is missing a valid total") from exc
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise FuyaoMarketContractError("snapshot total changed while fetching pages")
                items = self._rows(data)
                if offset + len(items) < total:
                    if not items:
                        raise FuyaoMarketContractError("snapshot pagination stopped before total coverage")
                    offset += len(items)
                    continue
                break
            else:
                raise FuyaoMarketContractError("Fuyao snapshot pagination exceeded the safety bound")
            pages = tuple(pages_list)
        return self.normalize_breadth(pages, as_of)

    # ---- active direction -----------------------------------------------
    def normalize_active_direction(
        self,
        rows: Sequence[Mapping[str, Any]],
        as_of: date,
        *,
        ordering_proven: bool = False,
        full_market_proven: bool = False,
        minimum_rows: int = 30,
    ) -> FuyaoMarketResult:
        date_ok, warnings = self._date_guard(rows, as_of)
        normalized: list[dict[str, Any]] = []
        identities: set[str] = set()
        for row in rows:
            identity = self._identity(row)
            name = self._text(row, "name", "security_name", "f14")
            amount = self._float(row, "amount", "turnover", "f6")
            if identity is None or identity in identities or name is None or amount is None:
                warnings.append("active direction row is missing identity, name or amount")
                continue
            identities.add(identity)
            normalized.append({"row": row, "identity": identity, "name": name, "amount": amount})
        amounts = [item["amount"] for item in normalized]
        if any(amounts[index] < amounts[index + 1] for index in range(len(amounts) - 1)):
            warnings.append("response is not sorted by descending amount")
        if not ordering_proven and not full_market_proven:
            warnings.append("server-side amount ordering or a complete market download is not proven")
        if len(normalized) < minimum_rows:
            warnings.append(f"active direction requires at least {minimum_rows} complete rows")
        status = (
            "ok"
            if date_ok
            and len(normalized) >= minimum_rows
            and (ordering_proven or full_market_proven)
            and not any("not sorted" in item for item in warnings)
            else "ineligible"
        )
        top = normalized[:minimum_rows]
        stocks: list[dict[str, Any]] = []
        industries = Counter()
        for item in top:
            row = item["row"]
            industry = self._text(row, "industry", "industry_name", "f100")
            if industry:
                industries[industry] += 1
            close = self._float(row, "close", "f2")
            high = self._float(row, "high", "f15")
            low = self._float(row, "low", "f16")
            position = (close - low) / (high - low) if None not in (close, high, low) and high > low else None
            stocks.append({"code": item["identity"], "name": item["name"], "industry": industry, "changePct": self._float(row, "change_pct", "changePct", "f3"), "amount": item["amount"], "closePosition": round(max(0.0, min(1.0, position)), 4) if position is not None else None})
        cluster, count = industries.most_common(1)[0] if industries else (None, 0)
        payload = {"state": "candidate" if count >= 3 else "unverified", "summary": f"成交额前30中 {cluster} 有 {count} 只" if cluster else "成交额前30未形成行业聚集线索", "topStocks": stocks}
        return self._result("active-direction", payload, status=status, as_of=as_of, observations=len(top), warnings=warnings)

    def fetch_active_direction(
        self,
        as_of: date,
        *,
        rows: Sequence[Mapping[str, Any]] | None = None,
        ordering_proven: bool = False,
        full_market_proven: bool = False,
    ) -> FuyaoMarketResult:
        if rows is None:
            # The documented v2 snapshot has no server-side turnover ordering
            # or stock-name fields required by this dataset.  Keep the
            # normalizer available for offline evidence, but never call the
            # retired v1 endpoint or present it as a cutover candidate.
            return self._result(
                "active-direction",
                {"state": "unverified", "summary": "activeDirection remains on the Eastmoney/TDX route", "topStocks": []},
                status="ineligible",
                as_of=as_of,
                observations=0,
                warnings=["Fuyao activeDirection endpoint is not part of the v2 cutover; existing Eastmoney/TDX route remains authoritative"],
                provider_revision=self.source_revision,
                quality_extra={"dateCapability": "not-selected", "cutover": False},
            )
        return self.normalize_active_direction(
            rows,
            as_of,
            ordering_proven=ordering_proven,
            full_market_proven=full_market_proven,
        )

    # ---- sectors ---------------------------------------------------------
    SECTOR_CALENDAR_ENDPOINT = "/api/a-share/calendar/trading-days"
    SECTOR_CATALOG_ENDPOINT = "/api/a-share-index/catalog/ths-index-list"
    SECTOR_SNAPSHOT_ENDPOINT = "/api/a-share-index/prices/snapshot"
    SECTOR_SNAPSHOT_BATCH_SIZE = 80
    SECTOR_UNSUPPORTED_FIELDS = ("mainNet", "mainNetPct", "upCount", "downCount", "leader")

    @staticmethod
    def _timestamp_date(value: Any) -> date | None:
        """Convert a provider millisecond/second timestamp to Shanghai date."""

        if value in (None, "", "-"):
            return None
        try:
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, _SHANGHAI_ZONE).date()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _timestamp_millis(value: Any) -> int:
        """Normalize provider seconds/milliseconds for drift evidence."""

        number = float(value)
        if abs(number) < 10_000_000_000:
            number *= 1000
        return int(number)

    @classmethod
    def _calendar_dates(cls, calendar: Mapping[str, Any]) -> tuple[set[date], list[str]]:
        dates: set[date] = set()
        warnings: list[str] = []
        for row in cls._rows(calendar):
            parsed = cls._parse_date(cls._value(row, "date", "trade_date", "tradeDate"))
            if parsed is None:
                parsed = cls._timestamp_date(cls._value(row, "date_ms", "dateMs", "timestamp"))
            if parsed is not None:
                dates.add(parsed)
        if not dates:
            warnings.append("sector trading calendar has no usable dates")
        return dates, warnings

    @classmethod
    def _sector_catalog(
        cls,
        catalog: Mapping[str, Any],
    ) -> tuple[dict[str, str], list[str]]:
        """Return a unique THS index identity -> display name mapping."""

        names: dict[str, str] = {}
        warnings: list[str] = []
        for row in cls._rows(catalog):
            code = cls._text(row, "thscode", "ths_code", "code")
            name = cls._text(row, "name", "index_name", "industry_name")
            if not code or not _THS_INDEX_RE.fullmatch(code.upper()) or not name:
                warnings.append("sector catalog row lacks a valid thscode or name")
                continue
            code = code.upper()
            if code in names:
                warnings.append(f"sector catalog contains duplicate identity {code}")
                continue
            names[code] = name
        if not names:
            warnings.append("sector catalog is empty")
        return names, warnings

    @classmethod
    def _snapshot_batches(
        cls,
        batches: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], set[Any], list[str], int]:
        """Flatten snapshot batches while retaining date-bearing evidence.

        Fuyao documents ``data.timestamp`` as the response/data timestamp.
        Separate requests therefore commonly have different millisecond
        values even when they belong to the same Shanghai trading date.  Keep
        the raw values for audit, but validate date consistency separately.
        The returned count lets callers reject a batch that omitted its
        timestamp instead of treating the remaining pages as sufficient
        evidence.
        """

        if isinstance(batches, Mapping):
            # A single ``data`` object is convenient for fixture callers.
            batches = (batches,)
        rows: list[dict[str, Any]] = []
        timestamps: set[Any] = set()
        warnings: list[str] = []
        timestamp_count = 0
        for batch in batches:
            if not isinstance(batch, Mapping):
                warnings.append("sector snapshot batch is malformed")
                continue
            timestamp = batch.get("timestamp")
            if timestamp in (None, "", "-"):
                warnings.append("sector snapshot batch has no timestamp")
            else:
                # Keep the raw value for exact batch consistency while still
                # allowing numeric strings from JSON fixtures.  Validation
                # below compares Shanghai dates, not raw response times.
                try:
                    timestamps.add(int(float(timestamp)))
                except (TypeError, ValueError):
                    timestamps.add(str(timestamp))
                timestamp_count += 1
            rows.extend(cls._rows(batch))
        if not rows:
            warnings.append("sector snapshot is empty")
        return rows, timestamps, warnings, timestamp_count

    def normalize_sector_index_data(
        self,
        calendar: Mapping[str, Any],
        catalog: Mapping[str, Any],
        snapshots: Sequence[Mapping[str, Any]] | Mapping[str, Any],
        as_of: date,
    ) -> FuyaoMarketResult:
        """Validate and normalize the documented THS industry API combination.

        The provider exposes only index identity, name (from the catalog),
        percentage change and turnover.  Unsupported ``SectorRow`` fields are
        deliberately kept as ``None`` rather than inferred from constituents.
        """

        warnings: list[str] = []
        calendar_dates, calendar_warnings = self._calendar_dates(calendar)
        warnings.extend(calendar_warnings)
        if as_of not in calendar_dates:
            warnings.append(f"sector requested date {as_of.isoformat()} is not a Shanghai trading day")

        catalog_by_code, catalog_warnings = self._sector_catalog(catalog)
        warnings.extend(catalog_warnings)
        catalog_integrity = not any(
            "catalog row lacks" in warning or "catalog contains duplicate" in warning
            for warning in catalog_warnings
        )
        snapshot_rows, timestamps, snapshot_warnings, timestamp_count = self._snapshot_batches(snapshots)
        warnings.extend(snapshot_warnings)

        timestamp_dates = {self._timestamp_date(value) for value in timestamps}
        timestamp_dates.discard(None)
        if not timestamps:
            warnings.append("sector snapshot date evidence is missing")
        batch_count = len(snapshots) if isinstance(snapshots, Sequence) and not isinstance(snapshots, Mapping) else 1
        if timestamp_count != batch_count:
            warnings.append(
                f"sector snapshot timestamp missing for {batch_count - timestamp_count} batch(es)"
            )
        elif len(timestamp_dates) > 1:
            warnings.append("sector snapshot batch timestamps map to different Shanghai dates")
        if timestamp_dates != {as_of}:
            observed = ", ".join(sorted(value.isoformat() for value in timestamp_dates)) or "missing"
            warnings.append(
                f"sector snapshot timestamp date mismatch: requested {as_of.isoformat()}, observed {observed}"
            )

        snapshot_by_code: dict[str, dict[str, Any]] = {}
        duplicate_snapshot = False
        for row in snapshot_rows:
            code = self._text(row, "thscode", "ths_code", "code")
            if not code or not _THS_INDEX_RE.fullmatch(code.upper()):
                warnings.append("sector snapshot row lacks a valid thscode")
                continue
            code = code.upper()
            if code in snapshot_by_code:
                duplicate_snapshot = True
                continue
            snapshot_by_code[code] = row
        if duplicate_snapshot:
            warnings.append("sector snapshot contains duplicate thscode identities")

        missing_codes = sorted(set(catalog_by_code) - set(snapshot_by_code))
        extra_codes = sorted(set(snapshot_by_code) - set(catalog_by_code))
        if missing_codes:
            warnings.append(
                f"sector snapshot coverage is incomplete: {len(missing_codes)} of {len(catalog_by_code)} catalog identities missing"
            )
        if extra_codes:
            warnings.append(f"sector snapshot contains {len(extra_codes)} identities absent from catalog")

        normalized: list[dict[str, Any]] = []
        missing_required = 0
        for code, name in catalog_by_code.items():
            row = snapshot_by_code.get(code)
            if row is None:
                continue
            change = self._float(row, "price_change_ratio_pct", "change_pct", "changePct", "f3")
            amount = self._float(row, "turnover", "amount", "f6")
            if (
                change is None
                or amount is None
                or not math.isfinite(change)
                or not math.isfinite(amount)
            ):
                missing_required += 1
                continue
            normalized.append(
                {
                    "rank": 0,
                    "code": code,
                    "name": name,
                    "changePct": change,
                    "amount": amount,
                    "mainNet": None,
                    "mainNetPct": None,
                    "upCount": None,
                    "downCount": None,
                    "leader": None,
                }
            )
        valid_snapshot_rows = len(normalized)
        if missing_required:
            warnings.append(
                f"sector snapshot rows missing required changePct or amount fields: {missing_required}"
            )
        normalized.sort(key=lambda row: (-float(row["changePct"]), str(row["code"])))
        normalized = normalized[:10]
        for rank, row in enumerate(normalized, start=1):
            row["rank"] = rank
        if normalized:
            warnings.append(
                "sector provider fields unavailable: " + ", ".join(self.SECTOR_UNSUPPORTED_FIELDS)
            )

        # ``timestamp`` is response-time evidence, so raw values may differ
        # across batches.  Exact-date acceptance requires every batch to carry
        # a timestamp and all timestamps to map to the requested Shanghai
        # trading date.
        exact_date = (
            as_of in calendar_dates
            and timestamp_count == batch_count
            and timestamp_dates == {as_of}
        )
        complete_coverage = (
            bool(catalog_by_code)
            and catalog_integrity
            and not missing_codes
            and not extra_codes
            and not duplicate_snapshot
        )
        complete_fields = bool(normalized) and missing_required == 0
        status = "fallback" if exact_date and complete_coverage and complete_fields else "insufficient"
        if not catalog_by_code or not normalized:
            status = "insufficient"
        quality_extra = {
            # ``endpoint`` remains a compact capability-report field; the
            # complete route set is retained under ``endpoints`` below.
            "endpoint": self.SECTOR_SNAPSHOT_ENDPOINT,
            "endpoints": {
                "calendar": self.SECTOR_CALENDAR_ENDPOINT,
                "catalog": self.SECTOR_CATALOG_ENDPOINT,
                "snapshot": self.SECTOR_SNAPSHOT_ENDPOINT,
            },
            "fieldCoverage": {
                "code": valid_snapshot_rows,
                "name": valid_snapshot_rows,
                "changePct": valid_snapshot_rows,
                "amount": valid_snapshot_rows,
                **{field: 0 for field in self.SECTOR_UNSUPPORTED_FIELDS},
            },
            "calendarCount": len(calendar_dates),
            "catalogCount": len(catalog_by_code),
            "snapshotCount": len(snapshot_by_code),
            "snapshotCoverage": (len(snapshot_by_code) / len(catalog_by_code)) if catalog_by_code else 0.0,
            "snapshotBatchCount": len(snapshots) if isinstance(snapshots, Sequence) and not isinstance(snapshots, Mapping) else 1,
            "snapshotTimestamps": sorted(str(value) for value in timestamps),
            "snapshotTimestampSemantics": "response-time; validated by Shanghai trading date",
            "snapshotTimestampDateConsistent": timestamp_count == batch_count and timestamp_dates == {as_of},
            "permissionEvidence": {"configured": bool(self.client.configured)},
            "rateLimitEvidence": {
                "requestBudget": int(self.client.request_budget),
                "requestsUsed": int(self.client.request_count),
            },
            "dateEvidence": {
                "requested": as_of.isoformat(),
                "calendar": as_of.isoformat() if as_of in calendar_dates else None,
                "snapshot": sorted(value.isoformat() for value in timestamp_dates),
            },
            "unsupportedFields": list(self.SECTOR_UNSUPPORTED_FIELDS),
            "fieldCompleteness": {
                "required": ["code", "name", "changePct", "amount"],
                "requiredComplete": complete_fields,
                "unsupported": list(self.SECTOR_UNSUPPORTED_FIELDS),
                "unsupportedAreNull": True,
            },
        }
        return self._result(
            "industry-ranking",
            {"rows": normalized, "state": "当日排名已观测" if normalized else "insufficient"},
            status=status,
            as_of=as_of,
            observations=len(normalized),
            warnings=warnings,
            provider_revision=self.source_revision,
            quality_extra=quality_extra,
        )

    # A descriptive alias makes the three-response contract easy to discover
    # for callers that do not use the implementation-oriented method name.
    normalize_sectors_from_sources = normalize_sector_index_data

    def normalize_sectors(self, rows: Sequence[Mapping[str, Any]], as_of: date) -> FuyaoMarketResult:
        """Normalize the legacy ranking fixture/API shape.

        Existing offline fixtures contain date-bearing rows and the richer
        Eastmoney-compatible fields.  Keep that contract for compatibility;
        the documented THS path is validated by
        :meth:`normalize_sector_index_data` and :meth:`fetch_sectors`.
        """

        date_ok, warnings = self._date_guard(rows, as_of)
        normalized: list[dict[str, Any]] = []
        for row in rows:
            name = self._text(row, "name", "industry_name", "f14")
            leader = self._text(row, "leader", "leader_name", "f128")
            if not name:
                warnings.append("sector row lacks an industry name")
                continue
            if not leader or _IDENTITY_RE.fullmatch(leader.upper()):
                warnings.append("sector row lacks a real leader name")
                leader = None
            normalized.append(
                {
                    "rank": 0,
                    "code": self._text(row, "code", "industry_code", "f12"),
                    "name": name,
                    "changePct": self._float(row, "change_pct", "changePct", "f3"),
                    "amount": self._float(row, "amount", "turnover", "f6"),
                    "mainNet": self._float(row, "main_net", "mainNet", "f62"),
                    "mainNetPct": self._float(row, "main_net_pct", "mainNetPct", "f184"),
                    "upCount": self._int(row, "up_count", "upCount", "f104"),
                    "downCount": self._int(row, "down_count", "downCount", "f105"),
                    "leader": leader,
                }
            )
        normalized.sort(
            key=lambda row: (
                -(float(row["changePct"])) if row["changePct"] is not None else math.inf,
                str(row["code"] or ""),
            )
        )
        normalized = normalized[:10]
        for rank, row in enumerate(normalized, start=1):
            row["rank"] = rank
        required = ("changePct", "amount", "mainNet", "mainNetPct", "upCount", "downCount")
        complete = all(all(row.get(key) is not None for key in required) for row in normalized) and bool(normalized)
        if not date_ok:
            status = "insufficient"
        elif not complete:
            status = "ineligible"
            warnings.append("sector response is missing one or more required fields")
        else:
            status = "ok"
        return self._result(
            "industry-ranking",
            {"rows": normalized, "state": "当日排名已观测" if normalized else "insufficient"},
            status=status,
            as_of=as_of,
            observations=len(normalized),
            warnings=warnings,
            provider_revision=self.source_revision,
        )

    def fetch_sectors(
        self,
        as_of: date,
        *,
        rows: Sequence[Mapping[str, Any]] | None = None,
        batch_size: int | None = None,
    ) -> FuyaoMarketResult:
        """Fetch and validate the official calendar/catalog/snapshot contract."""

        if rows is not None:
            return self.normalize_sectors(rows, as_of)
        calendar = self.client.request(self.SECTOR_CALENDAR_ENDPOINT).data
        catalog = self.client.request(self.SECTOR_CATALOG_ENDPOINT, params={"tag": "industry"}).data
        catalog_rows, catalog_warnings = self._sector_catalog(catalog)
        if catalog_warnings and not catalog_rows:
            # Keep an auditable insufficient result instead of making a
            # meaningless snapshot request with an empty thscodes parameter.
            return self.normalize_sector_index_data(calendar, catalog, (), as_of)
        selected_batch_size = max(1, int(batch_size or self.SECTOR_SNAPSHOT_BATCH_SIZE))
        codes = tuple(catalog_rows)
        batches: list[Mapping[str, Any]] = []
        for offset in range(0, len(codes), selected_batch_size):
            batch = codes[offset : offset + selected_batch_size]
            response = self.client.request(
                self.SECTOR_SNAPSHOT_ENDPOINT,
                params={"thscodes": ",".join(batch)},
            )
            batches.append(response.data)
        return self.normalize_sector_index_data(calendar, catalog, batches, as_of)


__all__ = [
    "FUYAO_MARKET_API_KEY_ENV",
    "FuyaoMarketAdapter",
    "FuyaoMarketClient",
    "FuyaoMarketConfigurationError",
    "FuyaoMarketContractError",
    "FuyaoMarketError",
    "FuyaoMarketPermissionError",
    "FuyaoMarketRateLimitError",
    "FuyaoMarketResponse",
    "FuyaoMarketResult",
    "FuyaoMarketTransportError",
]
