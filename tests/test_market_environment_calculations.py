from datetime import date, timedelta

from src.market_environment.calculations import (
    Bar,
    amount_ratio,
    classify_volume_price,
    moving_average,
    range_position,
)


def make_bars(closes: list[float], amounts: list[float] | None = None) -> list[Bar]:
    amounts = amounts or [100.0] * len(closes)
    return [
        Bar(
            date=date(2026, 1, 1) + timedelta(days=index),
            open=close,
            close=close,
            high=close,
            low=close,
            amount=amount,
        )
        for index, (close, amount) in enumerate(zip(closes, amounts))
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
