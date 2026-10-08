"""Date-bound client and parser for the TDX official daily package.

The binary layout is a minimal compatible rewrite of the Apache-2.0 licensed
implementation in ``simonlin1212/a-stock-data`` at revision
``2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7``.  The service does not import,
download, or execute that repository at runtime.
"""

from __future__ import annotations

import io
import math
import re
import struct
import zipfile
import zlib
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import RLock
from typing import Any

from src.trading_system.data.provider_http import (
    HostPolicy,
    ProviderHttpClient,
    ProviderHttpError,
    build_requests_compatibility_session,
)
from src.trading_system.data.providers import ProviderFailure


TDX_UPSTREAM_REPOSITORY = "https://github.com/simonlin1212/a-stock-data"
TDX_UPSTREAM_REVISION = "2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7"
TDX_UPSTREAM_LICENSE = "Apache-2.0"
TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
TDX_BJ_FIRST_DAY = date(2022, 5, 6)
TDX_BJ_920_EFFECTIVE_DATE = date(2025, 10, 9)
TDX_MIN_PRICED = {"sh": 10_000, "sz": 3_000, "bj": 50}
TDX_MARKETS = ("sh", "sz", "bj")
TDX_STOCK_UNIVERSE_POLICY_VERSION = "tdx-stock-universe-v1"
TDX_STOCK_UNIVERSE_MINIMUMS = {"sh": 1_000, "sz": 1_500, "bj": 100}
TDX_STOCK_UNIVERSE_MIN_TOTAL = 4_000
TDX_STOCK_UNIVERSE_MAX_UNCLASSIFIED_RATIO = 0.0
_CODE_RE = re.compile(r"^[0-9]{6}$")

_TDX_STOCK_PREFIXES = {
    "sh": ("600", "601", "603", "605", "688"),
    "sz": ("000", "001", "002", "003", "004", "300", "301"),
    "bj": ("43", "83", "87", "88"),
}
_TDX_EXPLICIT_NON_STOCK_PREFIXES = {
    "sh": (
        (("000", "880", "881", "999"), "index"),
        (("900",), "b-share"),
        (
            tuple(f"{prefix:03d}" for prefix in range(500, 590)),
            "fund",
        ),
        (tuple(f"{prefix:03d}" for prefix in range(160, 170)), "fund"),
        (
            (
                "010",
                "018",
                "019",
                "020",
                "152",
                "155",
                "157",
                *tuple(f"{prefix:03d}" for prefix in range(100, 150)),
                *tuple(f"{prefix:03d}" for prefix in range(170, 180)),
                *tuple(f"{prefix:03d}" for prefix in range(184, 189)),
                "198",
                *tuple(f"{prefix:03d}" for prefix in range(230, 250)),
                *tuple(f"{prefix:03d}" for prefix in range(270, 272)),
                "302",
            ),
            "bond",
        ),
        (
            (
                *tuple(f"{prefix:03d}" for prefix in range(180, 184)),
                *tuple(f"{prefix:03d}" for prefix in range(190, 200)),
            ),
            "non-stock-security",
        ),
        (("360", "362"), "preferred-or-other"),
        (("580", "582"), "warrant"),
        (("689",), "depositary-receipt"),
        (("204", "888"), "non-stock-security"),
    ),
    "sz": (
        (("20",), "b-share"),
        (("10", "11", "12", "13", "14", "15", "16", "18"), "fund-or-bond"),
        (("17", "19"), "bond"),
        (("399",), "index"),
        (("03",), "warrant"),
        (("889",), "depositary-receipt"),
        (("302", "500", "501"), "non-stock-security"),
        (("520", "524", "525", "563", "564", "565", "566", "567"), "bond"),
    ),
    "bj": (
        (("899",), "index"),
        (("821", "910"), "non-stock-security"),
        (("92",), "non-stock-security"),
    ),
}


class TDXDailyPackageError(ProviderFailure):
    """Typed, sanitized failure at the TDX provider boundary."""


class TDXDailyPackageUnavailable(TDXDailyPackageError):
    """The requested package is missing or has not been published yet."""


class TDXStockUniverseError(TDXDailyPackageError):
    """The package is parseable but cannot prove a complete stock universe."""

    def __init__(self, message: str, classification: "TDXStockUniverseClassification") -> None:
        super().__init__(message)
        self.classification = classification


