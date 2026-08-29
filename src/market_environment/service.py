"""Application service for loading and calculating market environment data."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from threading import Lock
from zoneinfo import ZoneInfo

from .calculations import (
    Bar,
    amount_ratio,
    classify_trend,
    classify_volume_price,
    moving_average,
    position_label,
    range_position,
)
from .providers import INDEX_SPECS, MarketDataProvider, ProviderResult


class MarketEnvironmentService:
    def __init__(self, provider: MarketDataProvider | None = None, ttl_seconds: int = 30) -> None:
        self.provider = provider or MarketDataProvider()
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def get(self, as_of: date) -> dict:
        cache_key = as_of.isoformat()
        now = datetime.now().timestamp()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.ttl_seconds:
                return cached[1]

        warnings: list[str] = []
        try:
            quotes = self.provider.fetch_quotes(INDEX_SPECS)
        except Exception as exc:
            quotes = {}
            warnings.append(f"腾讯实时报价不可用：{exc}")

        results: list[tuple[object, ProviderResult | None, str | None]] = []
        for spec in INDEX_SPECS:
            try:
                expected_price = quotes.get(spec.code, {}).get("price")
                result = self.provider.fetch(spec, expected_price=expected_price)
                results.append((spec, result, None))
            except Exception as exc:
                results.append((spec, None, str(exc)))

        if not any(result for _, result, _ in results):
            raise RuntimeError("全部指数数据源不可用")

        analyses = []
        effective_dates: list[date] = []
        for spec, result, error in results:
            if result is None:
                warnings.append(f"{spec.name}：{error or '无数据'}")
                continue
            bars = [bar for bar in result.bars if bar.date <= as_of]
            if not bars:
                warnings.append(f"{spec.name}：所选日期前无历史数据")
                continue
            effective_dates.append(bars[-1].date)
            quote = quotes.get(spec.code, {})
            analysis = self._analyse(spec, bars, result, quote)
            analyses.append(analysis)
            if result.warning:
                warnings.append(f"{spec.name}：{result.warning}")
            if analysis["dataQuality"]["warning"] and not result.warning:
                warnings.append(f"{spec.name}：{analysis['dataQuality']['warning']}")

        if not analyses:
            raise RuntimeError("所选日期前没有可用指数数据")
        effective_date = min(effective_dates)
        for item in analyses:
            if item["dataQuality"]["warning"] is None and effective_date < as_of:
                item["dataQuality"]["warning"] = f"非交易日，已回退到 {effective_date.isoformat()}"

        trends = Counter(item["trendState"] for item in analyses)
        sync = self._synchronization(analyses)
        dominant = trends.most_common(1)[0][0] if trends else "数据不足"
        payload = {
            "asOf": effective_date.isoformat(),
            "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "indices": analyses,
            "summary": {"synchronization": sync, "dominantTrend": dominant, "warnings": warnings},
        }
        with self._lock:
            self._cache[cache_key] = (now, payload)
        return payload

    @staticmethod
    def _analyse(spec, bars: list[Bar], result: ProviderResult, quote: dict) -> dict:
        ma = {f"ma{window}": moving_average(bars, window) for window in (5, 10, 20, 60)}
        ratio5 = amount_ratio(bars, 5)
        ratio20 = amount_ratio(bars, 20)
        close = bars[-1].close
        change_pct = quote.get("change_pct")
        if change_pct is None or quote.get("is_stale"):
            change_pct = ((close / bars[-2].close) - 1) * 100 if len(bars) > 1 and bars[-2].close else 0
        warning = result.warning
        quality_warnings: list[str] = []
        if not quote:
            quality_warnings.append("腾讯实时行情不可用，涨跌幅使用历史 K 线计算")
        if len(bars) >= 20 and range_position(bars, 20) is None:
            quality_warnings.append("20 日最高价与最低价相同，区间位置不可计算")
        if len(bars) >= 60 and range_position(bars, 60) is None:
            quality_warnings.append("60 日最高价与最低价相同，区间位置不可计算")
        if quote.get("is_stale"):
            quality_warnings.insert(0, "腾讯报价疑似停牌或过期，涨跌幅已使用历史 K 线计算")
        if quality_warnings:
            warning = "；".join(filter(None, [warning, *quality_warnings]))
        history = []
        for index in range(max(0, len(bars) - 60), len(bars)):
            sample = bars[: index + 1]
            history.append(
                {
                    "date": bars[index].date.isoformat(),
                    "close": bars[index].close,
                    "ma5": moving_average(sample, 5),
                    "ma10": moving_average(sample, 10),
                    "ma20": moving_average(sample, 20),
                    "ma60": moving_average(sample, 60),
                    "amount": bars[index].amount,
                }
            )
        return {
            "code": spec.code,
            "name": quote.get("name") or spec.name,
            "representative": spec.representative,
            "changePct": round(float(change_pct or 0), 2),
            "close": round(close, 2),
            "movingAverages": {key: round(value, 2) if value is not None else None for key, value in ma.items()},
            "rangePosition20": range_position(bars, 20),
            "rangePosition60": range_position(bars, 60),
            "rangePosition20Label": position_label(range_position(bars, 20)),
            "rangePosition60Label": position_label(range_position(bars, 60)),
            "amount": round(bars[-1].amount, 2),
            "amountRatio5": round(ratio5, 2) if ratio5 is not None else None,
            "amountRatio20": round(ratio20, 2) if ratio20 is not None else None,
            "trendState": classify_trend(bars, ratio20),
            "volumePriceState": classify_volume_price(bars, ratio5),
            "history": history,
            "dataQuality": {"source": result.source, "isStale": bool(quote.get("is_stale")), "warning": warning},
        }

    @staticmethod
    def _synchronization(analyses: list[dict]) -> str:
        changes = [item["changePct"] for item in analyses]
        if not changes:
            return "无可用数据"
        positive = sum(value >= 0.5 for value in changes)
        negative = sum(value <= -0.5 for value in changes)
        if positive >= max(3, len(changes) - 1):
            return "同步上涨"
        if negative >= max(3, len(changes) - 1):
            return "普遍走弱"
        return "指数分化"
