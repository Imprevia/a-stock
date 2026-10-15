from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import URLError

import pytest

from scripts import hermes_market_collection as caller


STATUS_PATH = "/api/market-environment/collection-runs/run-20261015"
STATUS_URL = f"{caller.BACKEND_BASE_URL}{STATUS_PATH}"


@dataclass(frozen=True)
class RecordedCall:
    method: str
    url: str
    headers: Mapping[str, str]
    timeout_seconds: float


class ScriptedTransport:
    def __init__(self, *actions: caller.HttpResult | BaseException) -> None:
        self.actions = list(actions)
        self.calls: list[RecordedCall] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> caller.HttpResult:
        self.calls.append(
            RecordedCall(
                method=method,
                url=url,
                headers=dict(headers),
                timeout_seconds=timeout_seconds,
            )
        )
        if not self.actions:
            pytest.fail(f"unexpected transport call: {method} {url}")
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def result(
    status: int,
    payload: Mapping[str, Any] | None,
    *,
    headers: Mapping[str, str] | None = None,
) -> caller.HttpResult:
    return caller.HttpResult(status=status, headers=headers or {}, payload=payload)


def run_payload(status: str = "success") -> dict[str, Any]:
    return {
        "outcome": "run",
        "targetDate": "2026-10-15",
        "runId": "run-20261015",
        "status": status,
        "statusUrl": STATUS_PATH,
        "tasks": [
            {
                "dataset": "core",
                "status": "success",
                "source": "tdx",
                "observations": 3,
                "durationMs": 12.5,
                "warning": None,
                "failure": None,
            }
        ],
    }


def invoke(transport: ScriptedTransport, **overrides: Any) -> dict[str, Any]:
    return caller.run(
        now=datetime(2026, 10, 15, 16, 30, tzinfo=caller.SHANGHAI_TIME_ZONE),
        transport=transport,
        sleeper=overrides.pop("sleeper", lambda _: None),
        monotonic_clock=overrides.pop("monotonic_clock", lambda: 0.0),
        **overrides,
    )


def test_http_200_terminal_response_is_normalized_without_raw_fields() -> None:
    payload = run_payload()
    payload["rawResponse"] = "RAW-SECRET"
    payload["traceback"] = "TRACEBACK-SECRET"
    payload["tasks"][0]["providerPayload"] = "PROVIDER-SECRET"
    transport = ScriptedTransport(result(200, payload))

    output = invoke(transport)

    assert output == {
        "schemaVersion": caller.SCHEMA_VERSION,
        "kind": "run",
        "targetDate": "2026-10-15",
        "runId": "run-20261015",
        "status": "success",
        "statusUrl": STATUS_URL,
        "httpStatus": 200,
        "message": None,
        "idempotencyKey": "hermes-market-collection-2026-10-15-1630",
        "uncertainReplay": False,
        "retryable": False,
        "tasks": [
            {
                "dataset": "core",
                "status": "success",
                "source": "tdx",
                "observations": 3,
                "durationMs": 12.5,
                "warning": None,
                "failure": None,
            }
        ],
    }
    encoded = json.dumps(output)
    assert "RAW-SECRET" not in encoded
    assert "TRACEBACK-SECRET" not in encoded
    assert "PROVIDER-SECRET" not in encoded
    assert len(transport.calls) == 1


def test_http_202_polls_only_status_url_and_never_posts_again() -> None:
    clock = FakeClock()
    active = run_payload("collecting")
    terminal = run_payload("partial")
    terminal["tasks"][0]["status"] = "failed"
    terminal["tasks"][0]["failure"] = {
        "category": "provider-unavailable",
        "message": "数据源暂不可用",
        "retryable": True,
        "retained": False,
        "raw": "DO-NOT-COPY",
    }
    transport = ScriptedTransport(result(202, active), result(200, terminal))

    output = invoke(
        transport,
        sleeper=clock.sleep,
        monotonic_clock=clock.monotonic,
        poll_budget_seconds=10,
        poll_interval_seconds=2,
    )

    assert output["kind"] == "run"
    assert output["status"] == "partial"
    assert output["tasks"][0]["failure"] == {
        "category": "provider-unavailable",
        "message": "数据源暂不可用",
        "retryable": True,
        "retained": False,
    }
    assert [call.method for call in transport.calls] == ["POST", "GET"]
    assert transport.calls[1].url == STATUS_URL
    assert "Idempotency-Key" not in transport.calls[1].headers


@pytest.mark.parametrize("status", [409, 422])
def test_conflict_and_pre_settlement_responses_are_rejected(status: int) -> None:
    transport = ScriptedTransport(
        result(status, {"detail": {"code": "rejected", "message": "请求被拒绝"}})
    )

    output = invoke(transport)

    assert output["kind"] == "rejected"
    assert output["status"] == "rejected"
    assert output["httpStatus"] == status
    assert output["message"] == "请求被拒绝"
    assert output["retryable"] is False
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_capacity_and_server_failures_are_retryable_endpoint_errors(status: int) -> None:
    transport = ScriptedTransport(result(status, {"detail": "服务暂不可用"}))

    output = invoke(transport)

    assert output["kind"] == "endpoint-error"
    assert output["status"] == "error"
    assert output["httpStatus"] == status
    assert output["message"] == "服务暂不可用"
    assert output["retryable"] is True
    assert len(transport.calls) == 1


