"""Indicators and configurable trend/volatility filters for paper-only SOL/USDT."""

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
    max_volatility_pct: float = 0.05
    trend_slope_period: int = 5
    trend_slope_filter: bool = True
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
    """Evaluate closed OHLCV bars; include filter diagnostics for dashboards."""
    cfg = config or StrategyConfig()
    if min(cfg.ema_fast, cfg.ema_slow, cfg.rsi_period, cfg.atr_period, cfg.trend_slope_period) <= 0:
        raise ValueError("Indicator periods must be positive")
    if cfg.ema_fast >= cfg.ema_slow:
        raise ValueError("ema_fast must be less than ema_slow")
    if not 0 <= cfg.min_volatility_pct <= cfg.max_volatility_pct:
        raise ValueError("Volatility bounds must satisfy 0 <= min <= max")
    bars = list(candles)
    minimum = max(cfg.ema_slow + cfg.trend_slope_period + 2, cfg.rsi_period + 2, cfg.atr_period + 2)
    if len(bars) < minimum:
        raise ValueError("Not enough closed candles to evaluate strategy")
    df = pd.DataFrame(bars, columns=["time", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["high", "low", "close"]].isna().any().any() or (df["close"] <= 0).any():
        raise ValueError("Candles contain invalid high, low, or close values")

    close = df["close"]
    fast = close.ewm(span=cfg.ema_fast, adjust=False).mean()
    slow = close.ewm(span=cfg.ema_slow, adjust=False).mean()
    rsi = _rsi(close, cfg.rsi_period)
    previous_close = close.shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()

    last_close = float(close.iloc[-1])
    last_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    vol_pct = last_atr / last_close
    fast_last, slow_last = float(fast.iloc[-1]), float(slow.iloc[-1])
    slow_then = float(slow.iloc[-1 - cfg.trend_slope_period])
    slope_pct = (slow_last - slow_then) / slow_then if slow_then else 0.0
    trend = "BULLISH" if fast_last > slow_last else "BEARISH" if fast_last < slow_last else "NEUTRAL"
    trend_ok_long = trend == "BULLISH" and (not cfg.trend_slope_filter or slope_pct > 0)
    trend_ok_short = trend == "BEARISH" and (not cfg.trend_slope_filter or slope_pct < 0)
    volatility_ok = cfg.min_volatility_pct <= vol_pct <= cfg.max_volatility_pct
    long_ok = trend_ok_long and float(rsi.iloc[-1]) >= cfg.rsi_long_threshold and volatility_ok
    short_ok = trend_ok_short and float(rsi.iloc[-1]) <= cfg.rsi_short_threshold and volatility_ok
    side = "LONG" if long_ok else "SHORT" if short_ok else None

    reasons = []
    if not volatility_ok:
        reasons.append("volatility_below_min" if vol_pct < cfg.min_volatility_pct else "volatility_above_max")
    if trend == "NEUTRAL" or (trend == "BULLISH" and not trend_ok_long) or (trend == "BEARISH" and not trend_ok_short):
        reasons.append("trend_slope_filter")
    if side is None and not reasons:
        reasons.append("rsi_filter")
    return {
        "side": side, "price": last_close, "high": float(df["high"].iloc[-1]),
        "low": float(df["low"].iloc[-1]), "rsi": float(rsi.iloc[-1]), "atr": last_atr,
        "volatility_pct": vol_pct, "volatility_ok": volatility_ok,
        "ema_fast": fast_last, "ema_slow": slow_last, "trend": trend,
        "trend_slope_pct": slope_pct, "trend_slope_ok": trend_ok_long if trend == "BULLISH" else trend_ok_short,
        "filter_reasons": reasons,
    }


def calculate_position_margin(equity: float, base_margin: float, risk_pct: float = 0.05,
                              min_margin: float = 5.0, max_margin: float = 200.0) -> float:
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
