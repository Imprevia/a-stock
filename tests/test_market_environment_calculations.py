from datetime import date, timedelta

from src.market_environment.calculations import (
    Bar,
    amount_ratio,
    advance_efficiency_percentile,
    build_summary_sentence,
    build_synchronization_assessment,
    bullish_alignment_ratio,
    classify_index_combination,
    classify_sync_pattern,
    classify_volume_price,
    moving_average,
    ma20_slope_percentile,
    range_position,
)


def make_bars(
    closes: list[float],
    amounts: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[Bar]:
    amounts = amounts or [100.0] * len(closes)
    highs = highs or closes
    lows = lows or closes
    return [
        Bar(
            date=date(2026, 1, 1) + timedelta(days=index),
            open=close,
            close=close,
            high=high,
            low=low,
            amount=amount,
        )
        for index, (close, amount, high, low) in enumerate(zip(closes, amounts, highs, lows))
    ]


def test_moving_average_uses_latest_window() -> None:
    bars = make_bars([1, 2, 3, 4, 5])
    assert moving_average(bars, 3) == 4


def test_range_position_returns_none_for_flat_window() -> None:
    assert range_position(make_bars([10] * 20), 20) is None


def test_range_position_uses_high_low_window() -> None:
    bars = make_bars([10] * 20)
    bars[-1] = Bar(
        date=bars[-1].date,
        open=10,
        close=15,
        high=15,
        low=14,
        amount=100,
    )
    bars[0] = Bar(
        date=bars[0].date,
        open=5,
        close=5,
        high=5,
        low=5,
        amount=100,
    )
    assert range_position(bars, 20) == (15 - 5) / (15 - 5)


def test_amount_ratio_compares_with_previous_window() -> None:
    bars = make_bars([1] * 6, [100, 100, 100, 100, 100, 200])
    assert amount_ratio(bars, 5) == 2


def test_volume_price_state_distinguishes_volume_expansion() -> None:
    bars = make_bars([10, 11], [100, 200])
    assert classify_volume_price(bars, 2) == "上涨放量"


def test_volume_price_state_marks_only_explicit_stable_range() -> None:
    bars = make_bars([10, 10.02])
    assert classify_volume_price(bars, 1.1) == "量价平稳"


def test_volume_price_state_does_not_fallback_between_thresholds() -> None:
    bars = make_bars([10, 10.1])
    assert classify_volume_price(bars, 1.1) is None


def test_index_combination_identifies_trend_damage_first() -> None:
    closes = [100 + index * 0.2 for index in range(59)] + [105]
    result = classify_index_combination(make_bars(closes), 1.6)
    assert result["key"] == "trend_damage"
    assert result["tradingMode"] == "风险控制"


def test_index_combination_identifies_high_divergence() -> None:
    closes = [80 + index * 0.4 for index in range(59)] + [103.3]
    highs = closes[:-1] + [105]
    lows = closes[:-1] + [103]
    result = classify_index_combination(make_bars(closes, highs=highs, lows=lows), 1.4)
    assert result["key"] == "high_divergence"


def test_index_combination_identifies_breakout_confirmation() -> None:
    closes = [80 + index * 0.3 for index in range(59)] + [99]
    highs = closes[:-1] + [99.1]
    lows = closes[:-1] + [98.5]
    result = classify_index_combination(make_bars(closes, highs=highs, lows=lows), 1.4)
    assert result["key"] == "breakout"


def test_index_combination_identifies_bottom_repair() -> None:
    closes = [120 - index * 0.45 for index in range(59)] + [98]
    result = classify_index_combination(make_bars(closes), 1.1)
    assert result["key"] == "bottom_repair"


def test_index_combination_identifies_uptrend() -> None:
    closes = [100 + index * 0.5 for index in range(60)]
    result = classify_index_combination(make_bars(closes), 1.0)
    assert result["key"] == "uptrend"


def test_index_combination_identifies_rotation() -> None:
    closes = [100 + (0.1 if index % 2 == 0 else -0.1) for index in range(60)]
    amounts = [100.0] * 55 + [80, 120, 85, 125, 100]
    result = classify_index_combination(make_bars(closes, amounts=amounts), 1.0)
    assert result["key"] == "rotation"


def test_index_combination_does_not_fallback_when_unmatched() -> None:
    closes = [100 + index * 0.05 for index in range(60)]
    result = classify_index_combination(make_bars(closes), 1.3)
    assert result["key"] == "unclassified"
    assert result["state"] is None
    assert result["matched"] is False


def test_sync_pattern_covers_five_states_and_precedence() -> None:
    names = ["上证指数", "深证成指", "创业板指", "沪深300", "中证500"]
    assert classify_sync_pattern(dict.fromkeys(names, 0.8))["code"] == "synchronized_rally"
    assert classify_sync_pattern(dict.fromkeys(names, -0.8))["code"] == "broad_weakness"
    assert classify_sync_pattern({"上证指数": 0.8, "沪深300": 0.7, "创业板指": -0.2, "中证500": -0.3, "深证成指": 0.1})["code"] == "weight_shelter"
    assert classify_sync_pattern({"上证指数": -0.2, "沪深300": -0.3, "创业板指": 0.8, "中证500": 0.7, "深证成指": 0.1})["code"] == "growth_lead"
    assert classify_sync_pattern({"上证指数": 0.2, "沪深300": -0.2, "创业板指": 0.1, "中证500": -0.1, "深证成指": 0.0})["code"] == "undetermined_divergence"


def assessment_indices(
    changes: dict[str, float],
    ratios: dict[str, float] | None = None,
    *,
    below_ma20: bool = False,
) -> list[dict]:
    ratios = ratios or {}
    return [
        {
            "name": name,
            "changePct": change_pct,
            "close": 99 if below_ma20 else 101,
            "movingAverages": {"ma20": 100},
            "amountRatio5": ratios.get(name, 1.1),
            "volumePriceState": None,
        }
        for name, change_pct in changes.items()
    ]


def breadth(advance_ratio: float | None, median_return: float | None, as_of: str) -> dict:
    return {
        "advanceRatio": advance_ratio,
        "medianReturn": median_return,
        "quality": {"asOf": as_of},
    }


def test_synchronized_rally_keeps_pattern_and_uses_exact_breadth_comparison() -> None:
    changes = dict.fromkeys(["上证指数", "深证成指", "创业板指", "沪深300", "中证500"], 0.8)
    pattern = classify_sync_pattern(changes)
    confirmed = build_synchronization_assessment(
        pattern,
        assessment_indices(changes),
        breadth(0.62, 0.8, "2026-09-04"),
        breadth(0.55, 0.2, "2026-09-03"),
    )
    contradicted = build_synchronization_assessment(
        pattern,
        assessment_indices(changes),
        breadth(0.4, -0.5, "2026-09-04"),
    )

    assert confirmed["patternCode"] == "synchronized_rally"
    assert confirmed["status"] == "confirmed"
    assert confirmed["confidence"] == "high"
    assert confirmed["dimensions"]["breadth"]["previousAsOf"] == "2026-09-03"
    assert confirmed["dimensions"]["breadth"]["advanceRatioDelta"] == 0.07
    assert contradicted["patternCode"] == "synchronized_rally"
    assert contradicted["status"] == "contradicted"
    assert contradicted["conclusionCode"] == "index-strength-breadth-divergence"


def test_synchronized_rally_missing_previous_breadth_caps_confidence() -> None:
    changes = dict.fromkeys(["上证指数", "深证成指", "创业板指", "沪深300", "中证500"], 0.8)
    result = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes),
        breadth(0.62, 0.8, "2026-09-04"),
    )

    assert result["status"] == "confirmed"
    assert result["confidence"] == "medium"
    assert result["dimensions"]["breadth"]["comparisonStatus"] == "insufficient"


