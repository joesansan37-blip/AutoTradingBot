"""Indicators and signal rules for the paper-only SOL/USDT simulator."""

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0
    atr_period: int = 14
    min_volatility_pct: float = 0.003
    max_position_risk_pct: float = 0.05
    min_position_margin: float = 5.0


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result = result.where(loss.ne(0), 100.0)
    result = result.where(gain.ne(0) | loss.ne(0), 50.0)
    return result.fillna(50.0)


def signal_from_candles(candles: Iterable, config: Optional[StrategyConfig] = None):
    """Return indicators and directional trend signal for already-closed OHLCV candles."""
    cfg = config or StrategyConfig()
    if min(cfg.ema_fast, cfg.ema_slow, cfg.rsi_period, cfg.atr_period) <= 0:
        raise ValueError("Indicator periods must be positive")
    if cfg.ema_fast >= cfg.ema_slow:
        raise ValueError("ema_fast must be less than ema_slow")
    bars = list(candles)
    minimum = max(cfg.ema_slow + 2, cfg.rsi_period + 2, cfg.atr_period + 2)
    if len(bars) < minimum:
        raise ValueError("Not enough closed candles to evaluate strategy")
    df = pd.DataFrame(bars, columns=["time", "open", "high", "low", "close", "volume"])
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[["high", "low", "close"]].isna().any().any() or (df["close"] <= 0).any():
        raise ValueError("Candles contain invalid high, low, or close values")

    close = df["close"]
    df["ema_fast"] = close.ewm(span=cfg.ema_fast, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=cfg.ema_slow, adjust=False).mean()
    df["rsi"] = _rsi(close, cfg.rsi_period)
    previous_close = close.shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()
    last = df.iloc[-1]
    last_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    volatility = last_atr / float(last["close"])
    long_ok = last["ema_fast"] > last["ema_slow"] and last["rsi"] >= cfg.rsi_long_threshold
    short_ok = last["ema_fast"] < last["ema_slow"] and last["rsi"] <= cfg.rsi_short_threshold
    side = "LONG" if long_ok and volatility >= cfg.min_volatility_pct else (
        "SHORT" if short_ok and volatility >= cfg.min_volatility_pct else None)
    return {
        "side": side, "price": float(last["close"]), "high": float(last["high"]),
        "low": float(last["low"]), "rsi": float(last["rsi"]), "atr": last_atr,
        "volatility_pct": volatility, "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
    }


def calculate_position_margin(equity: float, base_margin: float, risk_pct: float = 0.05,
                              min_margin: float = 5.0, max_margin: float = 200.0) -> float:
    """Return a conservative paper margin cap based on equity and configured base margin."""
    equity, base_margin = float(equity), float(base_margin)
    if equity <= 0 or base_margin <= 0:
        return 0.0
    risk_budget = equity * max(0.0, min(float(risk_pct), 1.0))
    margin = min(base_margin, risk_budget)
    if margin < min_margin and base_margin >= min_margin and risk_budget >= min_margin:
        margin = min_margin
    if max_margin > 0:
        margin = min(margin, max_margin)
    return max(0.0, min(margin, base_margin))
