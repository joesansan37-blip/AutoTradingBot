import unittest

from strategies import STRATEGIES, signal_from_candles


class StrategyTests(unittest.TestCase):
    def setUp(self):
        # Smooth upward synthetic market plus a forming candle that must be ignored.
        self.candles = []
        for i in range(120):
            close = 100 + i * 0.1
            self.candles.append([i * 60_000, close, close + 0.2, close - 0.2, close, 10])

    def test_all_profiles_return_consistent_signal_schema(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                result = signal_from_candles(self.candles, strategy)
                self.assertEqual(result["strategy"], strategy)
                self.assertIn(result["side"], (None, "LONG", "SHORT"))
                self.assertGreater(result["price"], 0)
                self.assertGreaterEqual(result["high"], result["low"])

    def test_mql5_profile_includes_adx_atr_and_atr_levels(self):
        result = signal_from_candles(self.candles, "multiasset_trend_pro")
        self.assertIsNotNone(result["atr"])
        self.assertIsNotNone(result["adx"])
        self.assertGreater(result["atr"], 0)
        self.assertGreaterEqual(result["adx"], 0)
        self.assertIn("stop_loss", result)
        self.assertIn("take_profit", result)

    def test_mql5_profile_ignores_forming_candle(self):
        baseline = signal_from_candles(self.candles, "multiasset_trend_pro")
        changed = [row[:] for row in self.candles]
        changed[-1][4] = 10_000
        self.assertEqual(baseline, signal_from_candles(changed, "multiasset_trend_pro"))

    def test_invalid_strategy_rejected(self):
        with self.assertRaises(ValueError):
            signal_from_candles(self.candles, "unknown")

    def test_insufficient_candles_rejected(self):
        with self.assertRaises(ValueError):
            signal_from_candles(self.candles[:20], "ema_trend")


if __name__ == "__main__":
    unittest.main()