@dataclass(frozen=True)
class TDXDailyPackageRow:
    code: str
    date: date
    close: float | None
    amount: float | None
    previous_close: float | None = None
    change_pct: float | None = None
    name: str | None = None
    market: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None


@dataclass(frozen=True)
class TDXStockUniverseClassification:
    """Auditable ordinary A-share classification for one requested date."""

    rows: tuple[TDXDailyPackageRow, ...]
    policy_version: str
    raw_count: int
    retained_count: int
    excluded_count: int
    unclassified_count: int
    retained_by_market: Mapping[str, int]
    excluded_by_reason: Mapping[str, int]
    unclassified_by_reason: Mapping[str, int]

    def metadata(self) -> dict[str, Any]:
        return {
            "stockUniversePolicyVersion": self.policy_version,
            "stockUniverseRawCount": self.raw_count,
            "stockUniverseRetainedCount": self.retained_count,
            "stockUniverseExcludedCount": self.excluded_count,
            "stockUniverseUnclassifiedCount": self.unclassified_count,
            "stockUniverseRetainedByMarket": dict(self.retained_by_market),
            "stockUniverseExcludedByReason": dict(self.excluded_by_reason),
            "stockUniverseUnclassifiedByReason": dict(self.unclassified_by_reason),
        }


@dataclass(frozen=True)
class TDXDailyPackage:
    rows: tuple[TDXDailyPackageRow, ...]
    source_url: str
    requested_date: date
    source_date: date
    fetched_at: datetime
    metadata: Mapping[str, Any]


def _as_date(value: date | str, *, field: str) -> date:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise TDXDailyPackageError(f"TDX package {field} is invalid")


def _finite_number(value: Any, *, field: str, allow_none: bool = True) -> float | None:
    if value in (None, "", "-"):
        if allow_none:
            return None
        raise TDXDailyPackageError(f"TDX package row is missing {field}")
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise TDXDailyPackageError(f"TDX package row has invalid {field}") from exc
    if not math.isfinite(number):
        raise TDXDailyPackageError(f"TDX package row has non-finite {field}")
    return number


def _optional_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text in {"-", "--"}:
        return None
    return text


def _value(row: Mapping[str, Any], *keys: str) -> Any:
    return next((row[key] for key in keys if key in row), None)


def normalize_tdx_rows(
    rows: Iterable[TDXDailyPackageRow | Mapping[str, Any]],
    requested_date: date | str,
) -> tuple[TDXDailyPackageRow, ...]:
    """Normalize injected/package rows without filling missing facts with zero."""

    expected = _as_date(requested_date, field="requested date")
    normalized: list[TDXDailyPackageRow] = []
    for index, raw in enumerate(rows):
        if isinstance(raw, TDXDailyPackageRow):
            item = raw
            if item.date != expected:
                raise TDXDailyPackageError(f"TDX package row {index} has a conflicting date")
            normalized.append(item)
            continue
        if not isinstance(raw, Mapping):
            raise TDXDailyPackageError(f"TDX package row {index} is malformed")
        code = str(_value(raw, "code", "f12", "symbol") or "").strip()
        if not _CODE_RE.fullmatch(code):
            raise TDXDailyPackageError(f"TDX package row {index} has an invalid code")
        row_date = _as_date(_value(raw, "date", "as_of", "asOf") or expected, field="row date")
        if row_date != expected:
            raise TDXDailyPackageError(f"TDX package row {index} has a conflicting date")
        close = _finite_number(_value(raw, "close", "f2", "price", "收盘价"), field="close")
        amount = _finite_number(
            _value(raw, "amount", "f6", "turnover", "成交额"),
            field="amount",
        )
        previous_close = _finite_number(
            _value(raw, "previous_close", "prev_close", "last_close", "昨收"),
            field="previous_close",
        )
        change_pct = _finite_number(
            _value(raw, "change_pct", "changePct", "f3", "涨跌幅"),
            field="change_pct",
        )
        if previous_close is not None and previous_close <= 0:
            raise TDXDailyPackageError(f"TDX package row {index} has an invalid previous_close")
        name = _optional_name(_value(raw, "name", "f14", "security_name", "证券名称"))
        market = _optional_name(_value(raw, "market", "exchange"))
        open_ = _finite_number(_value(raw, "open", "开盘"), field="open")
        high = _finite_number(_value(raw, "high", "f15", "最高"), field="high")
        low = _finite_number(_value(raw, "low", "f16", "最低"), field="low")
        raw_volume = _finite_number(_value(raw, "volume", "成交量"), field="volume")
        volume = int(raw_volume) if raw_volume is not None and raw_volume >= 0 else None
        normalized.append(
            TDXDailyPackageRow(
                code=code,
                date=row_date,
                close=close,
                amount=amount,
                previous_close=previous_close,
                change_pct=change_pct,
                name=name,
                market=market,
                open=open_,
                high=high,
                low=low,
                volume=volume,
            )
        )
    return tuple(normalized)


