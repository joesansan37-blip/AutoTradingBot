"""Selectable paper-only strategy profiles for SOL/USDT simulation.

Strategies generate signals only. Execution is handled by the local paper ledger; this
project does not submit exchange orders.
"""

import pandas as pd

STRATEGIES = ("ema_trend", "rsi_reversion", "donchian_breakout", "multiasset_trend_pro")


def _wilder(series, period):
    """Wilder's recursive moving average, approximated with pandas EWM."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _multiasset_trend_pro(df):
    """MQL5-derived EMA(12/26) cross with ADX(14) filter and ATR stops."""
    close, high, low = df["close"], df["high"], df["low"]
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, 14)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smooth_tr = _wilder(tr, 14)
    plus_di = 100.0 * _wilder(plus_dm, 14) / smooth_tr.replace(0, 1e-12)
    minus_di = 100.0 * _wilder(minus_dm, 14) / smooth_tr.replace(0, 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    adx = _wilder(dx, 14)

    i, prev_i = len(df) - 1, len(df) - 2
    atr_now, adx_now = atr.iloc[i], adx.iloc[i]
    result = {
        "side": None,
        "adx": float(adx_now) if pd.notna(adx_now) else None,
        "atr": float(atr_now) if pd.notna(atr_now) else None,
        "stop_loss": None,
        "take_profit": None,
    }
    if result["atr"] is None or result["adx"] is None or result["adx"] < 22.0:
        return result

    price = float(close.iloc[i])
    crossed_up = ema_fast.iloc[i] > ema_slow.iloc[i] and ema_fast.iloc[prev_i] <= ema_slow.iloc[prev_i]
    crossed_down = ema_fast.iloc[i] < ema_slow.iloc[i] and ema_fast.iloc[prev_i] >= ema_slow.iloc[prev_i]
    if crossed_up:
        result.update(side="LONG", stop_loss=price - result["atr"] * 1.8,
                      take_profit=price + result["atr"] * 3.0)
    elif crossed_down:
        result.update(side="SHORT", stop_loss=price + result["atr"] * 1.8,
                      take_profit=price - result["atr"] * 3.0)
    return result


def signal_from_candles(candles, strategy="ema_trend"):
    """Return a signal using closed OHLCV bars only.

    Standard result fields: strategy, side (LONG/SHORT/None), price, high, low, rsi.
    The ``multiasset_trend_pro`` profile also returns ``adx``, ``atr``, ``stop_loss``
    and ``take_profit``. Like all indicator ports, it is an approximation of MT5.
    """
    strategy = strategy.strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}; choose from {', '.join(STRATEGIES)}")
    if not candles or len(candles) < 60:
        raise ValueError("At least 60 candles are needed")

    # The final CCXT candle may still be forming. Exclude it from every indicator.
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
    else:
        extras = _multiasset_trend_pro(df)
        side = extras["side"]

    last = df.iloc[-1]
    result = {"strategy": strategy, "side": side, "price": float(last.close),
              "high": float(last.high), "low": float(last.low), "rsi": float(last.rsi)}
    result.update(extras)
    return result
