"""Thin wrapper around the official ``hithink-finance`` CLI.

The skill deliberately does not implement its own HTTP client: the official
CLI owns endpoint contracts, paging and parameter validation.  This module only
adds prerequisite checks, bounded retry, batching and credential redaction.

The API key travels in the child process environment, never in argv, so it
cannot leak through shell history or process listings.  It is resolved from
``FUYAO_API_KEY`` (process env) and otherwise from ``deploy/truenas/deploy.env``,
which is git-ignored; the file is read for that single key only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from scoring import Bar, normalize_bars

SHANGHAI = ZoneInfo("Asia/Shanghai")

API_KEY_ENV = "FUYAO_API_KEY"
LEGACY_API_KEY_ENV = "MARKET_ENVIRONMENT_FUYAO_API_KEY"
CLI_BINARY = "hithink-finance"
CLI_KEY_ENV = "HITHINK_FINANCE_API_KEY"

ENV_FILE_RELATIVE = Path("deploy") / "truenas" / "deploy.env"
ENV_FILE_VAR = "FUYAO_API_KEY"

MAX_BATCH_CODES = 10
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_FACTOR = 2.0
MAX_BACKOFF_SECONDS = 8.0

RATE_LIMIT_CODES = {4001, 429}


class FuyaoError(RuntimeError):
    """Base error carrying a machine-readable quality status."""

    status = "degraded"

    def __init__(self, message: str, *, code: Any = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class FuyaoInsufficient(FuyaoError):
    """Inputs are missing; no conclusion can be produced."""

    status = "insufficient"


class FuyaoDegraded(FuyaoError):
    """Data was partially obtained but the result is not trustworthy."""

    status = "degraded"


def parse_env_file(path: Path, variable: str) -> str | None:
    """Read a single variable from a dotenv-style file.

    Supports ``KEY=value``, ``export KEY=value``, quoted values and trailing
    ``#`` comments.  Only the requested key is returned; the file may contain
    unrelated secrets and is never echoed.
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        else:
            marker = value.find(" #")
            if marker != -1:
                value = value[:marker].rstrip()
        return value.strip() or None
    return None


def find_env_file(start: Path | None = None) -> Path | None:
    """Walk up from the script location to locate ``deploy/truenas/deploy.env``."""

    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        target = candidate / ENV_FILE_RELATIVE
        if target.is_file():
            return target
    return None


def resolve_credential(
    *,
    explicit_key: str | None = None,
    env_file: Path | None = None,
    search_env_file: bool = True,
) -> tuple[str | None, str]:
    """Resolve the fuyao key and label where it came from (never the value).

    Order: explicit argument, ``FUYAO_API_KEY`` process env, legacy
    ``MARKET_ENVIRONMENT_FUYAO_API_KEY`` process env, then the deploy env file.
    """

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


def _redact(text: str, secret: str | None) -> str:
    if not secret:
        return text
    redacted = text.replace(secret, "***")
    # Also drop long contiguous slices in case a message embeds a fragment.
    if len(secret) >= 8:
        for size in (16, 12, 8):
            if len(secret) >= size:
                redacted = redacted.replace(secret[:size], "***")
                redacted = redacted.replace(secret[-size:], "***")
    return redacted


@dataclass
class CallRecord:
    command: str
    attempts: int = 1
    ok: bool = True
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"command": self.command, "attempts": self.attempts, "ok": self.ok, "note": self.note}


