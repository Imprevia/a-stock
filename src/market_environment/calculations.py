"""Pure calculations for the market environment dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Iterable, Mapping, Sequence


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


SYNC_PATTERN_LABELS = {
    "synchronized_rally": "同步上涨",
    "broad_weakness": "普遍走弱",
    "weight_shelter": "权重护盘",
    "growth_lead": "成长占优",
    "undetermined_divergence": "分化未定型",
}
SYNC_PATTERN_SCORES = {
    "broad_weakness": 0,
    "undetermined_divergence": 25,
    "weight_shelter": 50,
    "growth_lead": 75,
    "synchronized_rally": 100,
}


def classify_sync_pattern(changes: Mapping[str, float | None]) -> dict[str, object]:
    """Classify five-index synchronization with neutral Shenzhen reference."""
    valid = {key: float(value) for key, value in changes.items() if value is not None}
    if not valid:
        code = "undetermined_divergence"
    else:
        advancing = sum(value >= 0.5 for value in valid.values())
        declining = sum(value <= -0.5 for value in valid.values())
        if advancing >= 4 and len(valid) >= 4:
            code = "synchronized_rally"
        elif declining >= 4 and len(valid) >= 4:
            code = "broad_weakness"
        elif all(valid.get(name, 0) >= 0.5 for name in ("上证指数", "沪深300")) and all(
            valid.get(name, 0) < 0 for name in ("创业板指", "中证500")
        ):
            code = "weight_shelter"
        elif all(valid.get(name, 0) >= 0.5 for name in ("创业板指", "中证500")) and all(
            valid.get(name, 0) < 0 for name in ("上证指数", "沪深300")
        ):
            code = "growth_lead"
        else:
            code = "undetermined_divergence"
    return {
        "code": code,
        "label": SYNC_PATTERN_LABELS[code],
        "score": SYNC_PATTERN_SCORES[code],
        "evidence": [f"{name} {value:+.2f}%" for name, value in valid.items()],
    }


def _breadth_state(breadth: Mapping[str, object]) -> str:
    advance_ratio = breadth.get("advanceRatio")
    median_return = breadth.get("medianReturn")
    if advance_ratio is None or median_return is None:
        return "insufficient"
    if float(advance_ratio) >= 0.55 and float(median_return) > 0:
        return "positive"
    if float(advance_ratio) <= 0.45 and float(median_return) < 0:
        return "negative"
    return "mixed"


def _dimension_status(state: str, *, confirming: str, contradicting: str) -> str:
    if state == "insufficient":
        return "insufficient"
    if state == confirming:
        return "confirming"
    if state == contradicting:
        return "contradicting"
    return "neutral"


def build_synchronization_assessment(
    sync_pattern: Mapping[str, object],
    analyses: Sequence[Mapping[str, object]],
    breadth: Mapping[str, object],
    previous_breadth: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Interpret an observed index pattern without rewriting the observation."""
    pattern_code = str(sync_pattern.get("code") or "undetermined_divergence")
    pattern_label = str(sync_pattern.get("label") or SYNC_PATTERN_LABELS["undetermined_divergence"])
    breadth_state = _breadth_state(breadth)
    previous_state = _breadth_state(previous_breadth or {})
    advance_ratio = breadth.get("advanceRatio")
    median_return = breadth.get("medianReturn")
    previous_advance_ratio = (previous_breadth or {}).get("advanceRatio")
    previous_median_return = (previous_breadth or {}).get("medianReturn")
    current_as_of = (breadth.get("quality") or {}).get("asOf") if isinstance(breadth.get("quality"), Mapping) else None
    previous_as_of = (
        (previous_breadth.get("quality") or {}).get("asOf")
        if previous_breadth and isinstance(previous_breadth.get("quality"), Mapping)
        else None
    )
    comparison_available = (
        previous_state != "insufficient"
        and advance_ratio is not None
        and median_return is not None
        and previous_advance_ratio is not None
        and previous_median_return is not None
    )
    advance_ratio_delta = (
        round(float(advance_ratio) - float(previous_advance_ratio), 4) if comparison_available else None
    )
    median_return_delta = (
        round(float(median_return) - float(previous_median_return), 4) if comparison_available else None
    )
    breadth_evidence = []
    if breadth_state == "insufficient":
        breadth_evidence.append("当日市场广度数据不足")
    else:
        breadth_evidence.append(f"上涨占比 {float(advance_ratio):.0%}，涨跌幅中位数 {float(median_return):.2f}%")
    if comparison_available:
        breadth_evidence.append(
            f"较 {previous_as_of} 上涨占比变化 {advance_ratio_delta:+.2%}，中位数变化 {median_return_delta:+.2f} 个百分点"
        )
    else:
        breadth_evidence.append("精确上一交易日广度快照缺失，无法判断改善或恶化")

    above_ma20 = 0
    below_ma20 = 0
    trend_valid = 0
    turnover_ratios: list[float] = []
    growth_turnover: dict[str, float] = {}
    volume_backed_advance = 0
    volume_backed_decline = 0
    valid_changes: list[float] = []
    for item in analyses:
        close = item.get("close")
        averages = item.get("movingAverages")
        ma20 = averages.get("ma20") if isinstance(averages, Mapping) else None
        if close is not None and ma20 is not None:
            trend_valid += 1
            if float(close) >= float(ma20):
                above_ma20 += 1
            else:
                below_ma20 += 1

        change_pct = item.get("changePct")
        if change_pct is not None:
            valid_changes.append(float(change_pct))
        ratio = item.get("amountRatio5")
        if ratio is None:
            continue
        ratio_value = float(ratio)
        turnover_ratios.append(ratio_value)
        name = str(item.get("name") or "")
        if name in {"创业板指", "中证500"}:
            growth_turnover[name] = ratio_value
        volume_state = item.get("volumePriceState")
        if volume_state == "上涨放量" or (change_pct is not None and float(change_pct) >= 0.5 and ratio_value >= 1.2):
            volume_backed_advance += 1
        if volume_state == "放量下跌" or (change_pct is not None and float(change_pct) <= -0.5 and ratio_value >= 1.2):
            volume_backed_decline += 1

    trend_state = "insufficient" if trend_valid < 3 else ("positive" if above_ma20 >= 3 else ("negative" if below_ma20 >= 3 else "mixed"))
    turnover_state = "insufficient"
    if len(turnover_ratios) >= 3:
        if volume_backed_advance >= 3:
            turnover_state = "positive"
        elif volume_backed_decline >= 3:
            turnover_state = "negative"
        else:
            turnover_state = "mixed"
    growth_median = median(growth_turnover.values()) if len(growth_turnover) == 2 else None
    turnover_median = median(turnover_ratios) if turnover_ratios else None
    trend_evidence = [f"MA20 上方 {above_ma20} 个，下方 {below_ma20} 个，有效 {trend_valid} 个"]
    turnover_evidence = [
        f"5 日成交额比值有效 {len(turnover_ratios)} 个，放量上涨 {volume_backed_advance} 个，放量下跌 {volume_backed_decline} 个"
    ]
    if turnover_median is not None:
        turnover_evidence.append(f"五指数成交额比值中位数 {turnover_median:.2f} 倍")
    if growth_median is not None:
        turnover_evidence.append(f"创业板指与中证500成交额比值中位数 {growth_median:.2f} 倍")

    breadth_status = "neutral" if pattern_code == "undetermined_divergence" else _dimension_status(
        breadth_state,
        confirming="negative" if pattern_code in {"weight_shelter", "broad_weakness"} else "positive",
        contradicting="positive" if pattern_code in {"weight_shelter", "broad_weakness"} else "negative",
    )
    trend_status = "neutral"
    if pattern_code in {"synchronized_rally", "growth_lead"}:
        trend_status = _dimension_status(trend_state, confirming="positive", contradicting="negative")
    elif pattern_code == "broad_weakness":
        trend_status = _dimension_status(trend_state, confirming="negative", contradicting="positive")
    elif trend_state == "insufficient":
        trend_status = "insufficient"
    turnover_status = "neutral"
    if pattern_code == "growth_lead":
        turnover_status = (
            "insufficient"
            if growth_median is None
            else ("confirming" if growth_median >= 1.0 else ("contradicting" if growth_median < 0.8 else "neutral"))
        )
    elif pattern_code == "synchronized_rally":
        turnover_status = _dimension_status(turnover_state, confirming="positive", contradicting="negative")
    elif pattern_code == "broad_weakness":
        turnover_status = _dimension_status(turnover_state, confirming="negative", contradicting="positive")
    elif turnover_state == "insufficient":
        turnover_status = "insufficient"

    status = "unconfirmed"
    conclusion_code = "undetermined-divergence"
    conclusion = "指数表现分化，尚未形成明确的同步方向。"
    confidence = "low"
    risks: list[str] = []

    # Strong business conclusions require their documented confirmation gates.
    if pattern_code == "synchronized_rally":
        if breadth_state == "insufficient":
            status = "insufficient"
            conclusion_code = "synchronized-rally-insufficient"
            conclusion = "多数指数同步上涨，但市场广度数据不足，强势普遍性尚不能确认。"
            confidence = "insufficient"
            risks.append("缺少上涨家数和涨跌幅中位数，不能把指数上涨定义为全面强势")
        elif breadth_state == "negative":
            status = "contradicted"
            conclusion_code = "index-strength-breadth-divergence"
            conclusion = "多数指数同步上涨，但多数个股偏弱，指数强势没有得到市场广度确认。"
            confidence = "high"
            risks.append("指数与个股表现背离，不能按全面强势处理")
        elif breadth_state == "positive":
            status = "confirmed"
            conclusion_code = "broad-strength-confirmed"
            improving = comparison_available and advance_ratio_delta > 0 and median_return_delta > 0
            conclusion = (
                "多数指数同步上涨，且上涨家数占比和涨跌幅中位数改善，市场风险偏好改善的可信度较高。"
                if improving
                else "多数指数同步上涨且多数个股偏强，市场强势具有普遍性。"
            )
            confidence = "high" if improving else "medium"
        else:
            conclusion_code = "synchronized-rally-unconfirmed"
            conclusion = "多数指数同步上涨，但市场广度处于混合状态，强势普遍性仍待确认。"
    elif pattern_code == "weight_shelter":
        if breadth_state == "insufficient":
            status = "insufficient"
            conclusion_code = "weight-lead-insufficient"
            conclusion = "权重指数相对占优，但市场广度不足，是否属于护盘尚不能确认。"
            confidence = "insufficient"
            risks.append("缺少个股广度，不能声称指数偏强而个股偏弱")
        elif breadth_state == "negative":
            status = "confirmed"
            conclusion_code = "weight-shelter-confirmed"
            conclusion = "上证与沪深300偏强，而多数个股偏弱，权重护盘特征得到市场广度确认。"
            confidence = "high"
            risks.append("指数强于个股，不能将权重护盘定义为全面强势")
        elif breadth_state == "positive":
            status = "contradicted"
            conclusion_code = "weight-lead-contradicted"
            conclusion = "权重指数相对占优，但多数个股并不弱，当前只能定义为权重领涨而非确认护盘。"
            confidence = "high"
        else:
            conclusion_code = "weight-lead-unconfirmed"
            conclusion = "权重指数相对占优，市场广度混合，护盘特征尚未确认。"
    elif pattern_code == "growth_lead":
        if breadth_state == "insufficient" or growth_median is None:
            status = "insufficient"
            conclusion_code = "growth-lead-insufficient"
            conclusion = "创业板与中证500相对占优，但市场广度或成长组成交额不足，题材机会尚不能确认。"
            confidence = "insufficient"
            risks.append("成长风格缺少市场广度或成交额验证")
        elif breadth_state == "negative" or growth_median < 0.8:
            status = "contradicted"
            conclusion_code = "growth-lead-contradicted"
            conclusion = "创业板与中证500相对占优，但市场广度或成交额不支持，成长强势的扩散能力有限。"
            confidence = "high"
            risks.append("相对强势未得到参与面和交易活跃度共同确认")
        elif breadth_state == "positive" and growth_median >= 1.0:
            status = "confirmed"
            conclusion_code = "growth-lead-confirmed"
            conclusion = "创业板与中证500相对占优，市场广度和成交额共同确认成长及中小盘风险偏好改善。"
            confidence = "high"
        else:
            conclusion_code = "growth-lead-unconfirmed"
            conclusion = "创业板与中证500相对占优，但广度或成交额仍处于中性区间，题材机会待继续验证。"
    elif pattern_code == "broad_weakness":
        if breadth_state == "insufficient" or trend_state == "insufficient" or turnover_state == "insufficient":
            status = "insufficient"
            conclusion_code = "broad-weakness-insufficient"
            conclusion = "多数指数同步走弱，但广度、趋势或成交额证据不足，系统性下降尚不能确认。"
            confidence = "insufficient"
            risks.append("指数普遍走弱，缺失风险维度不能按安全处理")
        elif breadth_state == "negative" and below_ma20 >= 3 and volume_backed_decline >= 3:
            status = "confirmed"
            conclusion_code = "systemic-decline-confirmed"
            conclusion = "多数指数同步走弱，并伴随放量下跌、关键均线失守和下跌面扩大，风险偏好正在系统性下降。"
            confidence = "high"
            risks.append("弱势由广度、趋势和成交额共同确认，应优先控制风险")
        elif breadth_state == "positive" or above_ma20 >= 3 or volume_backed_advance >= 3:
            status = "contradicted"
            conclusion_code = "broad-weakness-contradicted"
            conclusion = "多数指数同步走弱，但个股广度、趋势位置或成交额出现反向证据，暂不能定义为系统性下降。"
            confidence = "high"
            risks.append("保留指数弱势警示，但系统性风险结论被其他证据反驳")
        else:
            conclusion_code = "broad-weakness-unconfirmed"
            conclusion = "多数指数同步走弱，但放量、均线破位和下跌面尚未同时确认，当前更接近普遍回落。"
            risks.append("系统性下降尚未确认，但指数弱势仍需持续观察")
    elif len(valid_changes) < 4:
        status = "insufficient"
        conclusion_code = "undetermined-insufficient"
        conclusion = "有效指数不足四个，无法可靠判断指数之间是否同步。"
        confidence = "insufficient"

    all_five_weak = len(valid_changes) >= 5 and all(value <= -0.5 for value in valid_changes)
    if all_five_weak:
        risks.append("五个主要指数均达到明确下跌阈值")
    evidence = [*list(sync_pattern.get("evidence") or []), *breadth_evidence, *trend_evidence, *turnover_evidence]
    return {
        "patternCode": pattern_code,
        "patternLabel": pattern_label,
        "status": status,
        "conclusionCode": conclusion_code,
        "conclusion": conclusion,
        "confidence": confidence,
        "allFiveWeak": all_five_weak,
        "dimensions": {
            "breadth": {
                "status": breadth_status,
                "currentAsOf": current_as_of,
                "previousAsOf": previous_as_of if comparison_available else None,
                "advanceRatio": float(advance_ratio) if advance_ratio is not None else None,
                "medianReturn": float(median_return) if median_return is not None else None,
                "advanceRatioDelta": advance_ratio_delta,
                "medianReturnDelta": median_return_delta,
                "comparisonStatus": "available" if comparison_available else "insufficient",
                "reason": "current-breadth-unavailable" if breadth_state == "insufficient" else None,
                "comparisonReason": None if comparison_available else "previous-breadth-unavailable",
                "evidence": breadth_evidence,
            },
            "trend": {
                "status": trend_status,
                "aboveMa20Count": above_ma20,
                "belowMa20Count": below_ma20,
                "validCount": trend_valid,
                "reason": "fewer-than-three-ma20-observations" if trend_state == "insufficient" else None,
                "evidence": trend_evidence,
            },
            "turnover": {
                "status": turnover_status,
                "medianAmountRatio5": round(turnover_median, 4) if turnover_median is not None else None,
                "growthMedianAmountRatio5": round(growth_median, 4) if growth_median is not None else None,
                "volumeBackedAdvanceCount": volume_backed_advance,
                "volumeBackedDeclineCount": volume_backed_decline,
                "validCount": len(turnover_ratios),
                "reason": (
                    "growth-turnover-unavailable"
                    if pattern_code == "growth_lead" and growth_median is None
                    else ("fewer-than-three-turnover-observations" if turnover_state == "insufficient" else None)
                ),
                "evidence": turnover_evidence,
            },
        },
        "evidence": evidence,
        "risks": risks,
    }


