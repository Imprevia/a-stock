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


def classify_volume_price(bars: list[Bar], amount_ratio_5: float | None) -> str | None:
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
    if abs(change_pct) < 0.5 and 1.0 <= amount_ratio_5 < 1.2:
        return "量价平稳"
    return None


def classify_index_combination(bars: list[Bar], amount_ratio_5: float | None) -> dict:
    ma5 = moving_average(bars, 5)
    ma10 = moving_average(bars, 10)
    ma20 = moving_average(bars, 20)
    ma60 = moving_average(bars, 60)
    position60 = range_position(bars, 60)
    required = (ma5, ma10, ma20, ma60, position60, amount_ratio_5)
    if len(bars) < 60 or any(value is None for value in required):
        return {
            "key": "insufficient",
            "state": "数据不足",
            "matched": False,
            "tone": "insufficient",
            "evidence": ["至少需要 60 个有效交易日及可用成交额"],
            "tradingMode": "等待数据",
        }

    current = bars[-1]
    previous = bars[-2]
    change_pct = (current.close / previous.close - 1) * 100 if previous.close else 0.0
    close_position = (current.close - current.low) / (current.high - current.low) if current.high != current.low else None
    previous_ma5 = moving_average(bars[:-1], 5)
    return_5 = (current.close / bars[-6].close - 1) * 100 if bars[-6].close else 0.0
    recent_high20 = max(bar.high for bar in bars[-21:-1])
    ma_short = (ma5, ma10, ma20)
    ma_spread = (max(ma_short) / min(ma_short) - 1) if min(ma_short) else None
    recent_amounts = [bar.amount for bar in bars[-5:] if bar.amount > 0]
    amount_swing = max(recent_amounts) / min(recent_amounts) if len(recent_amounts) == 5 else None

    def result(key: str, state: str, tone: str, evidence: list[str], trading_mode: str) -> dict:
        return {
            "key": key,
            "state": state,
            "matched": True,
            "tone": tone,
            "evidence": evidence,
            "tradingMode": trading_mode,
        }

    if current.close < ma20 and change_pct <= -0.5 and amount_ratio_5 >= 1.2:
        return result(
            "trend_damage",
            "趋势破坏或退潮",
            "risk",
            [f"收盘 {current.close:.2f} 低于 MA20 {ma20:.2f}", f"日跌幅 {change_pct:.2f}%", f"5 日成交额比值 {amount_ratio_5:.2f}x"],
            "风险控制",
        )
    if (
        position60 >= 0.8
        and abs(change_pct) < 0.5
        and amount_ratio_5 >= 1.2
        and close_position is not None
        and close_position < 0.5
    ):
        return result(
            "high_divergence",
            "高位分歧或派发风险",
            "warning",
            [f"60 日位置 {position60:.0%}", f"日涨跌幅 {change_pct:.2f}%", f"5 日成交额比值 {amount_ratio_5:.2f}x", f"日内收盘位置 {close_position:.0%}"],
            "降低追高，等待承接",
        )
    if (
        position60 >= 0.8
        and change_pct >= 0.5
        and amount_ratio_5 >= 1.2
        and close_position is not None
        and close_position >= 0.7
        and current.close >= recent_high20
    ):
        return result(
            "breakout",
            "趋势加速或突破确认",
            "positive",
            [f"60 日位置 {position60:.0%}", f"日涨幅 {change_pct:.2f}%", f"5 日成交额比值 {amount_ratio_5:.2f}x", f"收盘不低于此前 20 日高点 {recent_high20:.2f}"],
            "趋势跟随，防止追高",
        )
    if (
        position60 < 0.4
        and previous_ma5 is not None
        and previous.close <= previous_ma5
        and current.close > ma5
        and 1.0 <= amount_ratio_5 < 1.2
    ):
        return result(
            "bottom_repair",
            "底部修复或启动尝试",
            "positive",
            [f"60 日位置 {position60:.0%}", f"收盘重新站上 MA5 {ma5:.2f}", f"5 日成交额比值 {amount_ratio_5:.2f}x"],
            "观察修复确认",
        )
    if (
        current.close >= ma5 >= ma10 >= ma20 >= ma60
        and return_5 > 0
        and position60 >= 0.6
        and 0.8 <= amount_ratio_5 < 1.2
    ):
        return result(
            "uptrend",
            "上升趋势或主升阶段",
            "positive",
            ["收盘与 MA5/MA10/MA20/MA60 呈多头结构", f"5 日涨幅 {return_5:.2f}%", f"60 日位置 {position60:.0%}", f"5 日成交额比值 {amount_ratio_5:.2f}x"],
            "顺势跟踪",
        )
    if ma_spread is not None and ma_spread <= 0.01 and amount_swing is not None and amount_swing >= 1.25:
        return result(
            "rotation",
            "震荡轮动",
            "neutral",
            [f"MA5/MA10/MA20 缠绕幅度 {ma_spread:.2%}", f"最近 5 日成交额摆动 {amount_swing:.2f}x"],
            "轮动应对",
        )
    return {
        "key": "unclassified",
        "state": None,
        "matched": False,
        "tone": "neutral",
        "evidence": [f"60 日位置 {position60:.0%}", f"5 日成交额比值 {amount_ratio_5:.2f}x", "当前指标未同时满足六类组合的明确阈值"],
        "tradingMode": "保持观察",
    }


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
