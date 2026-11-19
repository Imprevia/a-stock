"""Sina market-data client for the active-industry scan Skill.

Two independent endpoints, both public and unauthenticated:

* ``Market_Center.getHQNodeData`` — one row per stock with the current
  cumulative turnover rate and amount.  The server accepts ``sort`` so the
  Top-N comes back in two pages instead of a 56-page sweep.
* ``CN_MarketDataService.getKLineData`` — 5-minute bars, stamped with the
  *end* of each bar (09:35 is the first, 15:00 the last, with a 95-minute gap
  across the lunch break).

Nothing here writes to a database; results go straight to the caller.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

BASE_NODE_URL = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/Market_Center.getHQNodeData"
)
BASE_KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php"
    "/CN_MarketDataService.getKLineData"
)

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}

NODE_ALL_A = "hs_a"
PAGE_SIZE = 100
DEFAULT_TIMEOUT = 25.0

RANK_BY_AMOUNT = "amount"
RANK_BY_TURNOVER = "turnoverratio"
RANKING_KEYS = (RANK_BY_AMOUNT, RANK_BY_TURNOVER)

EXCHANGE_SUFFIX = {"sh": "SH", "sz": "SZ", "bj": "BJ"}


class SinaError(RuntimeError):
    """A Sina request failed; the caller decides how to degrade."""


@dataclass(frozen=True)
class RankRow:
    """One stock on a ranking."""

    code: str
    symbol: str
    name: str
    amount: float
    turnover_pct: float
    price: float
    float_mv_yi: float
    change_pct: float

    @property
    def thscode(self) -> str:
        return to_thscode(self.symbol)


def to_thscode(symbol: str) -> str:
    """Map a Sina symbol (``sh600000``) to a thscode (``600000.SH``)."""

    prefix = symbol[:2].lower()
    suffix = EXCHANGE_SUFFIX.get(prefix)
    if suffix is None:
        return symbol.upper()
    return f"{symbol[2:]}.{suffix}"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


def parse_row(raw: Mapping[str, Any]) -> RankRow | None:
    """Convert one raw Sina row; unusable rows return ``None``."""

    symbol = str(raw.get("symbol") or "").strip()
    code = str(raw.get("code") or "").strip()
    if not symbol or not code:
        return None
    return RankRow(
        code=code,
        symbol=symbol,
        name=str(raw.get("name") or "").strip(),
        amount=_number(raw.get("amount")),
        turnover_pct=_number(raw.get("turnoverratio")),
        price=_number(raw.get("trade")),
        float_mv_yi=_number(raw.get("nmc")) / 10000.0,
        change_pct=_number(raw.get("changepercent")),
    )


def _get_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        payload = urllib.request.urlopen(request, timeout=timeout).read()
    except (urllib.error.URLError, OSError) as error:  # noqa: UP041 - OSError covers timeouts
        raise SinaError(f"请求失败: {error}") from error
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SinaError(f"响应不是合法 JSON: {error}") from error


def _page_url(sort_key: str, page: int, page_size: int) -> str:
    return (
        f"{BASE_NODE_URL}?page={page}&num={page_size}"
        f"&sort={sort_key}&asc=0&node={NODE_ALL_A}&symbol=&_s_r_a=page"
    )


def fetch_sorted_pool(
    sort_key: str,
    *,
    pool_size: int = 400,
    page_size: int = PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = 8,
) -> list[RankRow]:
    """Fetch a server-sorted candidate pool for one ranking key.

    Pages are requested concurrently because the server sorts before paging,
    so page 3 is meaningful without having read pages 1–2 first.
    """

    if sort_key not in RANKING_KEYS:
        raise ValueError(f"unsupported sort key: {sort_key}")
    pages = max(1, (pool_size + page_size - 1) // page_size)

    def one(page: int) -> list[Any]:
        payload = _get_json(_page_url(sort_key, page, page_size), timeout)
        return payload if isinstance(payload, list) else []

    rows: list[RankRow] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for batch in pool.map(one, range(1, pages + 1)):
            for raw in batch:
                if not isinstance(raw, Mapping):
                    continue
                parsed = parse_row(raw)
                if parsed is not None:
                    rows.append(parsed)
    rows.sort(key=lambda r: _sort_value(r, sort_key), reverse=True)
    return rows[:pool_size]


def _sort_value(row: RankRow, sort_key: str) -> float:
    return row.turnover_pct if sort_key == RANK_BY_TURNOVER else row.amount


def fetch_full_snapshot(
    *,
    page_size: int = PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = 16,
    max_pages: int = 80,
) -> list[RankRow]:
    """Fetch every tradable A-share row and rank locally.

    This is the degraded path used when server-side sorting is unavailable.
    It costs roughly a second for ~5,600 rows, so it stays inside the intraday
    budget.
    """

    def one(page: int) -> list[Any]:
        payload = _get_json(_page_url("symbol", page, page_size), timeout)
        return payload if isinstance(payload, list) else []

    rows: list[RankRow] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for batch in pool.map(one, range(1, max_pages + 1)):
            if not batch:
                continue
            for raw in batch:
                if not isinstance(raw, Mapping):
                    continue
                parsed = parse_row(raw)
                if parsed is not None:
                    rows.append(parsed)
    return rows


def rank(
    rows: Iterable[RankRow],
    sort_key: str,
    *,
    top: int,
) -> list[RankRow]:
    """Sort a row collection by one ranking key and keep the head."""

    if sort_key not in RANKING_KEYS:
        raise ValueError(f"unsupported sort key: {sort_key}")
    ordered = sorted(rows, key=lambda r: _sort_value(r, sort_key), reverse=True)
    return ordered[:top]


def fetch_kline(
    symbol: str,
    *,
    scale: int = 5,
    datalen: int = 60,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff: float = 0.3,
) -> list[dict[str, Any]]:
    """Fetch intraday bars for one symbol.  Empty list on unrecoverable failure.

    Transient rate limiting is common when many symbols are requested at once,
    so a short bounded retry runs before the symbol is given up on.  Callers
    compare requested versus returned counts to decide whether to degrade.
    """

    url = (
        f"{BASE_KLINE_URL}?symbol={symbol}&scale={scale}"
        f"&ma=no&datalen={datalen}"
    )
    attempt = 0
    while True:
        try:
            payload = _get_json(url, timeout)
        except SinaError:
            if attempt >= retries:
                return []
            attempt += 1
            time.sleep(backoff * attempt)
            continue
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, Mapping)]


def fetch_klines(
    symbols: Sequence[str],
    *,
    scale: int = 5,
    datalen: int = 60,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = 12,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Fetch intraday bars for many symbols concurrently.

    Returns ``(bars_by_symbol, missing_symbols)``.  Callers need the missing
    list because a partial intraday dataset silently shrinks the momentum
    window: without it, a rate-limited batch would look like a market where
    most stocks simply had no trading.
    """

    def one(symbol: str) -> tuple[str, list[dict[str, Any]]]:
        return symbol, fetch_kline(
            symbol, scale=scale, datalen=datalen, timeout=timeout
        )

    result: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for symbol, bars in pool.map(one, symbols):
            if bars:
                result[symbol] = bars
            else:
                missing.append(symbol)
    return result, missing


def bars_up_to(
    bars: Sequence[Mapping[str, Any]],
    cutoff: str,
) -> list[Mapping[str, Any]]:
    """Keep only bars whose end timestamp is at or before ``cutoff`` (HH:MM).

    Bars are stamped with their end time, so a 10:30 request keeps exactly the
    bars ending 09:35 through 10:30 — twelve of them.
    """

    kept = []
    for bar in bars:
        stamp = str(bar.get("day") or "")
        if len(stamp) < 16:
            continue
        if stamp[11:16] <= cutoff:
            kept.append(bar)
    return kept


def cumulative_volume(bars: Sequence[Mapping[str, Any]]) -> int:
    """Sum bar volumes, ignoring unparseable values."""

    total = 0
    for bar in bars:
        try:
            total += int(float(bar.get("volume") or 0))
        except (TypeError, ValueError):
            continue
    return total


def cumulative_amount(bars: Sequence[Mapping[str, Any]]) -> float:
    """Sum bar amounts, ignoring unparseable values."""

    total = 0.0
    for bar in bars:
        try:
            total += float(bar.get("amount") or 0)
        except (TypeError, ValueError):
            continue
    return total