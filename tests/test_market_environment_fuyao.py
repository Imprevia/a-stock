from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests

from src.market_environment.fuyao import (
    FuyaoClient,
    FuyaoConfigurationError,
    FuyaoContractError,
    FuyaoLimitDataset,
    FuyaoNonTradingDayError,
    FuyaoPermissionError,
    FuyaoPoolResult,
    FuyaoTransportError,
)
from src.market_environment.providers import MarketDataProvider


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/market-environment/fuyao-limit-pools.json").read_text(
        encoding="utf-8"
    )
)
AS_OF = date(2026, 9, 18)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FixtureSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params, headers, timeout, allow_redirects):
        assert allow_redirects is False
        self.calls.append((urlparse(url).path, dict(params), dict(headers), timeout))
        path = urlparse(url).path
        if path.endswith("/calendar/trading-days"):
            payload = FIXTURE["calendar"]
        elif path.endswith("/meta/tickers/list"):
            payload = FIXTURE["tickers"]
        elif path.endswith("/limit-up-pool"):
            payload = FIXTURE["limit_up_pages"][int(params["page"]) - 1]
        elif path.endswith("/limit-down-pool"):
            payload = FIXTURE["limit_down"]
        elif path.endswith("/limit-break-pool"):
            payload = FIXTURE["limit_break"]
        else:
            raise AssertionError(path)
        return FakeResponse(payload)


def fixture_client(session=None, **kwargs):
    client = FuyaoClient(
        "fixture-key",
        session=session or FixtureSession(),
        sleep=lambda _delay: None,
        **kwargs,
    )
    client._PAGE_SIZE = 2
    return client


def test_fetches_calendar_tickers_and_all_pool_pages_with_shanghai_date_ms():
    session = FixtureSession()
    client = fixture_client(session)

    result = client.fetch_limit_dataset(AS_OF)

    assert tuple(result.pools) == ("limit_up", "failed_limit_up", "limit_down")
    assert result.pools["limit_up"].total == 3
    assert len(result.pools["limit_up"].rows) == 3
    assert result.pools["failed_limit_up"].total == 1
    assert result.pools["limit_down"].rows == ()
    assert set(result.tickers) == {"600001.SH", "000001.SZ", "430001.BJ"}
    pool_calls = [call for call in session.calls if "special-data" in call[0]]
    assert len(pool_calls) == 4
    assert all(call[1]["date_ms"] == 1789660800000 for call in pool_calls)
    assert all(call[1]["size"] == 2 for call in pool_calls)
    assert all(call[2] == {"X-api-key": "fixture-key"} for call in session.calls)


def test_non_trading_day_rejects_before_ticker_or_pool_requests():
    session = FixtureSession()
    client = fixture_client(session)

    with pytest.raises(FuyaoNonTradingDayError, match="not present"):
        client.fetch_limit_dataset(date(2026, 9, 19))

    assert [call[0] for call in session.calls] == ["/api/a-share/calendar/trading-days"]


def test_duplicate_identity_makes_pagination_incomplete():
    payloads = [
        FIXTURE["limit_up_pages"][0],
        json.loads(json.dumps(FIXTURE["limit_up_pages"][1])),
    ]
    payloads[1]["data"]["item"][0] = dict(payloads[0]["data"]["item"][0])

    class DuplicateSession:
        def get(self, _url, *, params, **_kwargs):
            return FakeResponse(payloads[int(params["page"]) - 1])

    client = fixture_client(DuplicateSession())
    with pytest.raises(FuyaoContractError, match="2 of 3"):
        client.fetch_limit_pool("limit_up", AS_OF)


@pytest.mark.parametrize(
    ("failure", "expected_calls"),
    [
        (FakeResponse({}, 429), 3),
        (FakeResponse({}, 503), 3),
        (FakeResponse({"code": 4001, "message": "limited", "data": {}}, 200), 3),
        (FakeResponse({"code": 5002, "message": "upstream timeout", "data": {}}, 200), 3),
        (requests.ConnectionError("offline"), 3),
    ],
)
def test_retryable_errors_are_retried_twice(failure, expected_calls):
    calls = []

    class RetrySession:
        def get(self, *_args, **_kwargs):
            calls.append(1)
            if len(calls) < expected_calls:
                if isinstance(failure, Exception):
                    raise failure
                return failure
            return FakeResponse(FIXTURE["calendar"])

    client = fixture_client(RetrySession())
    assert client.fetch_trading_days()[-1] == AS_OF
    assert len(calls) == expected_calls


