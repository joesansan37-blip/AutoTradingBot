from strategy import StrategyConfig, signal_from_candles


def _candles(values, spread=1.0):
    return [[i, close, close + spread, close - spread, close, 100.0]
            for i, close in enumerate(values)]


def test_trending_signal_and_filter_diagnostics():
    closes = [100 + i * 0.2 for i in range(120)]
    result = signal_from_candles(_candles(closes), StrategyConfig(min_volatility_pct=0.001))
    assert result["trend"] == "BULLISH"
    assert result["trend_slope_ok"]
    assert result["side"] == "LONG"
    assert result["volatility_ok"]


def test_too_low_and_too_high_volatility_block_entries():
    closes = [100 + i * 0.2 for i in range(120)]
    quiet = signal_from_candles(_candles(closes, spread=0.001),
                                StrategyConfig(min_volatility_pct=0.01, max_volatility_pct=0.1))
    volatile = signal_from_candles(_candles(closes, spread=10),
                                   StrategyConfig(min_volatility_pct=0.001, max_volatility_pct=0.02))
    assert not quiet["volatility_ok"] and quiet["side"] is None
    assert not volatile["volatility_ok"] and volatile["side"] is None


def test_invalid_volatility_band_rejected():
    try:
        signal_from_candles(_candles([100 + i * .1 for i in range(120)]),
                            StrategyConfig(min_volatility_pct=.1, max_volatility_pct=.01))
        assert False, "expected invalid volatility bounds"
    except ValueError as exc:
        assert "Volatility bounds" in str(exc)
