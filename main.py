from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0
    atr_period: int = 14
    atr_multiplier: float = 1.5
    min_volatility_pct: float = 0.003
    max_position_risk_pct: float = 0.05
    min_position_margin: float = 5.0


def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_gain = up.rolling(window=period, min_periods=period).mean()
    avg_loss = down.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / (avg_loss.replace(0, pd.NA) + 1e-9)
    return 100 - (100 / (1 + rs)).fillna(50.0)


def signal_from_candles(candles: Iterable, config: Optional[StrategyConfig] = None):
    cfg = config or StrategyConfig()
    bars = list(candles)
    if len(bars) < max(60, cfg.ema_slow + cfg.rsi_period + 10):
        raise ValueError("Not enough candles to evaluate the strategy")

    df = pd.DataFrame(bars, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})

    df["fast"] = df["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    df["slow"] = df["close"].ewm(span=cfg.ema_slow, adjust=False).mean()
    df["rsi"] = _compute_rsi(df["close"], cfg.rsi_period)

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = (
        df[["high", "low", "prev_close"]].max(axis=1) - df[["high", "low", "prev_close"]].min(axis=1)
    ).abs()
    df["atr"] = df["tr"].rolling(cfg.atr_period, min_periods=cfg.atr_period).mean()

    prev = df.iloc[-2]
    last = df.iloc[-1]
    atr_pct = (float(last["atr"]) / max(float(last["close"]), 1e-9)) if pd.notna(last["atr"]) else 0.0

    long_signal = (
        float(prev["fast"]) <= float(prev["slow"]) and
        float(last["fast"]) > float(last["slow"]) and
        float(last["rsi"]) >= cfg.rsi_long_threshold and
        atr_pct >= cfg.min_volatility_pct
    )
    short_signal = (
        float(prev["fast"]) >= float(prev["slow"]) and
        float(last["fast"]) < float(last["slow"]) and
        float(last["rsi"]) <= cfg.rsi_short_threshold and
        atr_pct >= cfg.min_volatility_pct
    )

    side = "LONG" if long_signal else "SHORT" if short_signal else None
    signal = {
        "side": side,
        "price": float(last["close"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "rsi": float(last["rsi"]),
        "atr": float(last["atr"]) if pd.notna(last["atr"]) else 0.0,
        "volatility_pct": atr_pct,
        "ema_fast": float(last["fast"]),
        "ema_slow": float(last["slow"]),
    }
    return signal


def calculate_position_margin(equity: float, base_margin: float, risk_pct: float = 0.05,
                              min_margin: float = 5.0, max_margin: float = 200.0) -> float:
    if base_margin <= 0:
        return 0.0
    risk_budget = equity * max(0.0, min(risk_pct, 1.0))
    margin = min(base_margin, risk_budget)
    if margin < min_margin and base_margin >= min_margin:
        margin = min_margin
    if max_margin > 0:
        margin = min(margin, max_margin)
    return max(0.0, min(margin, base_margin))