@pytest.mark.parametrize("code", [2001, 2003])
def test_permission_error_is_not_retried(code):
    calls = []

    class PermissionSession:
        def get(self, *_args, **_kwargs):
            calls.append(1)
            return FakeResponse({"code": code, "message": "denied", "data": None})

    with pytest.raises(FuyaoPermissionError, match=f"code={code}"):
        fixture_client(PermissionSession()).fetch_trading_days()
    assert len(calls) == 1


def test_retry_exhaustion_uses_exponential_backoff():
    sleeps = []

    class LimitedSession:
        def get(self, *_args, **_kwargs):
            return FakeResponse({"code": 4001, "message": "limited", "data": {}})

    client = FuyaoClient(
        "fixture-key",
        session=LimitedSession(),
        sleep=sleeps.append,
        backoff_seconds=0.25,
    )
    with pytest.raises(FuyaoTransportError, match="after retries"):
        client.fetch_trading_days()
    assert sleeps == [0.25, 0.5]


def test_missing_key_fails_closed_without_network_or_secret_echo(monkeypatch):
    monkeypatch.delenv("MARKET_ENVIRONMENT_FUYAO_API_KEY", raising=False)
    client = FuyaoClient(session=FixtureSession())
    with pytest.raises(FuyaoConfigurationError) as error:
        client.fetch_trading_days()
    assert "fixture-key" not in str(error.value)
    assert client.session.calls == []


def test_pagination_metadata_must_remain_consistent():
    calls = defaultdict(int)

    class TruncatedSession:
        def get(self, url, *, params, **_kwargs):
            path = urlparse(url).path
            calls[path] += 1
            payload = json.loads(json.dumps(FIXTURE["limit_up_pages"][int(params["page"]) - 1]))
            if int(params["page"]) == 2:
                payload["data"]["pagination"]["total"] = 4
            return FakeResponse(payload)

    with pytest.raises(FuyaoContractError, match="total/pages conflict|changed"):
        fixture_client(TruncatedSession()).fetch_limit_pool("limit_up", AS_OF)
    assert sum(calls.values()) == 2


def test_calendar_requires_shanghai_midnight():
    payload = json.loads(json.dumps(FIXTURE["calendar"]))
    payload["data"]["item"][0]["date_ms"] += 3_600_000

    class CalendarSession:
        def get(self, *_args, **_kwargs):
            return FakeResponse(payload)

    with pytest.raises(FuyaoContractError, match="Shanghai midnight"):
        fixture_client(CalendarSession()).fetch_trading_days()


@pytest.mark.parametrize("mutation", ["short-page", "mixed-timestamp", "page-bound"])
def test_pool_rejects_internally_inconsistent_pages(mutation):
    pages = json.loads(json.dumps(FIXTURE["limit_up_pages"]))
    if mutation == "short-page":
        pages[0]["data"]["item"].pop()
        expected = "expected rows"
    elif mutation == "mixed-timestamp":
        pages[1]["data"]["timestamp"] += 1
        expected = "mixed snapshot timestamps"
    else:
        pages[0]["data"]["pagination"].update({"total": 202, "pages": 101})
        expected = "safety bound"

    class InvalidPageSession:
        def get(self, _url, *, params, **_kwargs):
            return FakeResponse(pages[int(params["page"]) - 1])

    with pytest.raises(FuyaoContractError, match=expected):
        fixture_client(InvalidPageSession()).fetch_limit_pool("limit_up", AS_OF)


def test_code_table_failure_degrades_enrichment_without_blocking_pools():
    class CodeTableFailureSession(FixtureSession):
        def get(self, url, **kwargs):
            if urlparse(url).path.endswith("/meta/tickers/list"):
                self.calls.append((urlparse(url).path, dict(kwargs["params"]), {}, kwargs["timeout"]))
                return FakeResponse({"code": 2003, "message": "denied", "data": None})
            return super().get(url, **kwargs)

    result = fixture_client(CodeTableFailureSession()).fetch_limit_dataset(AS_OF)
    assert result.tickers == {}
    assert result.pools["limit_up"].total == 3
    assert any("code-table enrichment unavailable" in item for item in result.warnings)


