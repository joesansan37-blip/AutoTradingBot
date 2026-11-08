"""Selectable paper-only strategy profiles for SOL/USDT linear perpetual simulation.

These are Python strategies, not MetaTrader Expert Advisors. They produce signals only;
execution remains in the paper ledger and this project submits no real orders.
"""

import pandas as pd

STRATEGIES = ("ema_trend", "rsi_reversion", "donchian_breakout")


def signal_from_candles(candles, strategy="ema_trend"):
    """Return a signal using closed OHLCV candles only.

    Result keys: strategy, side (LONG/SHORT/None), price, high, low, rsi.
    """
    strategy = strategy.strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    if not candles or len(candles) < 60:
        raise ValueError("At least 60 candles are needed")

    # CCXT's final OHLCV candle may still be forming; do not make a signal from it.
    df = pd.DataFrame(candles[:-1], columns=["time", "open", "high", "low", "close", "volume"])
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(df) < 55:
        raise ValueError("Not enough valid closed candles")

    close = df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-12))
    df["ema_fast"] = close.ewm(span=20, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=50, adjust=False).mean()

    side = None
    if strategy == "ema_trend":
        prev, last = df.iloc[-2], df.iloc[-1]
        if prev.ema_fast <= prev.ema_slow and last.ema_fast > last.ema_slow and last.rsi > 50:
            side = "LONG"
        elif prev.ema_fast >= prev.ema_slow and last.ema_fast < last.ema_slow and last.rsi < 50:
            side = "SHORT"

    elif strategy == "rsi_reversion":
        # Bollinger excursion followed by a close back inside, confirmed by RSI recovery.
        df["bb_mid"] = close.rolling(20).mean()
        std = close.rolling(20).std(ddof=0)
        df["bb_upper"] = df["bb_mid"] + 2 * std
        df["bb_lower"] = df["bb_mid"] - 2 * std
        prev, last = df.iloc[-2], df.iloc[-1]
        if prev.close <= prev.bb_lower and last.close > last.bb_lower and prev.rsi < 35 and last.rsi > prev.rsi:
            side = "LONG"
        elif prev.close >= prev.bb_upper and last.close < last.bb_upper and prev.rsi > 65 and last.rsi < prev.rsi:
            side = "SHORT"

    elif strategy == "donchian_breakout":
        # Compare the newest closed candle to the preceding 20 bars, excluding itself.
        lookback = df.iloc[-21:-1]
        prev, last = df.iloc[-2], df.iloc[-1]
        upper = float(lookback["high"].max())
        lower = float(lookback["low"].min())
        if last.close > upper and last.close > last.ema_slow:
            side = "LONG"
        elif last.close < lower and last.close < last.ema_slow:
            side = "SHORT"

    last = df.iloc[-1]
    return {
        "strategy": strategy,
        "side": side,
        "price": float(last.close),
        "high": float(last.high),
        "low": float(last.low),
        "rsi": float(last.rsi),
    }
