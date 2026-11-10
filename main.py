"""Environment parsing and production logging helpers."""

import json
import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    execution_mode: str = "paper"
    symbol: str = "SOL/USDT"
    timeframe: str = "15m"
    data_exchange: str = "kraken"
    leverage: int = 2
    order_margin_usdt: float = 25.0
    starting_balance_usdt: float = 500.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    paper_fee_rate: float = 0.0006
    max_daily_loss_usdt: float = 25.0
    scan_seconds: int = 15
    state_file: str = "paper_account.json"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    log_level: str = "INFO"
    log_format: str = "plain"


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _bool(name, default=True):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be true/false")
    return value in {"true", "1", "yes"}


def load_config():
    cfg = AppConfig(
        execution_mode=os.getenv("EXECUTION_MODE", "paper").strip().lower(),
        symbol=os.getenv("TRADING_SYMBOL", "SOL/USDT").strip(),
        timeframe=os.getenv("TIMEFRAME", "15m").strip(),
        data_exchange=os.getenv("DATA_EXCHANGE", "kraken").strip().lower(),
        leverage=_int("LEVERAGE", 2),
        order_margin_usdt=_float("ORDER_MARGIN_USDT", 25),
        starting_balance_usdt=_float("PAPER_STARTING_BALANCE_USDT", 500),
        stop_loss_pct=_float("STOP_LOSS_PCT", 2),
        take_profit_pct=_float("TAKE_PROFIT_PCT", 4),
        paper_fee_rate=_float("PAPER_FEE_RATE", 0.0006),
        max_daily_loss_usdt=_float("MAX_DAILY_LOSS_USDT", 25),
        scan_seconds=_int("SCAN_SECONDS", 15),
        state_file=os.getenv("PAPER_STATE_FILE", "paper_account.json").strip(),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        log_format=os.getenv("LOG_FORMAT", "plain").strip().lower(),
    )
    if cfg.execution_mode != "paper":
        raise ValueError("Only EXECUTION_MODE=paper is supported; live trading is not implemented")
    if cfg.symbol != "SOL/USDT":
        raise ValueError("This simulator is limited to TRADING_SYMBOL=SOL/USDT")
    if not 1 <= cfg.leverage <= 10:
        raise ValueError("LEVERAGE must be between 1 and 10")
    if min(cfg.order_margin_usdt, cfg.starting_balance_usdt, cfg.max_daily_loss_usdt) <= 0:
        raise ValueError("Paper balance, order margin, and daily loss limit must be positive")
    if not 0 < cfg.paper_fee_rate < 0.01:
        raise ValueError("PAPER_FEE_RATE must be between 0 and 0.01")
    if not 0 < cfg.scan_seconds <= 3600:
        raise ValueError("SCAN_SECONDS must be between 1 and 3600")
    if not cfg.state_file:
        raise ValueError("PAPER_STATE_FILE must not be empty")
    if cfg.log_level not in logging.getLevelNamesMapping():
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    if cfg.log_format not in {"plain", "json"}:
        raise ValueError("LOG_FORMAT must be plain or json")
    if bool(cfg.telegram_token) != bool(cfg.telegram_chat_id):
        raise ValueError("Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or leave both empty")
    return cfg


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level="INFO", log_format="plain"):
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper()))
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)