def test_weight_shelter_requires_negative_breadth_and_does_not_invent_sector_cause() -> None:
    changes = {"上证指数": 0.8, "沪深300": 0.7, "创业板指": -0.2, "中证500": -0.3, "深证成指": 0.1}
    result = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes),
        breadth(0.4, -0.6, "2026-09-04"),
    )

    assert result["status"] == "confirmed"
    assert result["conclusionCode"] == "weight-shelter-confirmed"
    assert "个股偏弱" in result["conclusion"]
    assert not any(name in result["conclusion"] for name in ("银行", "保险", "石油"))


def test_growth_lead_requires_breadth_and_growth_turnover() -> None:
    changes = {"上证指数": -0.2, "沪深300": -0.3, "创业板指": 0.8, "中证500": 0.7, "深证成指": 0.1}
    supported_ratios = {"创业板指": 1.2, "中证500": 1.0}
    weak_ratios = {"创业板指": 0.7, "中证500": 0.7}
    confirmed = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes, supported_ratios),
        breadth(0.6, 0.5, "2026-09-04"),
    )
    contradicted = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes, weak_ratios),
        breadth(0.6, 0.5, "2026-09-04"),
    )

    assert confirmed["status"] == "confirmed"
    assert confirmed["dimensions"]["turnover"]["growthMedianAmountRatio5"] == 1.1
    assert contradicted["status"] == "contradicted"


