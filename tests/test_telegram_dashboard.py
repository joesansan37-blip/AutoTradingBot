from telegram_dashboard import keyboard, render


def _data():
    return {
        "bot_status": "ACTIVE", "market": "🟢 data 2s old", "timeframe": "15m", "price": "123.4567",
        "signal": {"side": "LONG", "trend": "BULLISH", "rsi": 61.0, "ema_fast": 122, "ema_slow": 121,
                   "trend_slope_pct": 0.002, "atr": 1.1, "volatility_pct": 0.008,
                   "volatility_ok": True, "filter_reasons": []},
        "equity": 510.0, "available": 480.0, "unrealized_pnl": 2.0,
        "position": {"side": "LONG", "entry": 120.0, "unrealized_pnl": 2.0},
        "daily_trades": 3, "daily_wins": 2, "daily_losses": 1, "daily_win_rate_pct": 66.7,
        "daily_realized": 4.0, "daily_return_pct": 0.8, "drawdown_abs": 3.0, "drawdown_pct": 0.6,
        "max_drawdown_abs": 8.0, "max_drawdown_pct": 1.6,
        "ema_fast_period": 20, "ema_slow_period": 50, "slope_period": 5,
        "min_volatility_pct": 0.003, "max_volatility_pct": 0.05, "rsi_long": 55, "rsi_short": 45,
    }


def test_dashboard_pages_are_compact_and_cover_requested_info():
    data = _data()
    overview = render("overview", data)
    performance = render("performance", data)
    strategy = render("strategy", data)
    assert len(overview) < 500 and "Equity" in overview and "PAPER" in overview
    assert "win rate" in performance and "Max observed DD" in performance
    assert "Trend filter" in strategy and "Volatility band" in strategy


def test_keyboard_has_three_pages_and_pause_toggle():
    buttons = keyboard(active=True)["inline_keyboard"]
    callbacks = [button["callback_data"] for row in buttons for button in row]
    assert callbacks[:3] == ["page:overview", "page:performance", "page:strategy"]
    assert "control:pause" in callbacks
    assert "control:resume" not in callbacks

    paused_callbacks = [button["callback_data"] for row in keyboard(active=False)["inline_keyboard"] for button in row]
    assert "control:resume" in paused_callbacks