def _tdx_non_stock_reason(market: str, code: str) -> str | None:
    for prefixes, reason in _TDX_EXPLICIT_NON_STOCK_PREFIXES.get(market, ()):
        if code.startswith(prefixes):
            return reason
    return None


def _tdx_stock_code_allowed(market: str, code: str, as_of: date) -> tuple[bool, str | None]:
    if market == "bj" and code.startswith("920"):
        if as_of < TDX_BJ_920_EFFECTIVE_DATE:
            return False, "bj-920-before-effective-date"
        return True, None
    if code.startswith(_TDX_STOCK_PREFIXES.get(market, ())):
        return True, None
    if (reason := _tdx_non_stock_reason(market, code)) is not None:
        return False, reason
    return False, "unrecognized-code-range"


def classify_tdx_stock_universe(
    rows: Iterable[TDXDailyPackageRow],
    requested_date: date | str,
) -> TDXStockUniverseClassification:
    """Keep only ordinary A-share rows using a date-versioned code policy."""

    expected = _as_date(requested_date, field="requested date")
    retained: list[TDXDailyPackageRow] = []
    retained_by_market = {market: 0 for market in TDX_MARKETS}
    excluded_by_reason: dict[str, int] = {}
    unclassified_by_reason: dict[str, int] = {}
    seen: set[tuple[str | None, str]] = set()
    raw_count = 0

    for raw in rows:
        raw_count += 1
        if not isinstance(raw, TDXDailyPackageRow):
            unclassified_by_reason["malformed-row"] = unclassified_by_reason.get("malformed-row", 0) + 1
            continue
        market = str(raw.market or "").strip().lower() or None
        identity = (market, raw.code)
        if identity in seen:
            unclassified_by_reason["duplicate-identity"] = (
                unclassified_by_reason.get("duplicate-identity", 0) + 1
            )
            continue
        seen.add(identity)
        if raw.date != expected:
            unclassified_by_reason["conflicting-date"] = (
                unclassified_by_reason.get("conflicting-date", 0) + 1
            )
            continue
        if market not in TDX_MARKETS:
            unclassified_by_reason["unsupported-market"] = (
                unclassified_by_reason.get("unsupported-market", 0) + 1
            )
            continue
        if not _CODE_RE.fullmatch(raw.code):
            unclassified_by_reason["invalid-code"] = (
                unclassified_by_reason.get("invalid-code", 0) + 1
            )
            continue
        allowed, reason = _tdx_stock_code_allowed(market, raw.code, expected)
        if allowed:
            retained.append(raw)
            retained_by_market[market] += 1
        elif reason in {
            "b-share",
            "fund",
            "fund-or-bond",
            "bond",
            "preferred-or-other",
            "warrant",
            "index",
            "depositary-receipt",
            "non-stock-security",
        }:
            excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
        else:
            reason = reason or "unclassified"
            unclassified_by_reason[reason] = unclassified_by_reason.get(reason, 0) + 1

    excluded_count = sum(excluded_by_reason.values())
    unclassified_count = sum(unclassified_by_reason.values())
    return TDXStockUniverseClassification(
        rows=tuple(retained),
        policy_version=TDX_STOCK_UNIVERSE_POLICY_VERSION,
        raw_count=raw_count,
        retained_count=len(retained),
        excluded_count=excluded_count,
        unclassified_count=unclassified_count,
        retained_by_market=retained_by_market,
        excluded_by_reason=excluded_by_reason,
        unclassified_by_reason=unclassified_by_reason,
    )