def _percentile_rank(values: Sequence[float], current: float) -> float:
    if not values:
        return 0.0
    return sum(value <= current for value in values) / len(values)


def _metric_percentile(values: Sequence[float], *, window: int = 250, minimum: int = 60) -> dict[str, object]:
    valid = [float(value) for value in values]
    if len(valid) < minimum:
        return {"value": None, "confidence": "insufficient", "reason": "insufficient-history"}
    sample = valid[-window:]
    confidence = "high" if len(valid) >= window else "medium"
    return {"value": _percentile_rank(sample, valid[-1]), "confidence": confidence, "reason": None}


def ma20_slope_percentile(bars: list[Bar]) -> dict[str, object]:
    slopes = [value for index in range(len(bars)) if (value := _slope(bars[: index + 1], 20)) is not None]
    return _metric_percentile(slopes)


def advance_efficiency_percentile(bars: list[Bar]) -> dict[str, object]:
    efficiencies: list[float] = []
    for index in range(1, len(bars)):
        sample = bars[: index + 1]
        ratio = amount_ratio(sample, 20)
        previous = sample[-2].close
        if ratio is None or previous <= 0:
            continue
        efficiencies.append(((sample[-1].close / previous) - 1) / max(ratio, 0.5))
    return _metric_percentile(efficiencies)


