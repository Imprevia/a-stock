from datetime import date, timedelta
import json

import pytest

from src.market_environment.providers import INDEX_SPECS, MarketDataProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_eastmoney_index_kline_parses_amount_and_explicit_secid(monkeypatch):
    start = date(2026, 6, 1)
    rows = []
    for offset in range(65):
        day = start + timedelta(days=offset)
        rows.append(f"{day.isoformat()},3900,3910,3920,3890,100000000,200000000000,0,0,0,0")
    captured = {}

    def fake_get(url, params, timeout):
        captured.update(params)
        return FakeResponse({"rc": 0, "data": {"klines": rows}})

    provider = MarketDataProvider()
    monkeypatch.setattr(provider.session, "get", fake_get)
    bars = provider._fetch_eastmoney_kline(INDEX_SPECS[0], 160)

    assert len(bars) == 65
    assert bars[-1].amount == 200000000000
    assert captured["secid"] == "1.000001"


def test_guarded_shanghai_index_requires_realtime_price():
    provider = MarketDataProvider()
    assert provider._is_accepted(INDEX_SPECS[0], [], None) is False


def test_baidu_kline_passes_explicit_market_for_ambiguous_index(monkeypatch):
    captured = {}
    payload = {
        "Result": {
            "newMarketData": {
                "keys": ["timestamp", "time", "open", "close", "volume", "high", "low", "amount"],
                "marketData": "1787846400,2026-08-28,3900,3952,100,3970,3850,100000000000",
            }
        }
    }

    def fake_get(url, params, timeout):
        captured.update(params)
        return FakeResponse(payload)

    provider = MarketDataProvider()
    monkeypatch.setattr(provider.session, "get", fake_get)
    bars = provider._fetch_baidu_kline(INDEX_SPECS[0], 160)

    assert bars[-1].close == 3952
    assert captured["code"] == "000001"
    assert captured["market"] == "sh"


def test_sina_index_kline_calibrates_historical_amount(monkeypatch):
    captured = {}
    rows = [
        {"day": "2026-08-27", "open": "3900", "close": "3920", "high": "3930", "low": "3890", "volume": "900"},
        {"day": "2026-08-28", "open": "3920", "close": "3952", "high": "3970", "low": "3940", "volume": "1000"},
    ]

    def fake_get(url, params, timeout):
        captured.update(params)
        return type("Response", (), {"raise_for_status": lambda self: None, "text": "var x=(" + json.dumps(rows) + ")"})()

    provider = MarketDataProvider()
    monkeypatch.setattr(provider.session, "get", fake_get)
    bars = provider._fetch_sina_kline(INDEX_SPECS[0], 160, {"amount": 2000, "volume": 500})

    assert len(bars) == 2
    assert bars[-1].amount == 2000
    assert captured["symbol"] == "sh000001"


def test_chapter01_provider_builds_current_snapshot_without_percentile_claims(monkeypatch):
    provider = MarketDataProvider()

    def fake_get_json(url, params):
        if "push2ex" in url:
            endpoint = url.rsplit("/", 1)[-1]
            pools = {
                "getTopicZTPool": [{"c": "000001", "lbc": 3}],
                "getTopicZBPool": [{"c": "000002"}, {"c": "000003"}],
                "getTopicDTPool": [{"c": "000004"}],
            }
            return {"data": {"pool": pools[endpoint]}}
        if params["fs"] == "m:90+t:2":
            return {
                "data": {
                    "diff": [
                        {
                            "f12": "BK001",
                            "f14": "电子",
                            "f3": 2.5,
                            "f6": 1000,
                            "f62": 300,
                            "f184": 3.0,
                            "f104": 20,
                            "f105": 5,
                            "f140": "样本股",
                        }
                    ]
                }
            }
        return {
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "甲", "f3": 2, "f6": 400, "f2": 11, "f15": 12, "f16": 10, "f100": "电子"},
                    {"f12": "000002", "f14": "乙", "f3": -1, "f6": 300, "f2": 9, "f15": 10, "f16": 8, "f100": "电子"},
                    {"f12": "000003", "f14": "丙", "f3": 0, "f6": 200, "f2": 8, "f15": 9, "f16": 7, "f100": "电子"},
                    {"f12": "000004", "f14": "丁", "f3": 3, "f6": 100, "f2": 7, "f15": 7, "f16": 7, "f100": "医药"},
                ]
            }
        }

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    payload = provider.fetch_chapter01(date(2026, 8, 28), allow_current_snapshot=True)

    assert payload["breadth"]["advanceCount"] == 2
    assert payload["breadth"]["declineCount"] == 1
    assert payload["breadth"]["flatCount"] == 1
    assert payload["breadth"]["medianReturn"] == 1.0
    assert payload["limits"]["failedLimitUpRatio"] == 0.6667
    assert payload["limits"]["maxStreak"] == 3
    assert payload["activeDirection"]["state"] == "candidate"
    assert payload["activeDirection"]["topStocks"][-1]["closePosition"] is None
    assert "percentile" not in json.dumps(payload, ensure_ascii=False).lower()


