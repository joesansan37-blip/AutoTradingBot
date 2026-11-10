"""Compact 3-page Telegram overview for the paper simulator."""


def keyboard(active=True):
    return {"inline_keyboard": [
        [{"text": "📊 Overview", "callback_data": "page:overview"},
         {"text": "📈 Performance", "callback_data": "page:performance"},
         {"text": "🧭 Strategy", "callback_data": "page:strategy"}],
        ([{"text": "⏸ Pause", "callback_data": "control:pause"}] if active else
         [{"text": "▶ Resume", "callback_data": "control:resume"}]),
    ]}


def render(page, data):
    page = page if page in {"overview", "performance", "strategy"} else "overview"
    if page == "overview":
        pos = data.get("position")
        position = "No open paper position" if not pos else (
            f"{pos['side']} · entry {pos['entry']:.4f} · uPnL {pos['unrealized_pnl']:+.2f} USDT")
        signal = data.get("signal")
        signal_line = "Signal: waiting for market data" if signal is None else (
            f"Signal: {signal['side'] or '—'} · trend {signal['trend']} · RSI {signal['rsi']:.0f}")
        market = data.get("market", "waiting")
        return (
            f"📊 SOL/USDT · PAPER · {data.get('bot_status', 'ACTIVE')}\n"
            f"{market} · {data.get('timeframe', '15m')} · {data.get('price', '—')} USDT\n"
            f"{signal_line}\n"
            f"Equity {data['equity']:.2f} · available {data['available']:.2f} USDT\n"
            f"{position}\n⚠️ Simulation only; no real orders"
        )
    if page == "performance":
        n = data["daily_trades"]
        rate = f"{data['daily_win_rate_pct']:.0f}%" if n else "—"
        return (
            "📈 PAPER PERFORMANCE · UTC\n"
            f"Today: {data['daily_realized']:+.2f} USDT ({data['daily_return_pct']:+.2f}%)\n"
            f"Closed trades: {n} · wins {data['daily_wins']} · losses {data['daily_losses']} · win rate {rate}\n"
            f"Unrealized: {data['unrealized_pnl']:+.2f} USDT\n"
            f"Drawdown now: {data['drawdown_abs']:.2f} USDT ({data['drawdown_pct']:.2f}%)\n"
            f"Max observed DD: {data['max_drawdown_abs']:.2f} USDT ({data['max_drawdown_pct']:.2f}%)"
        )
    signal = data.get("signal")
    if signal is None:
        details = "Indicators: awaiting candles."
    else:
        reasons = ", ".join(signal.get("filter_reasons", [])) or "all filters passed"
        details = (
            f"Trend: {signal['trend']} · slope {signal['trend_slope_pct'] * 100:+.3f}%\n"
            f"EMA{data['ema_fast_period']}/{data['ema_slow_period']}: "
            f"{signal['ema_fast']:.4f}/{signal['ema_slow']:.4f}\n"
            f"RSI: {signal['rsi']:.1f} · ATR: {signal['atr']:.4f}\n"
            f"Volatility: {signal['volatility_pct'] * 100:.3f}% · "
            f"filter {'OK' if signal['volatility_ok'] else 'BLOCK'}\n"
            f"Decision: {signal['side'] or 'no entry'} ({reasons})"
        )
    return (
        "🧭 STRATEGY FILTERS · PAPER\n"
        f"Trend filter: EMA alignment + slow EMA slope over {data['slope_period']} closed bars\n"
        f"Volatility band: {data['min_volatility_pct'] * 100:.3f}%–"
        f"{data['max_volatility_pct'] * 100:.2f}% ATR/price\n"
        f"RSI thresholds: LONG ≥ {data['rsi_long']:.0f} · SHORT ≤ {data['rsi_short']:.0f}\n"
        f"{details}\nNot financial advice; paper simulation only."
    )
