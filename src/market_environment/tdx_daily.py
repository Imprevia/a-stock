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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests

from src.trading_system.data.providers import ProviderFailure


TDX_UPSTREAM_REPOSITORY = "https://github.com/simonlin1212/a-stock-data"
TDX_UPSTREAM_REVISION = "2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7"
TDX_UPSTREAM_LICENSE = "Apache-2.0"
TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
TDX_BJ_FIRST_DAY = date(2022, 5, 6)
TDX_MIN_PRICED = {"sh": 10_000, "sz": 3_000, "bj": 50}
TDX_MARKETS = ("sh", "sz", "bj")
_CODE_RE = re.compile(r"^[0-9]{6}$")


class TDXDailyPackageError(ProviderFailure):
    """Typed, sanitized failure at the TDX provider boundary."""


class TDXDailyPackageUnavailable(TDXDailyPackageError):
    """The requested package is missing or has not been published yet."""


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
        session: requests.Session | None = None,
        max_bytes: int = 8 * 1024 * 1024,
        minimum_market_rows: Mapping[str, int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_bytes = max(1024, int(max_bytes))
        self.minimum_market_rows = dict(minimum_market_rows or TDX_MIN_PRICED)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def fetch(self, requested_date: date | str) -> TDXDailyPackage:
        expected = _as_date(requested_date, field="requested date")
        ymd = expected.strftime("%Y%m%d")
        url = TDX_PACKAGE_URL.format(ymd=ymd)
        try:
            response = self.session.get(url, timeout=(10, self.timeout))
        except requests.RequestException as exc:
            raise TDXDailyPackageError("TDX package HTTP request failed") from exc
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code == 404:
            raise TDXDailyPackageUnavailable("TDX package is unavailable or not published")
        if status_code < 200 or status_code >= 300:
            raise TDXDailyPackageError(f"TDX package HTTP status {status_code}", status_code=status_code)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TDXDailyPackageError("TDX package HTTP request failed", status_code=status_code) from exc
        content = getattr(response, "content", b"")
        if not isinstance(content, bytes) or len(content) > self.max_bytes:
            raise TDXDailyPackageError("TDX package exceeds the download safety bound")
        if not content:
            raise TDXDailyPackageError("TDX package response is empty")
        try:
            return parse_tdx_daily_package(
                content,
                expected,
                package_date=expected,
                minimum_market_rows=self.minimum_market_rows,
                source_url=url,
                fetched_at=self.now(),
            )
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