def test_chapter01_provider_accepts_keyed_stock_snapshot(monkeypatch):
    provider = MarketDataProvider()

    def fake_get_json(url, params):
        if "push2ex" in url:
            return {"data": {"pool": []}}
        if params["fs"] == "m:90+t:2":
            return {"data": {"diff": []}}
        return {
            "data": {
                "diff": {
                    "0": {"f3": "1.5"},
                    "1": {"f3": "-0.5"},
                    "2": {"f3": "0"},
                }
            }
        }

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    payload = provider.fetch_chapter01(date(2026, 8, 28), allow_current_snapshot=True)

    assert payload["breadth"]["advanceCount"] == 1
    assert payload["breadth"]["declineCount"] == 1
    assert payload["breadth"]["medianReturn"] == 0.0


def test_stock_snapshot_rejects_partial_market_response(monkeypatch):
    provider = MarketDataProvider()
    monkeypatch.setattr(
        provider.eastmoney,
        "get_json",
        lambda url, params: {"data": {"total": 3, "diff": [{"f3": 1}, {"f3": -1}]}},
    )

    with pytest.raises(RuntimeError, match="仅返回 2 / 3 行"):
        provider._fetch_eastmoney_stock_snapshot()


def test_chapter01_breadth_falls_back_to_sorted_delay_pages(monkeypatch):
    provider = MarketDataProvider()
    provider._BREADTH_PAGE_SIZE = 3
    sorted_returns = [3.0, 2.0, 1.0, None, 0.0, 0.0, -1.0, -2.0, -3.0]

    def fake_get_json(url, params):
        if "push2ex" in url:
            return {"data": {"pool": []}}
        if url == provider._BREADTH_FALLBACK_URL:
            page = int(params["pn"])
            start = (page - 1) * provider._BREADTH_PAGE_SIZE
            values = sorted_returns[start : start + provider._BREADTH_PAGE_SIZE]
            return {
                "data": {
                    "total": len(sorted_returns),
                    "diff": [{"f3": "-" if value is None else value} for value in values],
                }
            }
        if params.get("fs") == "m:90+t:2":
            raise RuntimeError("industry unavailable")
        raise RuntimeError("primary stock snapshot blocked")

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    payload = provider.fetch_chapter01(date(2026, 8, 28), allow_current_snapshot=True)

    assert payload["breadth"]["advanceCount"] == 3
    assert payload["breadth"]["declineCount"] == 3
    assert payload["breadth"]["flatCount"] == 2
    assert payload["breadth"]["validCount"] == 8
    assert payload["breadth"]["medianReturn"] == 0.0
    assert payload["breadth"]["quality"]["status"] == "fallback"
    assert payload["breadth"]["quality"]["source"] == "eastmoney-clist-delay"


def test_chapter01_limit_provider_distinguishes_failure_from_explicit_empty_pool(monkeypatch):
    provider = MarketDataProvider()

    monkeypatch.setattr(provider.eastmoney, "get_json", lambda url, params: {"data": {"pool": []}})
    empty = provider._fetch_limit_evidence(date(2026, 8, 28))
    assert empty["limitUpCount"] == 0
    assert empty["limitDownCount"] == 0
    assert empty["failedLimitUpRatio"] is None
    assert empty["maxStreak"] is None

    def fail(url, params):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    failed = provider._fetch_limit_evidence(date(2026, 8, 28))
    assert failed["limitUpCount"] is None
    assert failed["limitDownCount"] is None
    assert failed["failedLimitUpCount"] is None
    assert failed["quality"]["status"] == "failed"