def bullish_alignment_ratio(analyses: Sequence[Mapping[str, object]]) -> float | None:
    eligible = []
    for item in analyses:
        averages = item.get("movingAverages")
        if isinstance(averages, Mapping) and all(averages.get(key) is not None for key in ("ma5", "ma10", "ma20")):
            eligible.append(item)
    if not eligible:
        return None
    bullish = 0
    for item in eligible:
        averages = item["movingAverages"]
        if isinstance(averages, Mapping) and averages["ma5"] >= averages["ma10"] >= averages["ma20"]:
            bullish += 1
    return bullish / len(eligible)


def build_summary_sentence(
    sync_label: str | None,
    ma20_label: str | None,
    range60_label: str | None,
    turnover_ratio5: float | None,
    volume_price_state: str | None,
    leaning: str | None,
) -> str:
    """Compose the auditable post-market sentence without filling missing parts."""
    turnover = f"成交额为5日均值的{turnover_ratio5:.2f}倍" if turnover_ratio5 is not None else "成交额数据不足"
    parts = (
        sync_label or "同步性数据不足",
        f"收盘位于{ma20_label}" if ma20_label else "MA20相对位置数据不足",
        f"60日区间{range60_label}" if range60_label else "60日区间位置数据不足",
        turnover,
        volume_price_state or "价格推进数据不足",
        leaning or "环境倾向数据不足",
    )
    return "，".join(parts) + "。"
