"""Pure core-index analysis and synchronization policies."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from ...calculations import (
    Bar,
    advance_efficiency_percentile,
    amount_ratio,
    bullish_alignment_ratio,
    build_synchronization_assessment,
    classify_index_combination,
    classify_sync_pattern,
    classify_trend,
    classify_volume_price,
    ma20_slope_percentile,
    moving_average,
    position_label,
    range_position,
)


def analyze_index(spec: Any, bars: list[Bar], result: Any, quote: dict) -> dict:
    ma = {f"ma{window}": moving_average(bars, window) for window in (5, 10, 20, 60)}
    ratio5 = amount_ratio(bars, 5)
    ratio20 = amount_ratio(bars, 20)
    combination = classify_index_combination(bars, ratio5)
    slope_percentile = ma20_slope_percentile(bars)
    efficiency_percentile = advance_efficiency_percentile(bars)
    close = bars[-1].close
    change_pct = quote.get("change_pct")
    if change_pct is None or quote.get("is_stale"):
        change_pct = (((close / bars[-2].close) - 1) * 100 if len(bars) > 1 and bars[-2].close else 0)
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
    data_gaps: list[dict[str, str]] = []
    for field, metric in (
        ("ma20SlopePercentile", slope_percentile),
        ("advanceEfficiencyPercentile", efficiency_percentile),
    ):
        if metric["value"] is None:
            data_gaps.append({"field": field, "reason": metric["reason"]})
    if len(bars) < 20:
        data_gaps.append({"field": "rangePosition20", "reason": "insufficient-history"})
    elif range_position(bars, 20) is None:
        data_gaps.append({"field": "rangePosition20", "reason": "not-computable"})
    if len(bars) < 60:
        data_gaps.append({"field": "rangePosition60", "reason": "insufficient-history"})
    elif range_position(bars, 60) is None:
        data_gaps.append({"field": "rangePosition60", "reason": "not-computable"})
    history = []
    for index in range(max(0, len(bars) - 60), len(bars)):
        sample = bars[: index + 1]
        history.append(
            {
                "date": bars[index].date.isoformat(),
                "open": bars[index].open,
                "close": bars[index].close,
                "low": bars[index].low,
                "high": bars[index].high,
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
        "ma20SlopePercentile": slope_percentile["value"],
        "advanceEfficiencyPercentile": efficiency_percentile["value"],
        "ma20SlopeConfidence": slope_percentile["confidence"],
        "advanceEfficiencyConfidence": efficiency_percentile["confidence"],
        "ma20PositionLabel": "上方" if ma["ma20"] is not None and close >= ma["ma20"] else ("下方" if ma["ma20"] is not None else None),
        "amount": round(bars[-1].amount, 2),
        "amountRatio5": round(ratio5, 2) if ratio5 is not None else None,
        "amountRatio20": round(ratio20, 2) if ratio20 is not None else None,
        "trendState": classify_trend(bars, ratio20),
        "volumePriceState": classify_volume_price(bars, ratio5),
        "combination": combination,
        "history": history,
        "dataQuality": {"source": result.source, "isStale": bool(quote.get("is_stale")), "warning": warning},
        "dataGaps": data_gaps,
    }


def sync_pattern(analyses: list[dict]) -> dict:
    return classify_sync_pattern({item["name"]: item.get("changePct") for item in analyses})


def synchronization_label(analyses: list[dict]) -> str:
    return sync_pattern(analyses)["label"]


def build_core_summary(analyses: list[dict], warnings: list[str], data_gaps: list[dict[str, str]]) -> dict[str, Any]:
    trends = Counter(item["trendState"] for item in analyses)
    pattern = sync_pattern(analyses)
    return {
        "synchronization": pattern["label"],
        "syncPattern": pattern,
        "bullishAlignmentRatio": bullish_alignment_ratio(analyses),
        "dominantTrend": trends.most_common(1)[0][0] if trends else "数据不足",
        "warnings": warnings,
        "dataGaps": data_gaps,
    }


def build_collected_core_summary(analyses: list[dict], warnings: list[str]) -> dict[str, Any]:
    trends = Counter(item["trendState"] for item in analyses)
    return {
        "synchronization": synchronization_label(analyses),
        "dominantTrend": trends.most_common(1)[0][0] if trends else "数据不足",
        "warnings": warnings,
    }


def synchronization_assessment(core: dict[str, Any], breadth: dict, previous_breadth: dict[str, Any] | None) -> dict[str, object]:
    pattern = core["summary"].get("syncPattern") or sync_pattern(core["indices"])
    return build_synchronization_assessment(pattern, core["indices"], breadth, previous_breadth)


def previous_trading_date(core: dict[str, Any]) -> date | None:
    as_of = core["effectiveDate"]
    candidates: list[date] = []
    for item in core["indices"]:
        for point in item.get("history", []):
            try:
                observed = date.fromisoformat(point["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if observed < as_of:
                candidates.append(observed)
    return max(candidates) if candidates else None


def combination_overview(analyses: list[dict], assessment: dict, breadth: dict) -> dict:
    breadth_available = breadth.get("advanceRatio") is not None and breadth.get("medianReturn") is not None
    strength = assessment["conclusion"]
    matched = [item["combination"] for item in analyses if item["combination"]["matched"]]
    stage_counts = Counter(item["key"] for item in matched)
    stage_key, stage_count = stage_counts.most_common(1)[0] if stage_counts else (None, 0)
    stage_match = next((item for item in matched if item["key"] == stage_key), None)
    if stage_match and stage_count >= 3:
        stage = stage_match["state"]
    elif matched:
        stage = "组合分化"
    else:
        stage = "未形成明确组合"
    volume_states = [item["volumePriceState"] for item in analyses if item.get("volumePriceState") not in {None, "数据不足"}]
    volume_counts = Counter(volume_states)
    volume_state, volume_count = volume_counts.most_common(1)[0] if volume_counts else (None, 0)
    capital_map = {
        "上涨放量": "资金认可价格推进",
        "上涨缩量": "上涨但增量资金不足",
        "放量滞涨": "成交活跃但价格推进不足",
        "下跌缩量": "抛压或承接仍待确认",
        "放量下跌": "资金主动撤退风险",
        "量价平稳": "量价整体平稳",
    }
    capital_acceptance = capital_map.get(volume_state, "量价信号分化或未分类") if volume_count >= 3 else "量价信号分化或未分类"
    if assessment["conclusionCode"] == "systemic-decline-confirmed" or stage == "趋势破坏或退潮":
        trading_mode = "风险控制"
    elif stage == "高位分歧或派发风险":
        trading_mode = "降低追高，等待承接"
    elif stage == "趋势加速或突破确认":
        trading_mode = "趋势跟随，防止追高"
    elif stage == "上升趋势或主升阶段":
        trading_mode = "顺势跟踪"
    elif stage == "底部修复或启动尝试":
        trading_mode = "观察修复确认"
    elif stage == "震荡轮动":
        trading_mode = "轮动应对"
    else:
        trading_mode = "保持观察"
    confidence = "medium" if assessment["confidence"] in {"high", "medium"} and stage_count >= 3 else "low"
    evidence = [
        f"五大指数同步性：{assessment['patternLabel']}（{assessment['status']}）",
        f"明确组合覆盖：{len(matched)} / {len(analyses)}",
    ]
    if breadth_available:
        evidence.append(f"市场广度：上涨占比 {breadth['advanceRatio']:.0%}，中位涨跌幅 {breadth['medianReturn']:.2f}%")
    else:
        evidence.append("市场广度缺失，市场是否真强仍待确认")
    evidence.append(f"一致量价状态：{volume_state or '无'}（{volume_count} / {len(analyses)}）")
    return {
        "strength": strength,
        "stage": stage,
        "capitalAcceptance": capital_acceptance,
        "tradingMode": trading_mode,
        "confidence": confidence,
        "evidence": evidence,
    }


__all__ = [
    "analyze_index",
    "build_collected_core_summary",
    "build_core_summary",
    "combination_overview",
    "previous_trading_date",
    "sync_pattern",
    "synchronization_assessment",
    "synchronization_label",
]