def test_uncertain_first_post_is_replayed_once_with_same_key_and_zero_wait() -> None:
    transport = ScriptedTransport(
        caller.TransportFailure("socket response was lost: RAW-SECRET"),
        result(200, run_payload()),
    )

    output = invoke(transport)

    assert output["kind"] == "run"
    assert output["uncertainReplay"] is True
    assert [call.method for call in transport.calls] == ["POST", "POST"]
    assert transport.calls[0].url.endswith("waitTimeoutSeconds=900")
    assert transport.calls[1].url.endswith("waitTimeoutSeconds=0")
    assert (
        transport.calls[0].headers["Idempotency-Key"]
        == transport.calls[1].headers["Idempotency-Key"]
        == "hermes-market-collection-2026-10-15-1630"
    )


def test_completely_unreachable_endpoint_stops_after_one_uncertain_replay() -> None:
    transport = ScriptedTransport(
        caller.TransportFailure("initial RAW-SECRET"),
        caller.TransportFailure("replay RAW-SECRET"),
    )

    output = invoke(transport)

    assert output["kind"] == "endpoint-unreachable"
    assert output["status"] == "unreachable"
    assert output["uncertainReplay"] is True
    assert output["retryable"] is True
    assert output["message"] == "无法连接后端：TransportFailure"
    assert "RAW-SECRET" not in json.dumps(output)
    assert [call.method for call in transport.calls] == ["POST", "POST"]


def test_server_skipped_response_is_terminal_and_not_polled() -> None:
    transport = ScriptedTransport(
        result(
            200,
            {
                "outcome": "skipped",
                "targetDate": "2026-10-15",
                "runId": None,
                "status": "skipped",
                "statusUrl": None,
                "reason": "非交易日",
                "tasks": [],
            },
        )
    )

    output = invoke(transport)

    assert output["kind"] == "skipped"
    assert output["status"] == "skipped"
    assert output["message"] == "非交易日"
    assert output["runId"] is None
    assert len(transport.calls) == 1


def test_after_1700_is_skipped_locally_without_any_network_call() -> None:
    transport = ScriptedTransport()

    output = caller.run(
        now=datetime(2026, 10, 15, 17, 0, 1, tzinfo=caller.SHANGHAI_TIME_ZONE),
        transport=transport,
    )

    assert output["kind"] == "skipped"
    assert output["status"] == "skipped"
    assert output["httpStatus"] is None
    assert "17:00" in output["message"]
    assert transport.calls == []


def test_poll_budget_exhaustion_reports_still_running_without_another_post() -> None:
    clock = FakeClock()
    active = run_payload("collecting")
    transport = ScriptedTransport(
        result(202, active),
        result(200, active),
        result(200, active),
    )

    output = invoke(
        transport,
        sleeper=clock.sleep,
        monotonic_clock=clock.monotonic,
        poll_budget_seconds=10,
        poll_interval_seconds=5,
    )

    assert output["kind"] == "still-running"
    assert output["status"] == "collecting"
    assert output["runId"] == "run-20261015"
    assert output["httpStatus"] == 202
    assert [call.method for call in transport.calls] == ["POST", "GET", "GET"]
    assert clock.sleeps == [5, 5]


def test_schedule_slot_key_uses_shanghai_calendar_date() -> None:
    utc_time = datetime(2026, 10, 15, 16, 45, tzinfo=timezone.utc)

    assert (
        caller.schedule_slot_key(utc_time)
        == "hermes-market-collection-2026-10-16-1630"
    )


@pytest.mark.parametrize(
    "untrusted_url",
    [
        "http://192.168.1.21:32001/api/market-environment/collection-runs/run-1",
        "http://192.168.1.20:32001.evil.invalid/api/market-environment/collection-runs/run-1",
        "https://192.168.1.20:32001/api/market-environment/collection-runs/run-1",
        "http://192.168.1.20:32001/not-a-status-path",
        "http://[invalid-host/api/market-environment/collection-runs/run-1",
    ],
)
def test_untrusted_status_url_is_not_followed_or_copied_to_output(
    untrusted_url: str,
) -> None:
    payload = run_payload("queued")
    payload["statusUrl"] = untrusted_url
    transport = ScriptedTransport(result(202, payload))

    output = invoke(transport, poll_budget_seconds=10, poll_interval_seconds=1)

    assert output["kind"] == "endpoint-error"
    assert output["statusUrl"] is None
    assert output["message"] == "statusUrl 不属于已配置的后端地址"
    assert len(transport.calls) == 1


def test_untrusted_location_header_is_not_followed() -> None:
    payload = run_payload("queued")
    payload.pop("statusUrl")
    transport = ScriptedTransport(
        result(
            202,
            payload,
            headers={"Location": "http://attacker.invalid/collection-runs/run-1"},
        )
    )

    output = invoke(transport, poll_budget_seconds=10, poll_interval_seconds=1)

    assert output["kind"] == "endpoint-error"
    assert output["statusUrl"] is None
    assert len(transport.calls) == 1


def test_transport_sanitizes_url_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(*args: Any, **kwargs: Any) -> None:
        raise URLError("RAW-CONNECTION-SECRET")

    monkeypatch.setattr(caller, "urlopen", fail_urlopen)

    with pytest.raises(caller.TransportFailure) as raised:
        caller.UrllibJsonTransport().request(
            "POST",
            "http://example.invalid",
            headers={},
            timeout_seconds=1,
        )

    assert str(raised.value) == "无法连接后端：str"
    assert "RAW-CONNECTION-SECRET" not in str(raised.value)


def test_main_never_prints_exception_text_or_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run() -> dict[str, Any]:
        raise RuntimeError("RAW-INTERNAL-SECRET")

    monkeypatch.setattr(caller, "run", fail_run)

    assert caller.main() == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["kind"] == "caller-error"
    assert output["message"] == "caller 内部错误：RuntimeError"
    assert "RAW-INTERNAL-SECRET" not in captured.out
    assert "Traceback" not in captured.out
    assert captured.err == ""
