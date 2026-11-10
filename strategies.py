"""Selectable paper-only SOL/USDT strategy profiles.

Strategies produce signals only; execution remains in the paper ledger. No real orders
are submitted by this project.
"""

import pandas as pd

STRATEGIES = ("ema_trend", "rsi_reversion", "donchian_breakout", "multiasset_trend_pro")


def _wilder(series, period):
    """Wilder smoothing, used to approximate MT5's ADX and ATR indicators."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _multiasset_trend_pro(df):
    """Compute closed-bar EMA(12/26), ADX(14), ATR(14), and EMA-cross signal."""
    fast_period, slow_period, adx_period, atr_period = 12, 26, 14, 14
    close, high, low = df["close"], df["high"], df["low"]
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = _wilder(true_range, atr_period)

    up_move, down_move = high.diff(), -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_tr = _wilder(true_range, adx_period)
    plus_di = 100.0 * _wilder(plus_dm, adx_period) / smoothed_tr.replace(0, 1e-12)
    minus_di = 100.0 * _wilder(minus_dm, adx_period) / smoothed_tr.replace(0, 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    adx = _wilder(dx, adx_period)

    last_idx, prev_idx = len(df) - 1, len(df) - 2
    atr_value, adx_value = atr.iloc[last_idx], adx.iloc[last_idx]
    result = {
        "side": None,
        "ema_fast": float(ema_fast.iloc[last_idx]),
        "ema_slow": float(ema_slow.iloc[last_idx]),
        "atr": float(atr_value) if pd.notna(atr_value) else None,
        "adx": float(adx_value) if pd.notna(adx_value) else None,
        "stop_loss": None,
        "take_profit": None,
    }
    if result["atr"] is None or result["adx"] is None:
        return result

    price = float(close.iloc[last_idx])
    if result["adx"] >= 22.0:
        if ema_fast.iloc[last_idx] > ema_slow.iloc[last_idx] and ema_fast.iloc[prev_idx] <= ema_slow.iloc[prev_idx]:
            result.update(side="LONG", stop_loss=price - result["atr"] * 1.8,
                          take_profit=price + result["atr"] * 3.0)
        elif ema_fast.iloc[last_idx] < ema_slow.iloc[last_idx] and ema_fast.iloc[prev_idx] >= ema_slow.iloc[prev_idx]:
            result.update(side="SHORT", stop_loss=price + result["atr"] * 1.8,
                          take_profit=price - result["atr"] * 3.0)
    return result


def signal_from_candles(candles, strategy="ema_trend"):
    """Return a signal using closed OHLCV candles only.

    Every profile returns strategy, side, price, high, low, and RSI. The converted MQL5
    profile additionally returns ADX, ATR, and ATR-derived stop/target levels.
    """
    strategy = strategy.strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    if not candles or len(candles) < 60:
        raise ValueError("At least 60 candles are needed")

    # The final CCXT OHLCV candle may still be forming; do not use it for signals.
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

    side, extras = None, {}
    if strategy == "ema_trend":
        prev, last = df.iloc[-2], df.iloc[-1]
        if prev.ema_fast <= prev.ema_slow and last.ema_fast > last.ema_slow and last.rsi > 50:
            side = "LONG"
        elif prev.ema_fast >= prev.ema_slow and last.ema_fast < last.ema_slow and last.rsi < 50:
            side = "SHORT"

    elif strategy == "rsi_reversion":
        df["bb_mid"] = close.rolling(20).mean()
        std = close.rolling(20).std(ddof=0)
        df["bb_upper"], df["bb_lower"] = df["bb_mid"] + 2 * std, df["bb_mid"] - 2 * std
        prev, last = df.iloc[-2], df.iloc[-1]
        if prev.close <= prev.bb_lower and last.close > last.bb_lower and prev.rsi < 35 and last.rsi > prev.rsi:
            side = "LONG"
        elif prev.close >= prev.bb_upper and last.close < last.bb_upper and prev.rsi > 65 and last.rsi < prev.rsi:
            side = "SHORT"

    elif strategy == "donchian_breakout":
        lookback, last = df.iloc[-21:-1], df.iloc[-1]
        upper, lower = float(lookback["high"].max()), float(lookback["low"].min())
        if last.close > upper and last.close > last.ema_slow:
            side = "LONG"
        elif last.close < lower and last.close < last.ema_slow:
            side = "SHORT"

    elif strategy == "multiasset_trend_pro":
        extras = _multiasset_trend_pro(df)
        side = extras["side"]

    last = df.iloc[-1]
    result = {"strategy": strategy, "side": side, "price": float(last.close),
              "high": float(last.high), "low": float(last.low), "rsi": float(last.rsi)}
    result.update(extras)
    return result