def validate_tdx_stock_universe(
    classification: TDXStockUniverseClassification,
    *,
    minimum_market_rows: Mapping[str, int] | None = None,
    minimum_total: int = TDX_STOCK_UNIVERSE_MIN_TOTAL,
    required_markets: Iterable[str] = TDX_MARKETS,
    max_unclassified_ratio: float = TDX_STOCK_UNIVERSE_MAX_UNCLASSIFIED_RATIO,
) -> None:
    """Reject a filtered package that cannot prove a complete stock universe."""

    minimums = dict(TDX_STOCK_UNIVERSE_MINIMUMS if minimum_market_rows is None else minimum_market_rows)
    required = tuple(dict.fromkeys(required_markets))
    if classification.raw_count <= 0 or classification.retained_count <= 0:
        raise TDXStockUniverseError("TDX ordinary A-share universe is empty", classification)
    duplicate_count = classification.unclassified_by_reason.get("duplicate-identity", 0)
    if duplicate_count:
        raise TDXStockUniverseError(
            "TDX ordinary A-share universe has duplicate identities",
            classification,
        )
    if classification.raw_count and (
        classification.unclassified_count / classification.raw_count > max_unclassified_ratio
    ):
        raise TDXStockUniverseError(
            "TDX ordinary A-share universe has unclassified security identities",
            classification,
        )
    missing = [
        market
        for market in required
        if classification.retained_by_market.get(market, 0) < int(minimums.get(market, 0))
    ]
    if missing:
        raise TDXStockUniverseError(
            "TDX ordinary A-share universe is incomplete: " + ",".join(sorted(missing)),
            classification,
        )
    if classification.retained_count < int(minimum_total):
        raise TDXStockUniverseError(
            f"TDX ordinary A-share universe has only {classification.retained_count} rows",
            classification,
        )


