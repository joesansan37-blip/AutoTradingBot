from strategy import StrategyConfig, calculate_position_margin, signal_from_candles


def _candles(close_values):
    return [[i, close - 0.2, close + 1.0, close - 1.0, close, 100.0]
            for i, close in enumerate(close_values)]


def test_uptrend_signal_includes_indicators():
    candles = _candles([100 + i * 0.2 for i in range(100)])
    result = signal_from_candles(candles, StrategyConfig(min_volatility_pct=0.001))
    assert result["side"] == "LONG"
    assert result["ema_fast"] > result["ema_slow"]
    assert result["rsi"] >= 55
    assert result["atr"] > 0


def test_low_volatility_suppresses_signal():
    candles = [[i, 100.0, 100.01, 99.99, 100.0, 10.0] for i in range(100)]
    result = signal_from_candles(candles)
    assert result["side"] is None
    assert result["volatility_pct"] < 0.003


def test_invalid_candle_count_and_periods_are_rejected():
    try:
        signal_from_candles(_candles([100.0] * 10))
        assert False, "expected insufficient candles to fail"
    except ValueError as exc:
        assert "Not enough" in str(exc)
    try:
        signal_from_candles(_candles([100.0] * 100), StrategyConfig(ema_fast=50, ema_slow=20))
        assert False, "expected invalid EMA ordering to fail"
    except ValueError as exc:
        assert "ema_fast" in str(exc)


def test_position_margin_respects_equity_and_base_caps():
    assert calculate_position_margin(500, 25, risk_pct=0.05) == 25
    assert calculate_position_margin(40, 25, risk_pct=0.05) == 5
    assert calculate_position_margin(20, 25, risk_pct=0.05) == 1
    assert calculate_position_margin(1000, 3, min_margin=5) == 3