def test_code_table_is_fetched_once_across_history_sessions():
    session = FixtureSession()
    client = fixture_client(session)

    client.fetch_limit_dataset(date(2026, 9, 17))
    client.fetch_limit_dataset(AS_OF)

    assert [call[0] for call in session.calls].count("/api/meta/tickers/list") == 1


def test_redirect_is_not_followed_with_api_key():
    calls = []

    class RedirectSession:
        def get(self, *_args, **kwargs):
            calls.append(kwargs)
            return FakeResponse({}, 302)

    with pytest.raises(FuyaoTransportError, match="HTTP 302"):
        fixture_client(RedirectSession()).fetch_trading_days()
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False


def provider_dataset(*, up_codes=("600001",)):
    tickers = {
        "600001.SH": {
            "thscode": "600001.SH",
            "ticker": "600001",
            "name": "沪市样本",
            "exchange": "SH",
            "list_date": "2020-01-02",
        },
        "000001.SZ": {
            "thscode": "000001.SZ",
            "ticker": "000001",
            "name": "深市样本",
            "exchange": "SZ",
            "list_date": "1991-04-03",
        },
    }
    up = tuple(
        {
            "thscode": f"{code}.SH",
            "ticker": code,
            "name": f"样本{code}",
            "is_st": False,
            "is_new": False,
            "last_price": 11,
            "price_change_ratio_pct": 10,
            "limit_up_time": "09:35",
            "limit_up_reason": "测试",
            "continue_day_cnt": 2,
            "seal_money": 1_000_000,
            "max_seal_money": 2_000_000,
        }
        for code in up_codes
    )
    return FuyaoLimitDataset(
        as_of=AS_OF,
        pools={
            "limit_up": FuyaoPoolResult(up, len(up), 1),
            "failed_limit_up": FuyaoPoolResult((), 0, 0),
            "limit_down": FuyaoPoolResult((), 0, 0),
        },
        tickers=tickers,
    )


class StubFuyao:
    configured = True

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def fetch_trading_days(self):
        if self.error is not None:
            raise self.error
        return (AS_OF,)

    def fetch_limit_dataset(self, as_of, *, trading_days=None):
        self.calls.append(as_of)
        if self.error is not None:
            raise self.error
        return self.result


def install_eastmoney_pools(monkeypatch, provider, *, up_codes=("600001",)):
    pools = {
        "getTopicZTPool": [
            {
                "m": "1",
                "c": code,
                "n": f"样本{code}",
                "board": "main",
                "is_st": False,
                "listing_days": 1000,
                "limit_regime": "pct:10",
                "close_price": 11,
                "previous_close": 10,
                "touched_limit_up": True,
                "closed_limit_up": True,
                "streak_days": 2,
            }
            for code in up_codes
        ],
        "getTopicZBPool": [],
        "getTopicDTPool": [],
    }

    def fake_get_json(url, _params):
        return {"data": {"pool": pools[url.rsplit("/", 1)[-1]]}}

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)


