"""Fuyao client for the active-industry scan Skill.

Three Fuyao-backed lookups, all through the ``hithink-finance`` CLI so no
credential ever reaches a process argument list:

* ``symbol list``        — every A-share with its ``list_date``.
* ``market history-batch`` — daily bars, used for the settlement-time percentile.
* ``index constituents``  — THS industry membership.

Credential resolution mirrors ``qts04-core``: ``FUYAO_API_KEY``, then
``MARKET_ENVIRONMENT_FUYAO_API_KEY``, then the single key inside
``deploy/truenas/deploy.env``.  Only that key is read; the file is never echoed.
"""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

API_KEY_ENV = "FUYAO_API_KEY"
LEGACY_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
CLI_BINARY = "hithink-finance"
ENV_FILE_VAR = "FUYAO_API_KEY"
ENV_FILE_RELATIVE = Path("deploy") / "truenas" / "deploy.env"

DEFAULT_TIMEOUT = 120.0
MAX_BATCH_CODES = 10
MARKET_PAGE_SIZE = 1000

CACHE_DIRNAME = Path(".cache") / "active-industry-scan"


class FuyaoError(RuntimeError):
    """A Fuyao call failed; callers decide whether to degrade."""


def parse_env_file(path: Path, variable: str) -> str | None:
    """Read exactly one variable from a dotenv-style file.

    Only the requested key is returned.  The file may hold unrelated secrets
    and is never logged or echoed.
    """

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != variable:
            continue
        value = value.strip()
        comment = value.find(" #")
        if comment != -1:
            value = value[:comment].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip() or None
    return None


def find_env_file(start: Path | None = None) -> Path | None:
    """Walk upward from ``start`` looking for ``deploy/truenas/deploy.env``."""

    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent
    for parent in (current, *current.parents):
        candidate = parent / ENV_FILE_RELATIVE
        if candidate.is_file():
            return candidate
    return None


def resolve_credential(
    *,
    explicit_key: str | None = None,
    env_file: Path | None = None,
    search_env_file: bool = True,
) -> tuple[str | None, str]:
    """Resolve the API key and the *label* of its origin, never its value."""

    if explicit_key and explicit_key.strip():
        return explicit_key.strip(), "argument"
    for name in (API_KEY_ENV, LEGACY_API_KEY_ENV):
        value = os.getenv(name, "").strip()
        if value:
            return value, f"env:{name}"
    candidate = env_file
    if candidate is None and search_env_file:
        candidate = find_env_file()
    if candidate is not None:
        value = parse_env_file(candidate, ENV_FILE_VAR)
        if value:
            return value, f"file:{ENV_FILE_VAR}@{Path(candidate).name}"
    return None, "none"


@dataclass(frozen=True)
class SymbolInfo:
    """One listing row."""

    thscode: str
    name: str
    list_date: date | None

    def listing_days(self, today: date) -> int | None:
        if self.list_date is None:
            return None
        return (today - self.list_date).days


@dataclass(frozen=True)
class MarketSnapshot:
    """Whole-market change and volume maps plus their provenance.

    ``source`` records which path produced the data (the fuyao endpoint or the
    Sina full-snapshot fallback) so a degraded run stays auditable.  ``None``
    means "not measured" everywhere in these maps, never 0.
    """

    changes: dict[str, float | None] = field(default_factory=dict)
    volumes: dict[str, float | None] = field(default_factory=dict)
    source: str = ""
    timestamp: str | None = None
    #: Declared universe size as reported by the provider.  Kept separate from
    #: ``len(changes)`` so a partially successful pagination shows reduced
    #: coverage instead of looking like a complete market.
    total: int | None = None

    def __bool__(self) -> bool:
        return bool(self.changes)


