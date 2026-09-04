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


def build_active_direction_rows() -> list[dict]:
    return [
        {
            "f12": f"{index:06d}",
            "f14": f"样本{index}",
            "f3": 3 - index / 10,
            "f6": 30_000 - index,
            "f2": 11,
            "f15": 12,
            "f16": 10,
            "f100": "电子" if index < 4 else f"行业{index}",
        }
        for index in range(30)
    ]


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
    bars = provider._fetch_eastmoney_kline(INDEX_SPECS[0], 280)

    assert len(bars) == 65
    assert bars[-1].amount == 200000000000
    assert captured["secid"] == "1.000001"
    assert captured["lmt"] == "280"


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
    bars = provider._fetch_baidu_kline(INDEX_SPECS[0], 280)

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
    bars = provider._fetch_sina_kline(INDEX_SPECS[0], 280, {"amount": 2000, "volume": 500})

    assert len(bars) == 2
    assert bars[-1].amount == 2000
    assert captured["symbol"] == "sh000001"
    assert captured["datalen"] == "280"


def test_chapter01_provider_builds_current_snapshot_without_percentile_claims(monkeypatch):
    provider = MarketDataProvider()

    breadth = provider._breadth_result(
        2,
        1,
        1,
        1.0,
        date(2026, 8, 28),
        source="eastmoney-clist-delay",
        status="fallback",
        warnings=["fixture"],
    )
    active_rows = build_active_direction_rows()
    active_rows[9]["f15"] = 11
    active_rows[9]["f16"] = 11
    monkeypatch.setattr(provider, "_fetch_eastmoney_breadth_fallback", lambda as_of, warning: breadth)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_active_direction",
        lambda: (active_rows, "eastmoney-clist", "partial", []),
    )

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
                            "f128": "样本股",
                            "f140": "000001",
                        }
                    ]
                }
            }
        raise AssertionError("stock datasets use their independent collectors")

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
    assert payload["sectors"]["rows"][0]["leader"] == "样本股"
    assert "percentile" not in json.dumps(payload, ensure_ascii=False).lower()


def test_sector_provider_uses_primary_source_and_real_leader_name(monkeypatch):
    provider = MarketDataProvider()
    calls = []

    def fake_get_json(url, params):
        calls.append((url, params["fields"]))
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
                        "f128": "领涨名称",
                        "f140": "000001",
                    }
                ]
            }
        }

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    result = provider.fetch_chapter01_sectors(date(2026, 9, 3), allow_current_snapshot=True)

    assert len(calls) == 1
    assert "push2.eastmoney.com" in calls[0][0]
    assert "f128" in calls[0][1]
    assert result["rows"][0]["leader"] == "领涨名称"
    assert result["quality"]["source"] == "eastmoney-clist"
    assert result["quality"]["status"] == "partial"


def test_sector_provider_falls_back_to_delayed_endpoint(monkeypatch):
    provider = MarketDataProvider()
    calls = []

    def fake_get_json(url, _params):
        calls.append(url)
        if "push2.eastmoney.com" in url:
            raise RuntimeError("primary disconnected")
        return {"data": {"diff": [{"f12": "BK002", "f14": "医药", "f3": 1.2}]}}

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    result = provider.fetch_chapter01_sectors(date(2026, 9, 3), allow_current_snapshot=True)

    assert len(calls) == 2
    assert "push2delay.eastmoney.com" in calls[1]
    assert result["quality"]["source"] == "eastmoney-clist-delay"
    assert result["quality"]["status"] == "fallback"
    assert "primary disconnected" in result["quality"]["warning"]
    assert result["rows"][0]["leader"] is None


def test_sector_provider_reports_both_endpoint_failures(monkeypatch):
    provider = MarketDataProvider()
    calls = []

    def fail(url, _params):
        calls.append(url)
        raise RuntimeError("unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = provider.fetch_chapter01_sectors(date(2026, 9, 3), allow_current_snapshot=True)

    assert len(calls) == 2
    assert result["quality"]["status"] == "failed"
    assert "主域失败" in result["quality"]["warning"]
    assert "延迟域失败" in result["quality"]["warning"]


def test_historical_sector_request_calls_no_endpoint(monkeypatch):
    provider = MarketDataProvider()
    monkeypatch.setattr(
        provider.eastmoney,
        "get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call provider")),
    )

    result = provider.fetch_chapter01_sectors(date(2026, 9, 2), allow_current_snapshot=False)

    assert result["quality"]["status"] == "missing"


