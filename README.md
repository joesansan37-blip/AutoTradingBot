from strategy import StrategyConfig, calculate_position_margin, signal_from_candles


def _candles_for_signal(trend: str, length: int = 120):
    candles = []
    price = 100.0
    for i in range(length):
        if i < 80:
            close = 100.0 + ((i % 7) - 3) * 0.2
        else:
            close = 100.0 + (i - 79) * 0.75 if trend == "long" else 100.0 - (i - 79) * 0.75
        open_price = close - 0.4
        high = max(open_price, close) + 0.8
        low = min(open_price, close) - 0.8
        candles.append([i * 60000, open_price, high, low, close, 1000.0])
    return candles


def test_bullish_signal_detected():
    signal = signal_from_candles(_candles_for_signal("long"), StrategyConfig())
    assert signal["side"] == "LONG"
    assert signal["rsi"] >= 55


def test_bearish_signal_detected():
    signal = signal_from_candles(_candles_for_signal("short"), StrategyConfig())
    assert signal["side"] == "SHORT"
    assert signal["rsi"] <= 45


def test_position_margin_is_capped_by_risk_budget():
    margin = calculate_position_margin(500.0, 25.0, risk_pct=0.05, min_margin=5.0, max_margin=200.0)
    assert margin == 25.0

    margin_low_equity = calculate_position_margin(40.0, 25.0, risk_pct=0.05, min_margin=5.0, max_margin=200.0)
    assert margin_low_equity == 5.0

    margin_small_base = calculate_position_margin(1000.0, 3.0, risk_pct=0.05, min_margin=5.0, max_margin=200.0)
    assert margin_small_base == 3.0


# coverage to keep the strategy robust for a real market cycle
__all__ = ["StrategyConfig", "signal_from_candles", "calculate_position_margin"]

