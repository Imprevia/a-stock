from datetime import date, timedelta

from src.market_environment.calculations import (
    Bar,
    amount_ratio,
    classify_index_combination,
    classify_volume_price,
    moving_average,
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
