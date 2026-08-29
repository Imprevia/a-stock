"""Pure calculations for the market environment dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    close: float
    high: float
    low: float
    amount: float


def _average(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def moving_average(bars: list[Bar], window: int) -> float | None:
    if len(bars) < window:
        return None
    return _average(bar.close for bar in bars[-window:])


def range_position(bars: list[Bar], window: int) -> float | None:
    """Return the close's position between recent low and high prices."""
    if len(bars) < window:
        return None
    window_bars = bars[-window:]
    low = min(bar.low for bar in window_bars)
    high = max(bar.high for bar in window_bars)
    if high == low:
        return None
    return max(0.0, min(1.0, (window_bars[-1].close - low) / (high - low)))


def amount_ratio(bars: list[Bar], window: int) -> float | None:
    if len(bars) < window + 1:
        return None
    baseline = _average(bar.amount for bar in bars[-window - 1 : -1])
    if not baseline:
        return None
    return bars[-1].amount / baseline


def _slope(bars: list[Bar], window: int, lookback: int = 5) -> float | None:
    if len(bars) < window + lookback:
        return None
    current = moving_average(bars, window)
    previous = moving_average(bars[:-lookback], window)
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def classify_trend(bars: list[Bar], amount_ratio_20: float | None) -> str:
    """Classify using the precedence described in the source document."""
    ma5 = moving_average(bars, 5)
    ma10 = moving_average(bars, 10)
    ma20 = moving_average(bars, 20)
    ma60 = moving_average(bars, 60)
    if None in (ma5, ma10, ma20, ma60):
        return "数据不足"

    current = bars[-1].close
    previous = bars[-2].close if len(bars) > 1 else current
    previous_ma20 = moving_average(bars[:-1], 20) if len(bars) > 20 else None
    if (
        previous_ma20 is not None
        and previous >= previous_ma20
        and current < ma20
        and amount_ratio_20 is not None
        and amount_ratio_20 >= 1.2
    ):
        return "趋势破坏"

    ma20_slope = _slope(bars, 20)
    ma60_slope = _slope(bars, 60)
    if (
        current >= ma5 >= ma10 >= ma20 >= ma60
        and (ma20_slope is None or ma20_slope >= 0)
        and (ma60_slope is None or ma60_slope >= 0)
    ):
        return "偏强"
    if (
        current <= ma5 <= ma10 <= ma20
        and (ma20_slope is None or ma20_slope <= 0)
    ):
        return "偏弱"
    return "震荡"


def classify_volume_price(bars: list[Bar], amount_ratio_5: float | None) -> str:
    if len(bars) < 2 or amount_ratio_5 is None:
        return "数据不足"
    change_pct = (bars[-1].close / bars[-2].close - 1) * 100 if bars[-2].close else 0
    if change_pct >= 0.5 and amount_ratio_5 >= 1.2:
        return "上涨放量"
    if change_pct >= 0.5 and amount_ratio_5 < 1.0:
        return "上涨缩量"
    if abs(change_pct) < 0.5 and amount_ratio_5 >= 1.2:
        return "放量滞涨"
    if change_pct <= -0.5 and amount_ratio_5 < 1.0:
        return "下跌缩量"
    if change_pct <= -0.5 and amount_ratio_5 >= 1.2:
        return "放量下跌"
    return "量价平稳"


def position_label(value: float | None) -> str:
    if value is None:
        return "数据不足"
    if value < 0.2:
        return "阶段低位"
    if value < 0.4:
        return "低位修复"
    if value < 0.6:
        return "区间中部"
    if value < 0.8:
        return "偏强区域"
    return "阶段高位"