def _parse_package_bytes(
    content: bytes,
    package_date: date,
    *,
    minimum_market_rows: Mapping[str, int] | None = None,
) -> tuple[tuple[TDXDailyPackageRow, ...], dict[str, Any]]:
    if not isinstance(content, bytes) or not content.startswith(b"PK"):
        raise TDXDailyPackageError("TDX package is not a zip archive")
    minimums = dict(TDX_MIN_PRICED if minimum_market_rows is None else minimum_market_rows)
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        bad_member = archive.testzip()
        if bad_member is not None:
            raise TDXDailyPackageError("TDX package has a failed archive checksum")
        names = set(archive.namelist())
        total_uncompressed = sum(info.file_size for info in archive.infolist())
        if total_uncompressed > 80 * 1024 * 1024:
            raise TDXDailyPackageError("TDX package expands beyond the safety bound")
        rows: list[TDXDailyPackageRow] = []
        market_counts: dict[str, int] = {}
        for market in TDX_MARKETS:
            cod_name = f"{market}{package_date.strftime('%y%m%d')}.cod"
            md1_name = f"{market}{package_date.strftime('%y%m%d')}.md1"
            if market == "bj" and package_date < TDX_BJ_FIRST_DAY and cod_name not in names and md1_name not in names:
                continue
            if cod_name not in names or md1_name not in names:
                raise TDXDailyPackageError(f"TDX package is missing the {market} market files")
            cod = archive.read(cod_name)
            md1 = archive.read(md1_name)
            if len(cod) % 150 or len(md1) % 512:
                raise TDXDailyPackageError(f"TDX package {market} member is truncated")
            record_count = len(cod) // 150
            block_count = len(md1) // 512
            if record_count != block_count:
                raise TDXDailyPackageError(f"TDX package {market} record/block counts differ")
            codes: set[str] = set()
            sequences: set[int] = set()
            before = len(rows)
            for offset in range(0, len(cod), 150):
                record = cod[offset : offset + 150]
                code_bytes = record[0:6].rstrip(b"\x00 ")
                try:
                    code = code_bytes.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise TDXDailyPackageError(f"TDX package {market} has a non-ASCII code") from exc
                sequence = struct.unpack("<H", record[32:34])[0]
                if not _CODE_RE.fullmatch(code):
                    raise TDXDailyPackageError(f"TDX package {market} has an invalid code")
                if code in codes or sequence in sequences:
                    raise TDXDailyPackageError(f"TDX package {market} has duplicate identity")
                codes.add(code)
                sequences.add(sequence)
                start = sequence * 512
                block = md1[start : start + 512]
                if len(block) != 512:
                    raise TDXDailyPackageError(f"TDX package {market} has an out-of-range block")
                previous_close = struct.unpack("<d", block[4:12])[0]
                open_, high, low, close = struct.unpack("<4d", block[12:44])
                volume = struct.unpack("<Q", block[56:64])[0]
                amount = struct.unpack("<d", block[72:80])[0]
                numbers = (previous_close, open_, high, low, close, amount)
                if not all(math.isfinite(value) for value in numbers):
                    raise TDXDailyPackageError(f"TDX package {market} has a non-finite numeric value")
                if amount < 0:
                    raise TDXDailyPackageError(f"TDX package {market} has a negative amount")
                if close <= 0:
                    continue
                raw_name = record[40:72].split(b"\x00", 1)[0]
                try:
                    name = raw_name.decode("gbk").strip()
                except UnicodeDecodeError as exc:
                    raise TDXDailyPackageError(f"TDX package {market} has an invalid name encoding") from exc
                if not name:
                    raise TDXDailyPackageError(f"TDX package {market} has a priced row without a name")
                change_pct = None
                if previous_close > 0:
                    change_pct = (close - previous_close) / previous_close * 100
                rows.append(
                    TDXDailyPackageRow(
                        code=code,
                        date=package_date,
                        close=round(close, 4),
                        amount=round(amount, 2),
                        previous_close=round(previous_close, 4),
                        change_pct=round(change_pct, 8) if change_pct is not None else None,
                        name=name,
                        market=market,
                        open=round(open_, 4),
                        high=round(high, 4),
                        low=round(low, 4),
                        volume=volume,
                    )
                )
            market_count = len(rows) - before
            market_counts[market] = market_count
            if market_count < int(minimums.get(market, 0)):
                raise TDXDailyPackageError(f"TDX package {market} market is incomplete")
        if not rows:
            raise TDXDailyPackageError("TDX package has no priced A-share rows")
        metadata = {
            "archiveBytes": len(content),
            "files": sorted(names),
            "marketCounts": market_counts,
            "recordCount": len(rows),
        }
        return tuple(rows), metadata
    except TDXDailyPackageError:
        raise
    except (EOFError, OSError, struct.error, ValueError, zipfile.BadZipFile, zlib.error) as exc:
        raise TDXDailyPackageError("TDX package cannot be parsed") from exc


def parse_tdx_daily_package(
    content: bytes,
    requested_date: date | str,
    *,
    package_date: date | str | None = None,
    minimum_market_rows: Mapping[str, int] | None = None,
    source_url: str | None = None,
    fetched_at: datetime | None = None,
) -> TDXDailyPackage:
    expected = _as_date(requested_date, field="requested date")
    source_date = _as_date(package_date or expected, field="source date")
    if source_date != expected:
        raise TDXDailyPackageError("TDX package source date conflicts with requested date")
    rows, metadata = _parse_package_bytes(
        content,
        source_date,
        minimum_market_rows=minimum_market_rows,
    )
    return TDXDailyPackage(
        rows=rows,
        source_url=source_url or TDX_PACKAGE_URL.format(ymd=source_date.strftime("%Y%m%d")),
        requested_date=expected,
        source_date=source_date,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        metadata=metadata,
    )