def test_active_direction_provider_uses_primary_without_delayed_request(monkeypatch):
    provider = MarketDataProvider()
    calls = []
    rows = build_active_direction_rows()

    def fake_get_json(url, params):
        calls.append((url, params))
        return {"data": {"diff": rows}}

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    result = provider.fetch_chapter01_active_direction(date(2026, 9, 3), allow_current_snapshot=True)

    assert len(calls) == 1
    assert calls[0][0] == provider._STOCK_SNAPSHOT_URL
    assert calls[0][1]["fid"] == "f6"
    assert result["state"] == "candidate"
    assert "电子 有 4 只" in result["summary"]
    assert len(result["topStocks"]) == 10
    assert result["topStocks"][0]["code"] == "000000"
    assert result["quality"]["source"] == "eastmoney-clist"
    assert result["quality"]["status"] == "partial"
    assert result["quality"]["observations"] == 30
    assert "降级" not in result["quality"]["warning"]


def test_active_direction_provider_falls_back_to_keyed_delayed_response(monkeypatch):
    provider = MarketDataProvider()
    calls = []
    rows = build_active_direction_rows()

    def fake_get_json(url, _params):
        calls.append(url)
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        return {"data": {"diff": {str(index): row for index, row in enumerate(rows)}}}

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    result = provider.fetch_chapter01_active_direction(date(2026, 9, 3), allow_current_snapshot=True)

    assert calls == [provider._STOCK_SNAPSHOT_URL, provider._ACTIVE_DIRECTION_FALLBACK_URL]
    assert result["state"] == "candidate"
    assert "电子 有 4 只" in result["summary"]
    assert [item["code"] for item in result["topStocks"]] == [f"{index:06d}" for index in range(10)]
    assert result["quality"]["source"] == "eastmoney-clist-delay"
    assert result["quality"]["status"] == "fallback"
    assert result["quality"]["observations"] == 30
    assert "primary disconnected" in result["quality"]["warnings"][0]
    assert "已降级到东方财富延迟容量方向" in result["quality"]["warnings"]


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
        raise AssertionError("breadth must not request the nominal full-market snapshot")

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    monkeypatch.setattr(
        provider,
        "_fetch_eastmoney_stock_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    breadth = provider.fetch_chapter01_breadth(date(2026, 8, 28), allow_current_snapshot=True)

    assert breadth["advanceCount"] == 3
    assert breadth["declineCount"] == 3
    assert breadth["flatCount"] == 2
    assert breadth["validCount"] == 8
    assert breadth["medianReturn"] == 0.0
    assert breadth["quality"]["status"] == "fallback"
    assert breadth["quality"]["source"] == "eastmoney-clist-delay"


@pytest.mark.parametrize("invalid_case", ["too-small", "missing-field", "unsorted"])
def test_active_direction_provider_rejects_invalid_delayed_payload(monkeypatch, invalid_case):
    provider = MarketDataProvider()
    rows = build_active_direction_rows()
    if invalid_case == "too-small":
        rows = rows[:29]
        expected_warning = "仅返回 29 个有效样本"
    elif invalid_case == "missing-field":
        rows[0] = {key: value for key, value in rows[0].items() if key != "f14"}
        expected_warning = "仅返回 29 个有效样本"
    else:
        rows[1]["f6"] = 1
        expected_warning = "未按成交额降序排列"

    calls = []

    def fake_get_json(url, _params):
        calls.append(url)
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        return {"data": {"diff": rows}}

    monkeypatch.setattr(provider.eastmoney, "get_json", fake_get_json)
    result = provider.fetch_chapter01_active_direction(date(2026, 9, 3), allow_current_snapshot=True)

    assert calls == [provider._STOCK_SNAPSHOT_URL, provider._ACTIVE_DIRECTION_FALLBACK_URL]
    assert result["state"] == "insufficient"
    assert result["topStocks"] == []
    assert result["quality"]["status"] == "failed"
    assert "主域失败：primary disconnected" in result["quality"]["warning"]
    assert "延迟域失败" in result["quality"]["warning"]
    assert expected_warning in result["quality"]["warning"]


def test_active_direction_provider_reports_both_endpoint_failures(monkeypatch):
    provider = MarketDataProvider()

    def fail(url, _params):
        if url == provider._STOCK_SNAPSHOT_URL:
            raise RuntimeError("primary disconnected")
        raise RuntimeError("delayed unavailable")

    monkeypatch.setattr(provider.eastmoney, "get_json", fail)
    result = provider.fetch_chapter01_active_direction(date(2026, 9, 3), allow_current_snapshot=True)

    assert result["quality"]["status"] == "failed"
    assert "主域失败：primary disconnected" in result["quality"]["warning"]
    assert "延迟域失败：delayed unavailable" in result["quality"]["warning"]


def test_historical_active_direction_request_calls_no_endpoint(monkeypatch):
    provider = MarketDataProvider()
    monkeypatch.setattr(
        provider.eastmoney,
        "get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call provider")),
    )

    result = provider.fetch_chapter01_active_direction(date(2026, 9, 2), allow_current_snapshot=False)

    assert result["state"] == "insufficient"
    assert result["quality"]["status"] == "missing"


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