def test_provider_merges_consistent_sources_and_preserves_fuyao_fields(monkeypatch):
    fuyao = StubFuyao(provider_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    install_eastmoney_pools(monkeypatch, provider)

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    assert result.payload["limitUpCount"] == 1
    assert result.payload["maxStreak"] == 2
    assert result.normalization.membership_complete is True
    assert result.normalization.streak_complete is True
    assert result.normalization.pool_quality["limit_up"]["status"] == "ok"
    row = next(row for row in result.normalization.rows if row.pool_type == "limit_up")
    assert row.source == "fuyao"
    assert row.limit_up_time == "09:35"
    assert row.limit_up_reason == "测试"
    assert row.listing_date == date(2020, 1, 2)


def test_provider_keeps_union_and_marks_source_difference_degraded(monkeypatch):
    fuyao = StubFuyao(provider_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    install_eastmoney_pools(monkeypatch, provider, up_codes=("600001", "600002"))

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    rows = [row for row in result.normalization.rows if row.pool_type == "limit_up"]
    assert {row.code for row in rows} == {"600001", "600002"}
    assert result.payload["limitUpCount"] == 2
    assert result.normalization.membership_complete is True
    assert result.normalization.pool_quality["limit_up"]["status"] == "degraded"
    exclusive = next(row for row in rows if row.code == "600002")
    assert exclusive.source.startswith("eastmoney")
    assert exclusive.row_quality == "degraded"
    assert any("Eastmoney" in warning for warning in exclusive.row_warnings)
    assert any("source membership differs" in warning for warning in result.normalization.warnings)


def test_provider_merges_eastmoney_per_pool_when_another_pool_is_incomplete(monkeypatch):
    fuyao = StubFuyao(provider_dataset())
    provider = MarketDataProvider(fuyao=fuyao)
    pools = {
        "getTopicZTPool": [
            {"m": "1", "c": "600001"},
            {"m": "1", "c": "600002"},
        ],
        "getTopicZBPool": [{"c": "bad"}],
        "getTopicDTPool": [],
    }
    monkeypatch.setattr(
        provider.eastmoney,
        "get_json",
        lambda url, _params: {"data": {"pool": pools[url.rsplit("/", 1)[-1]]}},
    )

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    assert {
        row.code for row in result.normalization.rows if row.pool_type == "limit_up"
    } == {"600001", "600002"}
    assert result.normalization.pool_quality["limit_up"]["source"] == "fuyao+eastmoney"
    assert result.normalization.pool_quality["failed_limit_up"]["source"] == "fuyao"
    assert any(
        "failed_limit_up Eastmoney cross-check lacks complete" in item
        for item in result.normalization.warnings
    )


def test_provider_uses_eastmoney_as_degraded_fallback_when_fuyao_fails(monkeypatch):
    fuyao = StubFuyao(error=RuntimeError("fixture primary unavailable"))
    provider = MarketDataProvider(fuyao=fuyao)
    install_eastmoney_pools(monkeypatch, provider)

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    assert result.payload["quality"]["status"] == "partial"
    assert result.payload["quality"]["source"] == "eastmoney-push2ex"
    assert result.normalization.membership_complete is False
    assert any("Fuyao primary source unavailable" in item for item in result.normalization.warnings)


def test_provider_requires_secret_when_limits_v1_runtime_is_enabled(monkeypatch):
    session = FixtureSession()
    provider = MarketDataProvider(
        fuyao=FuyaoClient("", session=session),
        require_fuyao_for_limits=True,
    )
    monkeypatch.setattr(
        provider.eastmoney,
        "get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback must not run")),
    )

    with pytest.raises(FuyaoConfigurationError, match="MARKET_ENVIRONMENT_FUYAO_API_KEY"):
        provider.fetch_chapter01_limit_dataset_strict(AS_OF)
    assert session.calls == []


def test_provider_keeps_pool_identity_when_code_table_exchange_conflicts(monkeypatch):
    dataset = provider_dataset()
    tickers = dict(dataset.tickers)
    tickers["600001.SH"] = {**tickers["600001.SH"], "exchange": "SZ"}
    fuyao = StubFuyao(
        FuyaoLimitDataset(dataset.as_of, dataset.pools, tickers, dataset.warnings)
    )
    provider = MarketDataProvider(fuyao=fuyao)
    install_eastmoney_pools(monkeypatch, provider)

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)
    row = next(row for row in result.normalization.rows if row.pool_type == "limit_up")

    assert row.security_id == "SSE:600001"
    assert row.exchange == "SSE"
    assert row.row_quality == "degraded"
    assert any("exchange conflicts" in item for item in row.row_warnings)


def test_provider_does_not_claim_empty_fallback_without_calendar_confirmation(monkeypatch):
    fuyao = StubFuyao(error=RuntimeError("calendar unavailable"))
    provider = MarketDataProvider(fuyao=fuyao)
    install_eastmoney_pools(monkeypatch, provider, up_codes=())

    result = provider.fetch_chapter01_limit_dataset_strict(AS_OF)

    assert result.payload["limitUpCount"] is None
    assert result.payload["failedLimitUpCount"] is None
    assert result.payload["limitDownCount"] is None
    assert result.payload["state"] == "insufficient"
    assert result.payload["quality"]["status"] == "partial"
    assert result.normalization.membership_complete is False
    assert all(
        item["membershipComplete"] is False
        for item in result.normalization.pool_quality.values()
    )
    assert any("empty pools remain unconfirmed" in item for item in result.normalization.warnings)
