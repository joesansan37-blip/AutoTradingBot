def _performance_text(snapshot):
    count = snapshot["daily_trades"]
    win_rate = f"{snapshot['daily_win_rate_pct']:.0f}%" if count else "—"
    return (
        "📈 RENDIMIENTO UTC\n"
        f"Hoy: {snapshot['daily_realized']:+.2f} USDT ({snapshot['daily_return_pct']:+.2f}%)\n"
        f"Operaciones: {count} · ✅ {snapshot['daily_wins']} · ❌ {snapshot['daily_losses']} · "
        f"Win rate: {win_rate}\n"
        f"Drawdown actual: {snapshot['drawdown_abs']:.2f} USDT ({snapshot['drawdown_pct']:.2f}%)\n"
        f"Máximo drawdown observado: {snapshot['max_drawdown_abs']:.2f} USDT "
        f"({snapshot['max_drawdown_pct']:.2f}%)"
    )


def dashboard_text():
    with runtime_lock:
        mark, updated, error, active, sig = last_mark, last_market_update, last_market_error, trading_active, last_signal
    prices = {SYMBOL: mark} if mark is not None else {}
    snap = account.snapshot(prices)
    if updated is None:
        market = "⚪ esperando datos"
    elif error:
        market = "🔴 error de mercado"
    else:
        age = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
        market = f"🟢 datos {age}s"
    signal = "—" if sig is None else (sig["side"] or "sin señal")
    price_text = f"{mark:,.4f}" if mark is not None else "—"
    pos = snap["positions"]
    pos_text = "sin posición" if not pos else f"{pos[0]['side']} @ {pos[0]['entry']:.4f} · PnL {pos[0]['unrealized_pnl']:+.2f}"
    return (
        f"📊 SOL/USDT  ·  {'▶ ACTIVO' if active else '⏸ PAUSADO'}\n"
        f"{market}  ·  {TIMEFRAME}  ·  {price_text} USDT\n"
        f"🧭 Señal: {signal}"
        + (f" · RSI {sig['rsi']:.0f}" if sig else "")
        + f"\n💼 Equity {snap['equity']:.2f}  ·  Disponible {snap['available']:.2f} USDT"
        + f"\n📈 Hoy {snap['daily_realized']:+.2f} USDT ({snap['daily_return_pct']:+.2f}%)"
        + f"\n📉 DD máx. {snap['max_drawdown_abs']:.2f} USDT ({snap['max_drawdown_pct']:.2f}%)"
        + f"\n📍 {pos_text}\n🧪 PAPER · sin órdenes reales"
        + (f"\n⚠️ {error[:120]}" if error else "")
    )


def status_text():
    return dashboard_text()


def performance_text():
    prices = {SYMBOL: last_mark} if last_mark is not None else {}
    return _performance_text(account.snapshot(prices))