@dataclass
class FuyaoClient:
    """CLI-backed client with injectable runner and sleeper for tests."""

    api_key: str | None = None
    env_file: Path | None | bool = None
    binary: str = CLI_BINARY
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base: float = DEFAULT_BACKOFF_BASE
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    runner: Callable[..., Any] | None = None
    sleeper: Callable[[float], None] = time.sleep
    calls: list[CallRecord] = field(default_factory=list)
    credential_source: str = "unresolved"

    def __post_init__(self) -> None:
        if self.api_key is None:
            key, label = resolve_credential(
                env_file=self.env_file,
                search_env_file=self.env_file is not False,
            )
            self.api_key = key or ""
            self.credential_source = label
        else:
            self.credential_source = "explicit"

    # ------------------------------------------------------------------
    # prerequisites
    # ------------------------------------------------------------------
    def resolve_binary(self) -> str:
        """Return the CLI path or raise ``FuyaoInsufficient``."""

        found = shutil.which(self.binary)
        if not found:
            raise FuyaoInsufficient(
                f"`{self.binary}` 不在 PATH 中；请安装 @hithink-tech/hithink-finance-cli "
                "（需要 Node.js 22.12+）后重试"
            )
        return found

    def require_key(self) -> str:
        key = (self.api_key or "").strip()
        if not key:
            raise FuyaoInsufficient(
                f"未找到 fuyao 凭据：请设置 {API_KEY_ENV}，"
                f"或在 {ENV_FILE_RELATIVE.as_posix()} 中配置 {ENV_FILE_VAR}"
            )
        return key

    def check_prerequisites(self) -> dict[str, Any]:
        """Validate binary and credentials before any network call."""

        binary = self.resolve_binary()
        self.require_key()
        return {
            "binary": binary,
            "credentialEnv": CLI_KEY_ENV,
            "credentialSource": self.credential_source,
            "ready": True,
        }

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    def _invoke(self, args: Sequence[str]) -> tuple[int, str, str]:
        runner = self.runner or subprocess.run
        env = dict(os.environ)
        env[CLI_KEY_ENV] = self.require_key()
        completed = runner(
            [self.binary, *args],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
            env=env,
        )
        return (
            int(getattr(completed, "returncode", 0) or 0),
            getattr(completed, "stdout", "") or "",
            getattr(completed, "stderr", "") or "",
        )

    def _parse(self, stdout: str, stderr: str, returncode: int, command: str) -> Mapping[str, Any]:
        text = (stdout or "").strip()
        if not text:
            raise FuyaoDegraded(
                _redact(f"{command} 无输出（exit={returncode}）：{(stderr or '').strip()[:200]}", self.api_key)
            )
        # The CLI may print warnings on stderr; stdout stays pure JSON.
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise FuyaoDegraded(
                _redact(f"{command} 输出不是合法 JSON：{error}；片段={text[:200]}", self.api_key)
            ) from error
        if not isinstance(payload, Mapping):
            raise FuyaoDegraded(f"{command} 输出不是对象信封")
        return payload

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> Any:
        error = payload.get("error")
        if isinstance(error, Mapping):
            return error.get("code")
        return payload.get("code")

    @staticmethod
    def _error_message(payload: Mapping[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or "")
        return str(payload.get("message") or "")

    def call(self, command: str, args: Sequence[str]) -> Mapping[str, Any]:
        """Run one CLI command and return its ``data`` mapping.

        Retries only on rate-limit evidence, with bounded exponential backoff.
        """

        attempts = 0
        last: FuyaoError | None = None
        while attempts <= self.max_retries:
            attempts += 1
            try:
                returncode, stdout, stderr = self._invoke(args)
            except subprocess.TimeoutExpired as error:
                last = FuyaoDegraded(_redact(f"{command} 超时（{self.timeout}s）", self.api_key))
                self.calls.append(CallRecord(command, attempts, False, "timeout"))
                break
            except FileNotFoundError as error:
                raise FuyaoInsufficient(f"无法执行 `{self.binary}`：{error}") from error

            payload = self._parse(stdout, stderr, returncode, command)
            if bool(payload.get("ok")):
                self.calls.append(CallRecord(command, attempts, True))
                data = payload.get("data")
                return data if isinstance(data, Mapping) else {}

            code = self._error_code(payload)
            message = _redact(self._error_message(payload), self.api_key)
            rate_limited = False
            try:
                rate_limited = int(code) in RATE_LIMIT_CODES
            except (TypeError, ValueError):
                rate_limited = False
            if rate_limited and attempts <= self.max_retries:
                delay = min(self.backoff_base * (self.backoff_factor ** (attempts - 1)), MAX_BACKOFF_SECONDS)
                self.sleeper(delay)
                last = FuyaoDegraded(f"{command} 触发限流 code={code}：{message}", code=code, retryable=True)
                continue
            if rate_limited:
                self.calls.append(CallRecord(command, attempts, False, f"rate-limit code={code}"))
                raise FuyaoDegraded(f"{command} 重试耗尽仍被限流 code={code}：{message}", code=code)
            self.calls.append(CallRecord(command, attempts, False, f"code={code}"))
            raise FuyaoDegraded(f"{command} 失败 code={code}：{message}", code=code)
        self.calls.append(CallRecord(command, attempts, False, "unreachable"))
        raise last or FuyaoDegraded(f"{command} 失败")

    # ------------------------------------------------------------------
    # high-level commands
    # ------------------------------------------------------------------
    def list_industries(self) -> list[dict[str, str]]:
        data = self.call("index.catalog", ["index", "catalog", "--tag", "industry", "--format", "json"])
        rows = data.get("item")
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                code = str(row.get("thscode") or "").strip().upper()
                name = str(row.get("name") or "").strip()
                if not code or not name or code in seen:
                    continue
                seen.add(code)
                result.append({"thscode": code, "name": name})
        if not result:
            raise FuyaoInsufficient("fuyao 未返回任何 industry 板块")
        return result

    @staticmethod
    def _to_millis(value: date) -> int:
        return int(datetime(value.year, value.month, value.day, tzinfo=SHANGHAI).timestamp() * 1000)

    def industry_history_batch(
        self, codes: Sequence[str], start: date, end: date
    ) -> dict[str, list[Bar]]:
        return self._history_batch(
            ["index", "history-batch"],
            "index.history-batch",
            codes,
            start,
            end,
            extra=[],
        )

    def stock_history_batch(
        self, codes: Sequence[str], start: date, end: date
    ) -> dict[str, list[Bar]]:
        return self._history_batch(
            ["market", "history-batch"],
            "market.history-batch",
            codes,
            start,
            end,
            extra=["--adjust", "forward", "--interval", "1d"],
        )

    def _history_batch(
        self,
        base: Sequence[str],
        command_id: str,
        codes: Sequence[str],
        start: date,
        end: date,
        *,
        extra: Sequence[str],
    ) -> dict[str, list[Bar]]:
        unique = list(dict.fromkeys(code.strip().upper() for code in codes if code.strip()))
        if not unique:
            return {}
        result: dict[str, list[Bar]] = {}
        start_ms = self._to_millis(start)
        end_ms = self._to_millis(end)
        for offset in range(0, len(unique), MAX_BATCH_CODES):
            chunk = unique[offset : offset + MAX_BATCH_CODES]
            data = self.call(
                command_id,
                [
                    *base,
                    "--thscodes",
                    ",".join(chunk),
                    "--start-ms",
                    str(start_ms),
                    "--end-ms",
                    str(end_ms),
                    *extra,
                    "--format",
                    "json",
                ],
            )
            groups = data.get("item")
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                code = str(group.get("thscode") or "").strip().upper()
                rows = group.get("item")
                if not code or not isinstance(rows, list):
                    continue
                result[code] = normalize_bars(row for row in rows if isinstance(row, Mapping))
        return result

    def constituents(self, thscode: str) -> list[dict[str, str]]:
        data = self.call(
            "index.constituents",
            ["index", "constituents", "--thscode", thscode, "--format", "json"],
        )
        rows = data.get("item")
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                code = str(row.get("thscode") or "").strip().upper()
                if not code or code in seen:
                    continue
                seen.add(code)
                result.append({"thscode": code, "name": str(row.get("name") or "").strip()})
        return result