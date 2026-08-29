from datetime import date, timedelta
import json

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