def test_broad_weakness_only_becomes_systemic_when_all_risk_dimensions_confirm() -> None:
    changes = dict.fromkeys(["上证指数", "深证成指", "创业板指", "沪深300", "中证500"], -0.8)
    confirmed = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes, dict.fromkeys(changes, 1.3), below_ma20=True),
        breadth(0.35, -1.0, "2026-09-04"),
    )
    insufficient = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes, dict.fromkeys(changes, 1.3), below_ma20=True),
        breadth(None, None, "2026-09-04"),
    )

    assert confirmed["status"] == "confirmed"
    assert confirmed["conclusionCode"] == "systemic-decline-confirmed"
    assert confirmed["allFiveWeak"] is True
    assert confirmed["dimensions"]["trend"]["belowMa20Count"] == 5
    assert confirmed["dimensions"]["turnover"]["volumeBackedDeclineCount"] == 5
    assert insufficient["status"] == "insufficient"
    assert insufficient["risks"]


def test_undetermined_pattern_remains_explicit() -> None:
    changes = {"上证指数": 0.2, "沪深300": -0.2, "创业板指": 0.1, "中证500": -0.1, "深证成指": 0.0}
    result = build_synchronization_assessment(
        classify_sync_pattern(changes),
        assessment_indices(changes),
        breadth(0.5, 0.0, "2026-09-04"),
    )

    assert result["status"] == "unconfirmed"
    assert result["conclusionCode"] == "undetermined-divergence"


def test_percentile_metrics_cover_full_reduced_and_insufficient_history() -> None:
    full = make_bars([100 + index * 0.2 + (index % 7) * 0.05 for index in range(300)], [100 + index for index in range(300)])
    reduced = full[:100]
    insufficient = full[:50]
    assert ma20_slope_percentile(full)["confidence"] == "high"
    assert advance_efficiency_percentile(full)["value"] is not None
    assert ma20_slope_percentile(reduced)["confidence"] == "medium"
    assert advance_efficiency_percentile(reduced)["confidence"] == "medium"
    assert ma20_slope_percentile(insufficient)["reason"] == "insufficient-history"
    assert advance_efficiency_percentile(insufficient)["reason"] == "insufficient-history"


def test_bullish_alignment_and_summary_sentence_keep_missing_segments() -> None:
    analyses = [
        {"movingAverages": {"ma5": 12, "ma10": 11, "ma20": 10}},
        {"movingAverages": {"ma5": 9, "ma10": 10, "ma20": 11}},
    ]
    assert bullish_alignment_ratio(analyses) == 0.5
    complete = build_summary_sentence("同步上涨", "MA20上方", "偏强区域", 1.2, "上涨放量", "顺势跟踪")
    partial = build_summary_sentence("同步上涨", None, None, None, None, "保持观察")
    assert "成交额为5日均值的1.20倍" in complete
    assert partial.count("数据不足") == 4
