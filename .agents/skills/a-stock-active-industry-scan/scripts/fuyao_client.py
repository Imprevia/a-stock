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
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

API_KEY_ENV = "FUYAO_API_KEY"
LEGACY_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
CLI_BINARY = "hithink-finance"
ENV_FILE_VAR = "FUYAO_API_KEY"
ENV_FILE_RELATIVE = Path("deploy") / "truenas" / "deploy.env"

DEFAULT_TIMEOUT = 120.0
MAX_BATCH_CODES = 10

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