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
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

import requests

from .calculations import Bar

FUYAO_MARKET_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
FUYAO_MARKET_BASE_URL = "https://fuyao.aicubes.cn"

_IDENTITY_RE = re.compile(r"^(?P<ticker>\d{6})\.(?P<exchange>SH|SZ|BJ)$")
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
        request_budget: int = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv(FUYAO_MARKET_API_KEY_ENV, "")).strip()
        self.timeout = max(0.1, float(timeout))
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.request_budget = max(1, int(request_budget))
        self._request_count = 0
        self._sleep = sleep

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
                    self._backoff(attempt)
                    continue
                raise FuyaoMarketRateLimitError("Fuyao HTTP 429 after retries")
            if 500 <= status < 600:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise FuyaoMarketTransportError(f"Fuyao HTTP {status} after retries")
            if status < 200 or status >= 300:
                raise FuyaoMarketTransportError(f"Fuyao HTTP {status}")
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
                    self._backoff(attempt)
                    continue
                raise FuyaoMarketTransportError(f"Fuyao response code {code} after retries")
            if code in self._PERMISSION_CODES:
                raise FuyaoMarketPermissionError(f"Fuyao authentication or permission denied (code={code})")
            if code not in {0, 200}:
                raise FuyaoMarketError(f"Fuyao request rejected (code={code})")
            data = envelope.get("data", envelope.get("result"))
            if not isinstance(data, Mapping):
                raise FuyaoMarketContractError("Fuyao success envelope is missing data")
            return FuyaoMarketResponse(dict(data), status, self._request_count)
        raise AssertionError("unreachable retry loop")

    def _backoff(self, attempt: int) -> None:
        self._sleep(self.backoff_seconds * (2**attempt))


class FuyaoMarketAdapter:
    """Normalize fixture/API responses into existing dashboard contracts."""

    INDEX_CODES = dict(_CODE_TO_IDENTITY)

    def __init__(self, client: FuyaoMarketClient | None = None, *, source_revision: str = "fuyao-market-v1") -> None:
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
            return datetime.fromtimestamp(number, timezone.utc).date()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @classmethod
    def _row_date(cls, row: Mapping[str, Any]) -> date | None:
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
        provider_revision: str = "fuyao-market-v1",
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
    def _result(cls, dataset: str, payload: dict[str, Any], *, status: str, as_of: date, observations: int, warnings: Sequence[str] = ()) -> FuyaoMarketResult:
        quality = cls._quality(dataset, status, observations, as_of, warnings)
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
        min_bars: int = 60,
    ) -> dict[str, FuyaoMarketResult]:
        result: dict[str, FuyaoMarketResult] = {}
        for code, rows in rows_by_code.items():
            canonical = str(code).lower()
            expected_identity = self.INDEX_CODES.get(canonical, canonical.upper())
            bars: list[Bar] = []
            warnings: list[str] = []
            date_ok, date_warnings = self._date_guard(rows[-1:], as_of)
            warnings.extend(date_warnings)
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
            result[canonical] = self._result(
                "core",
                {"code": canonical, "identity": expected_identity, "bars": bars},
                status=status,
                as_of=as_of,
                observations=len(bars),
                warnings=warnings,
            )
        return result

    def fetch_core(self, as_of: date, *, codes: Sequence[str] | None = None, limit: int = 280) -> dict[str, FuyaoMarketResult]:
        selected = tuple(codes or self.INDEX_CODES)
        rows: dict[str, list[dict[str, Any]]] = {}
        for code in selected:
            response = self.client.request("/api/a-share/index/history", params={"code": self.INDEX_CODES.get(code, code), "limit": limit})
            rows[code] = self._rows(response.data)
        return self.normalize_core(rows, as_of)

    # ---- breadth ---------------------------------------------------------
    def normalize_breadth(self, pages: Sequence[Mapping[str, Any]], as_of: date, *, expected_total: int | None = None) -> FuyaoMarketResult:
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

    def fetch_breadth(self, as_of: date, *, pages: Sequence[Mapping[str, Any]] | None = None) -> FuyaoMarketResult:
        if pages is None:
            response = self.client.request("/api/a-share/market/snapshot", params={"page": 1, "size": 1000})
            pages = (response.data,)
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
            response = self.client.request("/api/a-share/market/snapshot", params={"page": 1, "size": 100})
            rows = self._rows(response.data)
        return self.normalize_active_direction(
            rows,
            as_of,
            ordering_proven=ordering_proven,
            full_market_proven=full_market_proven,
        )

    # ---- sectors ---------------------------------------------------------
    def normalize_sectors(self, rows: Sequence[Mapping[str, Any]], as_of: date) -> FuyaoMarketResult:
        date_ok, warnings = self._date_guard(rows, as_of)
        normalized: list[dict[str, Any]] = []
        for rank, row in enumerate(rows[:10], start=1):
            name = self._text(row, "name", "industry_name", "f14")
            leader = self._text(row, "leader", "leader_name", "f128")
            if not name:
                warnings.append("sector row lacks an industry name")
                continue
            if not leader or _IDENTITY_RE.fullmatch(leader.upper()):
                warnings.append("sector row lacks a real leader name")
                leader = None
            normalized.append({"rank": rank, "code": self._text(row, "code", "industry_code", "f12"), "name": name, "changePct": self._float(row, "change_pct", "changePct", "f3"), "amount": self._float(row, "amount", "turnover", "f6"), "mainNet": self._float(row, "main_net", "mainNet", "f62"), "mainNetPct": self._float(row, "main_net_pct", "mainNetPct", "f184"), "upCount": self._int(row, "up_count", "upCount", "f104"), "downCount": self._int(row, "down_count", "downCount", "f105"), "leader": leader})
        required = ("changePct", "amount", "mainNet", "mainNetPct", "upCount", "downCount")
        complete = all(all(row.get(key) is not None for key in required) for row in normalized) and bool(normalized)
        if not date_ok:
            status = "insufficient"
        elif not complete:
            status = "ineligible"
            warnings.append("sector response is missing one or more required fields")
        else:
            status = "ok"
        return self._result("industry-ranking", {"rows": normalized, "state": "当日排名已观测" if normalized else "insufficient"}, status=status, as_of=as_of, observations=len(normalized), warnings=warnings)

    def fetch_sectors(self, as_of: date, *, rows: Sequence[Mapping[str, Any]] | None = None) -> FuyaoMarketResult:
        if rows is None:
            response = self.client.request("/api/a-share/industry/ranking", params={"page": 1, "size": 100})
            rows = self._rows(response.data)
        return self.normalize_sectors(rows, as_of)


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
