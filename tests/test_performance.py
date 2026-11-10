import json

from paper_futures import PaperFutures


def _account(tmp_path):
    return PaperFutures(str(tmp_path / "ledger.json"), 500, 2, 0.0006, 2, 4, 25)


def test_performance_metrics_and_drawdown_are_persisted(tmp_path):
    account = _account(tmp_path)
    account.open_position("SOL/USDT", "LONG", 100, 25)

    at_loss = account.snapshot({"SOL/USDT": 90})
    assert at_loss["drawdown_abs"] > 0
    assert at_loss["max_drawdown_abs"] == at_loss["drawdown_abs"]
    assert at_loss["max_drawdown_pct"] > 0

    closed = account.close_position("SOL/USDT", 90, "test")
    assert closed["net_pnl"] < 0
    metrics = account.snapshot()
    assert metrics["daily_trades"] == 1
    assert metrics["daily_losses"] == 1
    assert metrics["daily_wins"] == 0
    assert metrics["daily_realized"] < 0

    reloaded = _account(tmp_path).snapshot()
    assert reloaded["max_drawdown_abs"] >= metrics["max_drawdown_abs"]
    assert reloaded["max_drawdown_pct"] >= metrics["max_drawdown_pct"]
    saved = json.loads((tmp_path / "ledger.json").read_text())
    assert "max_drawdown_pct" in saved


def test_daily_win_rate_counts_closed_trades_only(tmp_path):
    account = _account(tmp_path)
    account.open_position("SOL/USDT", "LONG", 100, 25)
    account.close_position("SOL/USDT", 110, "test_win")
    account.open_position("SOL/USDT", "SHORT", 100, 25)
    account.close_position("SOL/USDT", 90, "test_win")

    metrics = account.snapshot()
    assert metrics["daily_trades"] == 2
    assert metrics["daily_wins"] == 2
    assert metrics["daily_losses"] == 0
    assert metrics["daily_win_rate_pct"] == 100
