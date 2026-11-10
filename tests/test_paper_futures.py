import os
import tempfile
import unittest

from paper_futures import PaperFutures


class PaperFuturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "paper.json")
        self.account = PaperFutures(self.path, 500, 2, 0.0006, 2, 4, 25)

    def tearDown(self):
        self.tmp.cleanup()

    def test_custom_atr_levels_are_used_for_position(self):
        position = self.account.open_position(
            "SOL/USDT", "LONG", 100, 25, stop_loss=98, take_profit=103
        )
        self.assertEqual(position["stop_loss"], 98)
        self.assertEqual(position["take_profit"], 103)

    def test_long_trailing_stop_only_moves_up(self):
        self.account.open_position("SOL/USDT", "LONG", 100, 25, stop_loss=95, take_profit=110)
        self.assertTrue(self.account.update_trailing_stop("SOL/USDT", 102, 1, 1, 1.5))
        stop_after_break_even = self.account.state["positions"]["SOL/USDT"]["stop_loss"]
        self.assertGreaterEqual(stop_after_break_even, 100)
        self.assertFalse(self.account.update_trailing_stop("SOL/USDT", 101, 1, 1, 1.5))
        self.assertEqual(self.account.state["positions"]["SOL/USDT"]["stop_loss"], stop_after_break_even)

    def test_short_trailing_stop_only_moves_down(self):
        self.account.open_position("SOL/USDT", "SHORT", 100, 25, stop_loss=105, take_profit=90)
        self.assertTrue(self.account.update_trailing_stop("SOL/USDT", 98, 1, 1, 1.5))
        stop_after_break_even = self.account.state["positions"]["SOL/USDT"]["stop_loss"]
        self.assertLessEqual(stop_after_break_even, 100)
        self.assertFalse(self.account.update_trailing_stop("SOL/USDT", 99, 1, 1, 1.5))
        self.assertEqual(self.account.state["positions"]["SOL/USDT"]["stop_loss"], stop_after_break_even)

    def test_custom_levels_must_be_on_correct_side(self):
        with self.assertRaises(ValueError):
            self.account.open_position("SOL/USDT", "LONG", 100, 25, stop_loss=101, take_profit=110)


if __name__ == "__main__":
    unittest.main()