class TDXDailyPackageClient:
    """Injectable, bounded HTTP client for exactly one requested session date."""

    def __init__(
        self,
        *,
        timeout: float = 90.0,
        session: Any | None = None,
        max_bytes: int = 8 * 1024 * 1024,
        minimum_market_rows: Mapping[str, int] | None = None,
        stock_universe_minimums: Mapping[str, int] | None = None,
        stock_universe_minimum_total: int = TDX_STOCK_UNIVERSE_MIN_TOTAL,
        stock_universe_required_markets: Iterable[str] = TDX_MARKETS,
        stock_universe_max_unclassified_ratio: float = TDX_STOCK_UNIVERSE_MAX_UNCLASSIFIED_RATIO,
        now: Callable[[], datetime] | None = None,
        http_client: ProviderHttpClient | None = None,
        package_cache_size: int = 2,
    ) -> None:
        self.timeout = timeout
        self.session = session or build_requests_compatibility_session()
        self.http = http_client or ProviderHttpClient(
            session=self.session,
            default_policy=HostPolicy(
                minimum_interval=1.0,
                jitter=(0.05, 0.25),
                timeout=(10.0, timeout),
                max_retries=2,
                retry_backoff=1.0,
                request_budget=20,
                cache_ttl_seconds=0.0,
            ),
        )
        self.max_bytes = max(1024, int(max_bytes))
        self.minimum_market_rows = dict(minimum_market_rows or TDX_MIN_PRICED)
        self.stock_universe_minimums = dict(
            stock_universe_minimums or TDX_STOCK_UNIVERSE_MINIMUMS
        )
        self.stock_universe_minimum_total = int(stock_universe_minimum_total)
        self.stock_universe_required_markets = tuple(stock_universe_required_markets)
        self.stock_universe_max_unclassified_ratio = float(stock_universe_max_unclassified_ratio)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._package_cache: OrderedDict[date, TDXDailyPackage] = OrderedDict()
        self._package_cache_size = max(1, int(package_cache_size))
        self._package_cache_lock = RLock()

    def fetch(self, requested_date: date | str) -> TDXDailyPackage:
        expected = _as_date(requested_date, field="requested date")
        with self._package_cache_lock:
            cached = self._package_cache.get(expected)
            if cached is not None:
                self._package_cache.move_to_end(expected)
                return cached
        ymd = expected.strftime("%Y%m%d")
        url = TDX_PACKAGE_URL.format(ymd=ymd)
        try:
            response = self.http.get(
                url,
                timeout=(10, self.timeout),
                cache_ttl=0.0,
                requested_date=expected.isoformat(),
                source_id="tdx-daily-package",
                max_response_bytes=self.max_bytes,
            )
        except ProviderHttpError as exc:
            if exc.status_code == 404:
                raise TDXDailyPackageUnavailable("TDX package is unavailable or not published") from exc
            if exc.kind == "contract" or "exceeds" in str(exc).lower():
                raise TDXDailyPackageError(
                    "TDX package exceeds the download safety bound"
                ) from exc
            raise TDXDailyPackageError(
                f"TDX package HTTP status {exc.status_code or 'request failure'}",
                status_code=exc.status_code,
            ) from exc
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code == 404:
            raise TDXDailyPackageUnavailable("TDX package is unavailable or not published")
        if status_code < 200 or status_code >= 300:
            raise TDXDailyPackageError(f"TDX package HTTP status {status_code}", status_code=status_code)
        response.raise_for_status()
        content = getattr(response, "content", b"")
        if not isinstance(content, bytes) or len(content) > self.max_bytes:
            raise TDXDailyPackageError("TDX package exceeds the download safety bound")
        if not content:
            raise TDXDailyPackageError("TDX package response is empty")
        with self._package_cache_lock:
            cached = self._package_cache.get(expected)
            if cached is not None:
                self._package_cache.move_to_end(expected)
                return cached
            try:
                package = parse_tdx_daily_package(
                    content,
                    expected,
                    package_date=expected,
                    minimum_market_rows=self.minimum_market_rows,
                    source_url=url,
                    fetched_at=self.now(),
                )
                self._package_cache[expected] = package
                self._package_cache.move_to_end(expected)
                while len(self._package_cache) > self._package_cache_size:
                    self._package_cache.popitem(last=False)
                return package
            except TDXDailyPackageError:
                raise
            except Exception as exc:
                raise TDXDailyPackageError("TDX package response cannot be normalized") from exc


__all__ = [
    "TDXDailyPackage",
    "TDXDailyPackageClient",
    "TDXDailyPackageError",
    "TDXDailyPackageRow",
    "TDXDailyPackageUnavailable",
    "TDX_BJ_FIRST_DAY",
    "TDX_MIN_PRICED",
    "TDX_PACKAGE_URL",
    "TDX_UPSTREAM_LICENSE",
    "TDX_UPSTREAM_REPOSITORY",
    "TDX_UPSTREAM_REVISION",
    "normalize_tdx_rows",
    "parse_tdx_daily_package",
]