class FuyaoClient:
    """Thin wrapper over the CLI with an injectable runner for tests."""

    def __init__(
        self,
        *,
        explicit_key: str | None = None,
        env_file: Path | None = None,
        binary: str = CLI_BINARY,
        timeout: float = DEFAULT_TIMEOUT,
        cache_dir: Path | None = None,
        runner: Any = None,
    ) -> None:
        self._binary = binary
        self._timeout = timeout
        self._cache_dir = cache_dir
        self._runner = runner or self._default_runner
        key, label = resolve_credential(explicit_key=explicit_key, env_file=env_file)
        self._key = key
        self.credential_source = label

    # -- plumbing ---------------------------------------------------------

    def _default_runner(self, args: Sequence[str]) -> tuple[int, str, str]:
        env = dict(os.environ)
        if self._key:
            env[API_KEY_ENV] = self._key
        try:
            completed = subprocess.run(
                [self._binary, *args],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise FuyaoError(f"调用 {self._binary} 失败: {error}") from error
        return completed.returncode, completed.stdout, completed.stderr

    def call(self, args: Sequence[str]) -> Mapping[str, Any]:
        """Run one CLI command and return its ``data`` mapping."""

        returncode, stdout, stderr = self._runner(args)
        if returncode != 0:
            raise FuyaoError(
                f"{self._binary} 退出码 {returncode}: {(stderr or stdout)[:200]}"
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise FuyaoError(f"响应不是合法 JSON: {error}") from error
        if not isinstance(payload, Mapping):
            raise FuyaoError("响应结构不是对象")
        if payload.get("ok") is False:
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, Mapping) else None
            raise FuyaoError(f"CLI 返回失败: {message or '未知错误'}")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise FuyaoError("响应缺少 data 字段")
        return data

    # -- symbols ----------------------------------------------------------

    def list_symbols(
        self,
        *,
        exchanges: str = "SH,SZ,BJ",
        limit: int = 10000,
    ) -> list[SymbolInfo]:
        """Every listed A-share with its listing date."""

        data = self.call(
            [
                "symbol",
                "list",
                "--exchange",
                exchanges,
                "--limit",
                str(limit),
                "--format",
                "json",
            ]
        )
        items = data.get("item")
        if not isinstance(items, list):
            return []
        rows: list[SymbolInfo] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            thscode = str(item.get("thscode") or "").strip()
            if not thscode:
                continue
            rows.append(
                SymbolInfo(
                    thscode=thscode,
                    name=str(item.get("name") or "").strip(),
                    list_date=_parse_date(item.get("list_date")),
                )
            )
        return rows

    # -- bars -------------------------------------------------------------

    def stock_history(
        self,
        thscodes: Sequence[str],
        start: date,
        end: date,
    ) -> dict[str, list[dict[str, Any]]]:
        """Daily bars per thscode over ``[start, end]``.

        The CLI rejects more than ten codes per call, so the input is chunked.
        """

        result: dict[str, list[dict[str, Any]]] = {}
        codes = [code for code in thscodes if code]
        for index in range(0, len(codes), MAX_BATCH_CODES):
            chunk = codes[index : index + MAX_BATCH_CODES]
            data = self.call(
                [
                    "market",
                    "history-batch",
                    "--thscodes",
                    ",".join(chunk),
                    "--start-ms",
                    str(_to_millis(start)),
                    "--end-ms",
                    str(_to_millis(end)),
                    "--format",
                    "json",
                ]
            )
            items = data.get("item")
            if not isinstance(items, list):
                continue
            for entry in items:
                if not isinstance(entry, Mapping):
                    continue
                thscode = str(entry.get("thscode") or "").strip()
                bars = entry.get("item")
                if thscode and isinstance(bars, list):
                    result[thscode] = [b for b in bars if isinstance(b, Mapping)]
        return result

    # -- industry ---------------------------------------------------------

    def index_constituents(
        self,
        thscode: str,
    ) -> list[str]:
        """Member thscodes of one THS board."""

        data = self.call(
            [
                "index",
                "constituents",
                "--thscode",
                thscode,
                "--format",
                "json",
            ]
        )
        items = data.get("item")
        if not isinstance(items, list):
            return []
        members: list[str] = []
        for item in items:
            if isinstance(item, Mapping):
                code = str(item.get("thscode") or "").strip()
            else:
                code = str(item).strip()
            if code:
                members.append(code)
        return members

    # -- direction --------------------------------------------------------

    def index_snapshot(self, thscodes: Sequence[str]) -> dict[str, float | None]:
        """Per-board percentage change against the previous close.

        One call covers an entire taxonomy level (90 boards at level 1, 230 at
        level 2), so this stays cheap.  A board whose ``price_change_ratio_pct``
        is missing maps to ``None`` rather than 0: "no measurement" must stay
        distinct from "unchanged" downstream.
        """

        codes = [code for code in thscodes if code]
        if not codes:
            return {}
        data = self.call(
            ["index", "snapshot", "--thscodes", ",".join(codes)]
        )
        items = data.get("item")
        if not isinstance(items, list):
            return {}
        changes: dict[str, float | None] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            thscode = str(item.get("thscode") or "").strip()
            if not thscode:
                continue
            changes[thscode] = _optional_float(item.get("price_change_ratio_pct"))
        return changes

    def market_snapshot(
        self,
        *,
        page_size: int = MARKET_PAGE_SIZE,
        max_workers: int = 6,
        max_pages: int = 8,
    ) -> MarketSnapshot:
        """Every A-share's change and volume for the current instant.

        Pages are fetched concurrently because the endpoint is offset-based and
        each page is independent.  Concatenating then keying by thscode keeps
        the map honest if a page overlaps another during a fast-moving market.
        """

        def one(offset: int) -> tuple[list[Mapping[str, Any]], int | None]:
            data = self.call(
                [
                    "market",
                    "snapshot",
                    "--limit",
                    str(page_size),
                    "--offset",
                    str(offset),
                ]
            )
            items = data.get("item")
            rows = (
                [item for item in items if isinstance(item, Mapping)]
                if isinstance(items, list)
                else []
            )
            return rows, _optional_int(data.get("total"))

        offsets = [index * page_size for index in range(max_pages)]
        changes: dict[str, float | None] = {}
        volumes: dict[str, float | None] = {}
        declared: int | None = None
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for batch, page_total in pool.map(one, offsets):
                if page_total is not None:
                    declared = max(declared or 0, page_total)
                if not batch:
                    continue
                for item in batch:
                    thscode = str(item.get("thscode") or "").strip()
                    if not thscode:
                        continue
                    changes[thscode] = _optional_float(item.get("price_change_ratio_pct"))
                    volumes[thscode] = _optional_float(item.get("volume"))
        return MarketSnapshot(
            changes=changes,
            volumes=volumes,
            source="fuyao-market-snapshot",
            timestamp=None,
            total=declared,
        )

    # -- cache ------------------------------------------------------------

    def cache_root(self) -> Path | None:
        return self._cache_dir


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    """Parse an integer, preserving "missing" as ``None``."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_float(value: Any) -> float | None:
    """Parse a number, preserving "missing" as ``None`` instead of 0.0.

    Coercing a missing change to 0 would fabricate a flat stock.  Non-finite
    values are treated as missing for the same reason.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def market_change_map(
    client: "FuyaoClient",
    *,
    fallback: Callable[[], MarketSnapshot] | None = None,
) -> MarketSnapshot:
    """Whole-market change map, with an explicit fallback path.

    The fuyao endpoint is the primary source.  ``fallback`` is injected by the
    caller (the pipeline wires the Sina full-snapshot reader) so this module
    stays unaware of which fallback exists.  When both paths fail the result is
    an empty snapshot rather than an exception: the caller decides how to
    degrade, because losing the benchmark must not abort the whole scan.
    """

    try:
        snapshot = client.market_snapshot()
        if snapshot:
            return snapshot
    except FuyaoError:
        pass
    if fallback is not None:
        try:
            recovered = fallback()
            if recovered:
                return recovered
        except Exception:  # noqa: BLE001 - any fallback failure degrades alike
            pass
    return MarketSnapshot(source="unavailable")


def _to_millis(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=SHANGHAI).timestamp() * 1000)


def filter_by_listing_age(
    rows: Sequence[Any],
    symbols: Mapping[str, SymbolInfo],
    today: date,
    *,
    min_listing_days: int,
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Split rows into (kept, excluded, missing_list_date).

    ``rows`` must expose ``thscode``.  Filtering happens on the candidate pool
    *before* truncation to Top-N, so the caller can still fill the ranking.
    """

    kept: list[Any] = []
    excluded: list[dict[str, Any]] = []
    missing: list[str] = []
    for position, row in enumerate(rows, start=1):
        info = symbols.get(row.thscode)
        if info is None or info.list_date is None:
            missing.append(row.thscode)
            continue
        days = info.listing_days(today)
        if days is None:
            missing.append(row.thscode)
            continue
        if days < min_listing_days:
            excluded.append(
                {
                    "code": row.thscode,
                    "name": getattr(row, "name", ""),
                    "listDate": info.list_date.isoformat(),
                    "listingDays": days,
                    "rankIfUnfiltered": position,
                }
            )
            continue
        kept.append(row)
    return kept, excluded, missing