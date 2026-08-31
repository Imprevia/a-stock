"""Market data providers with a mootdx-first, HTTP fallback strategy."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from src.trading_system.data.providers import EastmoneyClient

from .calculations import Bar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexSpec:
    code: str
    digits: str
    name: str
    representative: str


INDEX_SPECS = (
    IndexSpec("sh000001", "000001", "上证指数", "沪市大盘股、金融和周期权重"),
    IndexSpec("sz399001", "399001", "深证成指", "深市成长、制造和消费"),
    IndexSpec("sz399006", "399006", "创业板指", "高弹性成长股风险偏好"),
    IndexSpec("sh000300", "000300", "沪深300", "两市核心大盘蓝筹"),
    IndexSpec("sh000905", "000905", "中证500", "中盘股和题材扩散"),
)

# Baidu and mootdx can interpret these six-digit Shanghai index codes as stocks
# when no independent quote is available. Require a quote cross-check before
# accepting either provider for those symbols.
PRICE_GUARDED_CODES = frozenset({"sh000001", "sh000905"})


@dataclass
class ProviderResult:
    bars: list[Bar]
    source: str
    warning: str | None = None
    is_stale: bool = False


class MarketDataProvider:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.eastmoney = EastmoneyClient(timeout=timeout, session=self.session)

    def fetch(
        self,
        spec: IndexSpec,
        limit: int = 160,
        expected_price: float | None = None,
        quote: dict[str, Any] | None = None,
    ) -> ProviderResult:
        errors: list[str] = []
        try:
            bars = self._fetch_mootdx(spec, limit)
            if len(bars) >= 60 and self._is_accepted(spec, bars, expected_price):
                return ProviderResult(bars=bars, source="mootdx")
            errors.append("mootdx 返回历史数据不足或与实时指数价格不匹配")
        except Exception as exc:  # provider boundary: fallback must remain available
            logger.warning("mootdx failed for %s: %s", spec.code, exc)
            errors.append(f"mootdx: {exc}")

        try:
            bars = self._fetch_baidu_kline(spec, limit)
            if len(bars) >= 60 and self._is_accepted(spec, bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="baidu-kline",
                    warning="通达信不可用，已降级到百度历史 K 线",
                )
            errors.append("百度历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Baidu kline failed for %s: %s", spec.code, exc)
            errors.append(f"百度 K 线: {exc}")

        try:
            bars = self._fetch_sina_kline(spec, limit, quote or {})
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="sina-kline",
                    warning="通达信和百度不可用，已降级到新浪指数 K 线；成交额按腾讯实时成交额校准估算",
                )
            errors.append("新浪指数 K 线数据不足")
        except Exception as exc:
            logger.warning("Sina kline failed for %s: %s", spec.code, exc)
            errors.append(f"新浪 K 线: {exc}")

        try:
            bars = self._fetch_eastmoney_kline(spec, limit)
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="eastmoney-kline",
                    warning="通达信和百度不可用，已降级到东方财富历史 K 线",
                )
            errors.append("东方财富历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Eastmoney kline failed for %s: %s", spec.code, exc)
            errors.append(f"东方财富 K 线: {exc}")

        try:
            bars = self._fetch_tencent_kline(spec, limit)
            if len(bars) >= 60 and self._price_matches(bars, expected_price):
                return ProviderResult(
                    bars=bars,
                    source="tencent-kline",
                    warning="通达信和百度不可用，已降级到腾讯历史 K 线；历史成交额可能不可用",
                )
            errors.append("腾讯历史 K 线数据不足")
        except Exception as exc:
            logger.warning("Tencent kline failed for %s: %s", spec.code, exc)
            errors.append(f"腾讯 K 线: {exc}")

        raise RuntimeError("；".join(errors))

    def fetch_quotes(self, specs: tuple[IndexSpec, ...]) -> dict[str, dict[str, Any]]:
        query = ",".join(spec.code for spec in specs)
        url = f"https://qt.gtimg.cn/q={query}"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        result: dict[str, dict[str, Any]] = {}
        for line in text.split(";"):
            if "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            values = line.split('"')[1].split("~")
            if len(values) < 50:
                continue
            code = key.lower()
            price = self._number(values, 3)
            last_close = self._number(values, 4)
            amount_wan = self._number(values, 37)
            result[code] = {
                "name": values[1],
                "price": price,
                "last_close": last_close,
                "change_pct": self._number(values, 32),
                "amount": amount_wan * 10000,
                "volume": self._number(values, 36),
                "is_stale": bool(amount_wan == 0 and price == last_close and price > 0),
            }
        return result

    def _fetch_mootdx(self, spec: IndexSpec, limit: int) -> list[Bar]:
        from mootdx.quotes import Quotes

        client = Quotes.factory(market="std", multithread=False)
        market = 1 if spec.code.startswith("sh") else 0
        frame = client.bars(symbol=spec.digits, frequency=9, offset=limit, market=market)
        if frame is None or len(frame) == 0:
            return []
        rows: list[Bar] = []
        for item in frame.to_dict("records"):
            raw_date = item.get("datetime") or item.get("date")
            parsed_date = self._parse_date(raw_date)
            if parsed_date is None:
                continue
            rows.append(
                Bar(
                    date=parsed_date,
                    open=float(item.get("open", 0) or 0),
                    close=float(item.get("close", 0) or 0),
                    high=float(item.get("high", 0) or 0),
                    low=float(item.get("low", 0) or 0),
                    amount=float(item.get("amount", 0) or 0),
                )
            )
        return sorted((bar for bar in rows if bar.close > 0), key=lambda bar: bar.date)

    def _fetch_baidu_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
        params = {
            "all": "1",
            "isIndex": "true",
            "isBk": "false",
            "isBlock": "false",
            "isFutures": "false",
            "isStock": "false",
            "newFormat": "1",
            "group": "quotation_kline_ab",
            "finClientType": "pc",
            "code": spec.digits,
            "market": "sh" if spec.code.startswith("sh") else "sz",
            "ktype": "1",
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        market_data = payload.get("Result", {}).get("newMarketData", {})
        keys = market_data.get("keys", [])
        rows = market_data.get("marketData", "").split(";")
        positions = {key: index for index, key in enumerate(keys)}
        result: list[Bar] = []
        for row in rows:
            values = row.split(",")
            if len(values) < len(keys):
                continue
            parsed_date = self._parse_date(values[positions.get("time", 1)])
            if parsed_date is None:
                continue
            result.append(
                Bar(
                    date=parsed_date,
                    open=float(values[positions["open"]]),
                    close=float(values[positions["close"]]),
                    high=float(values[positions["high"]]),
                    low=float(values[positions["low"]]),
                    amount=float(values[positions["amount"]]),
                )
            )
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_eastmoney_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        """Fetch index K-lines with an explicit Eastmoney market secid.

        Unlike the six-digit Baidu/mootdx routes, ``1.000001`` and
        ``1.000905`` are unambiguous Shanghai index identifiers and include
        historical turnover amounts needed for volume-price analysis.
        """
        market = "1" if spec.code.startswith("sh") else "0"
        secid = f"{market}.{spec.digits}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "beg": "19900101",
            "end": (date.today() + timedelta(days=1)).strftime("%Y%m%d"),
            "lmt": str(max(limit, 160)),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        payload = self.eastmoney.get_json(url, params)
        if payload.get("rc") not in (0, None):
            raise RuntimeError(f"返回错误码 {payload.get('rc')}")
        rows = payload.get("data", {}).get("klines", [])
        result: list[Bar] = []
        for row in rows:
            values = str(row).split(",")
            if len(values) < 7:
                continue
            parsed_date = self._parse_date(values[0])
            if parsed_date is None:
                continue
            try:
                result.append(
                    Bar(
                        date=parsed_date,
                        open=float(values[1]),
                        close=float(values[2]),
                        high=float(values[3]),
                        low=float(values[4]),
                        amount=float(values[6]),
                    )
                )
            except (TypeError, ValueError):
                continue
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_sina_kline(self, spec: IndexSpec, limit: int, quote: dict[str, Any]) -> list[Bar]:
        """Fetch index history from Sina and calibrate turnover units.

        Sina exposes index volume in a different unit from currency. The latest
        Tencent real-time amount and same-day Sina volume provide a scale factor,
        so historical amounts remain comparable without presenting raw volume
        as currency.
        """
        url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{spec.code}_klines=/CN_MarketData.getKLineData"
        params = {"symbol": spec.code, "scale": "240", "ma": "no", "datalen": str(max(limit, 160))}
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        text = response.text
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise RuntimeError("新浪响应不含 K 线数组")
        rows = json.loads(text[start : end + 1])
        if not rows:
            return []
        latest_volume = float(rows[-1].get("volume") or 0)
        quote_amount = float(quote.get("amount") or 0)
        if latest_volume <= 0 or quote_amount <= 0:
            raise RuntimeError("缺少腾讯实时成交额或新浪最新成交量，无法校准新浪成交量")
        scale = quote_amount / latest_volume
        result: list[Bar] = []
        for row in rows:
            parsed_date = self._parse_date(row.get("day"))
            if parsed_date is None:
                continue
            try:
                volume = float(row.get("volume") or 0)
                result.append(
                    Bar(
                        date=parsed_date,
                        open=float(row["open"]),
                        close=float(row["close"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        amount=volume * scale,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)[-160:]

    def _fetch_tencent_kline(self, spec: IndexSpec, limit: int) -> list[Bar]:
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={spec.code},day,,,{limit},qfq"
        )
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}).get(spec.code, {})
        rows = data.get("qfqday") or data.get("day") or []
        result: list[Bar] = []
        for row in rows:
            if len(row) < 6:
                continue
            parsed_date = self._parse_date(row[0])
            if parsed_date is None:
                continue
            result.append(
                Bar(
                    date=parsed_date,
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    # Tencent's public day endpoint exposes volume but not amount.
                    amount=float(row[6]) if len(row) > 6 and row[6] not in (None, "") else 0,
                )
            )
        return sorted((bar for bar in result if bar.close > 0), key=lambda bar: bar.date)

    @staticmethod
    def _number(values: list[str], index: int) -> float:
        try:
            return float(values[index]) if values[index] else 0.0
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _price_matches(bars: list[Bar], expected_price: float | None) -> bool:
        if expected_price in (None, 0) or not bars:
            return True
        return abs(bars[-1].close - expected_price) / expected_price <= 0.2

    @classmethod
    def _is_accepted(cls, spec: IndexSpec, bars: list[Bar], expected_price: float | None) -> bool:
        if spec.code in PRICE_GUARDED_CODES and expected_price in (None, 0):
            return False
        return cls._price_matches(bars, expected_price)

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = str(value or "")[:10]
        try:
            return date.fromisoformat(text.replace("/", "-"))
        except ValueError:
            return None
