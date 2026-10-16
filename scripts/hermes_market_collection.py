#!/usr/bin/env python3
"""Deterministic Hermes caller for the trusted-LAN full-collection endpoint.

The script is intentionally self-contained so the reviewed file can be copied
into ``HERMES_HOME/scripts`` without installing the application package.  It
prints exactly one normalized JSON object for the Hermes reporting prompt.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as wall_time
from http.client import RemoteDisconnected
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BACKEND_BASE_URL = "http://192.168.1.20:32001"
FULL_COLLECTION_PATH = "/api/market-environment/collection-runs/full"
SHANGHAI_TIME_ZONE = ZoneInfo("Asia/Shanghai")
SCHEDULE_TIME = wall_time(15, 30)
CATCH_UP_DEADLINE = wall_time(16, 0)
INITIAL_WAIT_SECONDS = 900
INITIAL_HTTP_TIMEOUT_SECONDS = 930
REPLAY_HTTP_TIMEOUT_SECONDS = 30
POLL_HTTP_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 15
POLL_BUDGET_SECONDS = 600
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TERMINAL_RUN_STATUSES = frozenset({"success", "partial", "failed"})
SCHEMA_VERSION = "hermes-market-collection/v1"


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    payload: Mapping[str, Any] | None


class TransportFailure(RuntimeError):
    """The caller cannot know whether the backend received the request."""


class JsonTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResult: ...


class UrllibJsonTransport:
    """Small standard-library JSON transport with known HTTP errors preserved."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResult:
        request = Request(
            url,
            data=b"" if method == "POST" else None,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return HttpResult(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    payload=_decode_payload(response.read(MAX_RESPONSE_BYTES + 1)),
                )
        except HTTPError as error:
            return HttpResult(
                status=int(error.code),
                headers=dict(error.headers.items()) if error.headers else {},
                payload=_decode_payload(error.read(MAX_RESPONSE_BYTES + 1)),
            )
        except (URLError, TimeoutError, socket.timeout, RemoteDisconnected, OSError) as error:
            raise TransportFailure(_safe_transport_message(error)) from error


def schedule_slot_key(now: datetime) -> str:
    current = _shanghai_now(now)
    return (
        "hermes-market-collection-"
        f"{current.date().isoformat()}-{SCHEDULE_TIME.strftime('%H%M')}"
    )


def run(
    *,
    now: datetime | None = None,
    transport: JsonTransport | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic_clock: Callable[[], float] = time.monotonic,
    poll_budget_seconds: float = POLL_BUDGET_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Invoke once, recover an uncertain response once, then provider-free poll."""

    current = _shanghai_now(now or datetime.now(tz=SHANGHAI_TIME_ZONE))
    key = schedule_slot_key(current)
    if current.time().replace(tzinfo=None) > CATCH_UP_DEADLINE:
        return _base_result(
            kind="skipped",
            target_date=current.date().isoformat(),
            status="skipped",
            message="已超过上海时间 16:00，不补跑 15:30 的采集时隙",
            idempotency_key=key,
        )
    if poll_budget_seconds < 0 or poll_interval_seconds <= 0:
        raise ValueError("poll budget must be non-negative and interval must be positive")

    client = transport or UrllibJsonTransport()
    headers = {
        "Accept": "application/json",
        "Idempotency-Key": key,
        "User-Agent": "a-stock-hermes-market-collection/1",
    }
    initial_url = _full_collection_url(INITIAL_WAIT_SECONDS)
    uncertain_replay = False
    try:
        response = client.request(
            "POST",
            initial_url,
            headers=headers,
            timeout_seconds=INITIAL_HTTP_TIMEOUT_SECONDS,
        )
    except TransportFailure:
        uncertain_replay = True
        try:
            response = client.request(
                "POST",
                _full_collection_url(0),
                headers=headers,
                timeout_seconds=REPLAY_HTTP_TIMEOUT_SECONDS,
            )
        except TransportFailure as error:
            return _base_result(
                kind="endpoint-unreachable",
                target_date=current.date().isoformat(),
                status="unreachable",
                message=_transport_failure_message(error),
                idempotency_key=key,
                uncertain_replay=True,
                retryable=True,
            )

    return _handle_post_response(
        response,
        key=key,
        fallback_target_date=current.date().isoformat(),
        uncertain_replay=uncertain_replay,
        transport=client,
        headers=headers,
        sleeper=sleeper,
        monotonic_clock=monotonic_clock,
        poll_budget_seconds=poll_budget_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def _handle_post_response(
    response: HttpResult,
    *,
    key: str,
    fallback_target_date: str,
    uncertain_replay: bool,
    transport: JsonTransport,
    headers: Mapping[str, str],
    sleeper: Callable[[float], None],
    monotonic_clock: Callable[[], float],
    poll_budget_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    payload = response.payload
    if response.status in {200, 202} and isinstance(payload, Mapping):
        if payload.get("outcome") == "skipped" or payload.get("status") == "skipped":
            return _normalize_payload(
                payload,
                kind="skipped",
                http_status=response.status,
                idempotency_key=key,
                uncertain_replay=uncertain_replay,
            )
        if response.status == 200:
            return _normalize_payload(
                payload,
                kind="run",
                http_status=response.status,
                idempotency_key=key,
                uncertain_replay=uncertain_replay,
            )
        status_url = _status_url(payload, response.headers)
        if status_url is None:
            return _contract_error(
                response.status,
                payload,
                target_date=fallback_target_date,
                idempotency_key=key,
                uncertain_replay=uncertain_replay,
                message="HTTP 202 响应缺少可用的 statusUrl",
            )
        return _poll_run(
            payload,
            status_url=status_url,
            key=key,
            uncertain_replay=uncertain_replay,
            transport=transport,
            headers=headers,
            sleeper=sleeper,
            monotonic_clock=monotonic_clock,
            poll_budget_seconds=poll_budget_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    kind = "rejected" if response.status in {400, 403, 409, 422} else "endpoint-error"
    return _base_result(
        kind=kind,
        target_date=_target_date(payload) or fallback_target_date,
        run_id=_string(payload, "runId"),
        status="rejected" if kind == "rejected" else "error",
        status_url=_string(payload, "statusUrl"),
        http_status=response.status,
        message=_error_message(payload, response.status),
        idempotency_key=key,
        uncertain_replay=uncertain_replay,
        retryable=response.status == 429 or response.status >= 500,
    )


def _poll_run(
    initial_payload: Mapping[str, Any],
    *,
    status_url: str,
    key: str,
    uncertain_replay: bool,
    transport: JsonTransport,
    headers: Mapping[str, str],
    sleeper: Callable[[float], None],
    monotonic_clock: Callable[[], float],
    poll_budget_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    absolute_status_url = _trusted_status_url(status_url)
    if absolute_status_url is None:
        return _contract_error(
            202,
            initial_payload,
            target_date=_target_date(initial_payload),
            idempotency_key=key,
            uncertain_replay=uncertain_replay,
            message="statusUrl 不属于已配置的后端地址",
        )

    latest: Mapping[str, Any] = initial_payload
    deadline = monotonic_clock() + poll_budget_seconds
    last_error: str | None = None
    while monotonic_clock() < deadline:
        sleeper(min(poll_interval_seconds, max(0.0, deadline - monotonic_clock())))
        try:
            response = transport.request(
                "GET",
                absolute_status_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": headers["User-Agent"],
                },
                timeout_seconds=POLL_HTTP_TIMEOUT_SECONDS,
            )
        except TransportFailure as error:
            last_error = _transport_failure_message(error)
            continue
        if response.status == 200 and isinstance(response.payload, Mapping):
            latest = response.payload
            last_error = None
            if str(latest.get("status")) in TERMINAL_RUN_STATUSES:
                return _normalize_payload(
                    latest,
                    kind="run",
                    http_status=200,
                    idempotency_key=key,
                    uncertain_replay=uncertain_replay,
                    status_url=status_url,
                )
            continue
        last_error = _error_message(response.payload, response.status)

    if last_error is not None:
        return _base_result(
            kind="endpoint-error",
            target_date=_target_date(latest),
            run_id=_string(latest, "runId"),
            status="error",
            status_url=status_url,
            message=last_error,
            idempotency_key=key,
            uncertain_replay=uncertain_replay,
            retryable=True,
        )
    return _normalize_payload(
        latest,
        kind="still-running",
        http_status=202,
        idempotency_key=key,
        uncertain_replay=uncertain_replay,
        status_url=status_url,
    )


def _normalize_payload(
    payload: Mapping[str, Any],
    *,
    kind: str,
    http_status: int,
    idempotency_key: str,
    uncertain_replay: bool,
    status_url: str | None = None,
) -> dict[str, Any]:
    tasks = payload.get("tasks")
    normalized_tasks = [
        _normalize_task(task)
        for task in tasks if isinstance(task, Mapping)
    ] if isinstance(tasks, list) else []
    return _base_result(
        kind=kind,
        target_date=_target_date(payload),
        run_id=_string(payload, "runId"),
        status=_string(payload, "status") or "unknown",
        status_url=status_url or _string(payload, "statusUrl"),
        http_status=http_status,
        message=_string(payload, "reason"),
        idempotency_key=idempotency_key,
        uncertain_replay=uncertain_replay,
        retryable=False,
        tasks=normalized_tasks,
    )


def _normalize_task(task: Mapping[str, Any]) -> dict[str, Any]:
    failure = task.get("failure")
    safe_failure = None
    if isinstance(failure, Mapping):
        safe_failure = {
            "category": _string(failure, "category"),
            "message": _string(failure, "message"),
            "retryable": bool(failure.get("retryable")),
            "retained": bool(failure.get("retained")),
        }
    return {
        "dataset": _string(task, "dataset"),
        "status": _string(task, "status") or "unknown",
        "source": _string(task, "source"),
        "observations": _non_negative_int(task.get("observations")),
        "durationMs": _non_negative_number(task.get("durationMs")),
        "warning": _string(task, "warning"),
        "failure": safe_failure,
    }


def _base_result(
    *,
    kind: str,
    target_date: str | None,
    status: str,
    message: str | None,
    idempotency_key: str,
    run_id: str | None = None,
    status_url: str | None = None,
    http_status: int | None = None,
    uncertain_replay: bool = False,
    retryable: bool = False,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "targetDate": target_date,
        "runId": run_id,
        "status": status,
        "statusUrl": _trusted_status_url(status_url) if status_url else None,
        "httpStatus": http_status,
        "message": message,
        "idempotencyKey": idempotency_key,
        "uncertainReplay": uncertain_replay,
        "retryable": retryable,
        "tasks": tasks or [],
    }


def _contract_error(
    http_status: int,
    payload: Mapping[str, Any],
    *,
    target_date: str | None,
    idempotency_key: str,
    uncertain_replay: bool,
    message: str,
) -> dict[str, Any]:
    return _base_result(
        kind="endpoint-error",
        target_date=target_date,
        run_id=_string(payload, "runId"),
        status="error",
        status_url=_string(payload, "statusUrl"),
        http_status=http_status,
        message=message,
        idempotency_key=idempotency_key,
        uncertain_replay=uncertain_replay,
        retryable=False,
    )


def _full_collection_url(wait_seconds: int) -> str:
    return (
        f"{BACKEND_BASE_URL}{FULL_COLLECTION_PATH}?"
        + urlencode({"waitTimeoutSeconds": wait_seconds})
    )


def _trusted_status_url(value: str) -> str | None:
    try:
        candidate = urljoin(f"{BACKEND_BASE_URL}/", value)
        expected = urlsplit(BACKEND_BASE_URL)
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
        return None
    if not parsed.path.startswith("/api/market-environment/collection-runs/"):
        return None
    return candidate


def _status_url(
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
) -> str | None:
    direct = _string(payload, "statusUrl")
    if direct:
        return direct
    for name, value in headers.items():
        if name.lower() == "location" and str(value).strip():
            return str(value).strip()
    return None


def _target_date(payload: Mapping[str, Any] | None) -> str | None:
    return _string(payload, "targetDate") or _string(payload, "asOf")


def _error_message(payload: Mapping[str, Any] | None, status: int) -> str:
    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, Mapping):
            message = _string(detail, "message") or _string(detail, "code")
            if message:
                return message
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        message = _string(payload, "message")
        if message:
            return message
    return f"后端返回 HTTP {status}"


def _decode_payload(raw: bytes) -> Mapping[str, Any] | None:
    if len(raw) > MAX_RESPONSE_BYTES:
        return {"message": "后端响应超过大小限制"}
    if not raw:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"message": "后端返回的不是有效 JSON"}
    return value if isinstance(value, Mapping) else {"message": "后端 JSON 必须是对象"}


def _safe_transport_message(error: BaseException) -> str:
    if isinstance(error, URLError) and error.reason is not None:
        reason = error.reason
        return f"无法连接后端：{type(reason).__name__}"
    return f"无法连接后端：{type(error).__name__}"


def _transport_failure_message(error: TransportFailure) -> str:
    """Retain messages produced by our transport without echoing arbitrary details."""

    message = str(error)
    if message.startswith("无法连接后端：") and len(message) <= 96:
        return message
    return "无法连接后端：TransportFailure"


def _string(payload: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _non_negative_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value


def _shanghai_now(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TIME_ZONE)
    return value.astimezone(SHANGHAI_TIME_ZONE)


def main() -> int:
    try:
        result = run()
    except Exception as error:  # Last-resort normalized output; never print a stack.
        current = datetime.now(tz=SHANGHAI_TIME_ZONE)
        result = _base_result(
            kind="caller-error",
            target_date=current.date().isoformat(),
            status="error",
            message=f"caller 内部错误：{type(error).__name__}",
            idempotency_key=schedule_slot_key(current),
            retryable=False,
        )
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
