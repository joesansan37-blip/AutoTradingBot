"""Paper-only SOL/USDT simulator with a compact Telegram dashboard."""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ccxt
import requests

from paper_futures import PaperFutures
from strategy import StrategyConfig, calculate_position_margin, signal_from_candles
from telegram_dashboard import keyboard, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
if os.getenv("EXECUTION_MODE", "paper").strip().lower() != "paper":
    raise RuntimeError("Only EXECUTION_MODE=paper is supported; live trading is not implemented.")

SYMBOL = os.getenv("TRADING_SYMBOL", "SOL/USDT").strip()
TIMEFRAME = os.getenv("TIMEFRAME", "15m").strip()
DATA_EXCHANGE = os.getenv("DATA_EXCHANGE", "kraken").strip().lower()
LEVERAGE = int(os.getenv("LEVERAGE", "2"))
ORDER_MARGIN_USDT = float(os.getenv("ORDER_MARGIN_USDT", "25"))
STARTING_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE_USDT", "500"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "4"))
PAPER_FEE_RATE = float(os.getenv("PAPER_FEE_RATE", "0.0006"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS_USDT", "25"))
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "15"))
STATE_PATH = os.getenv("PAPER_STATE_FILE", "paper_account.json")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

if SYMBOL != "SOL/USDT":
    raise ValueError("This simulator is limited to TRADING_SYMBOL=SOL/USDT")
if not 1 <= LEVERAGE <= 10:
    raise ValueError("Set LEVERAGE between 1 and 10")
if min(ORDER_MARGIN_USDT, STARTING_BALANCE, MAX_DAILY_LOSS) <= 0:
    raise ValueError("Balance, order margin, and daily loss limit must be positive")
if not 0 < PAPER_FEE_RATE < 0.01:
    raise ValueError("PAPER_FEE_RATE must be between 0 and 0.01")

STRATEGY_CONFIG = StrategyConfig(
    ema_fast=int(os.getenv("STRATEGY_EMA_FAST", "20")),
    ema_slow=int(os.getenv("STRATEGY_EMA_SLOW", "50")),
    rsi_period=int(os.getenv("STRATEGY_RSI_PERIOD", "14")),
    rsi_long_threshold=float(os.getenv("STRATEGY_RSI_LONG", "55")),
    rsi_short_threshold=float(os.getenv("STRATEGY_RSI_SHORT", "45")),
    atr_period=int(os.getenv("STRATEGY_ATR_PERIOD", "14")),
    min_volatility_pct=float(os.getenv("STRATEGY_MIN_VOLATILITY_PCT", "0.003")),
    max_volatility_pct=float(os.getenv("STRATEGY_MAX_VOLATILITY_PCT", "0.05")),
    trend_slope_period=int(os.getenv("STRATEGY_TREND_SLOPE_PERIOD", "5")),
    trend_slope_filter=os.getenv("STRATEGY_TREND_SLOPE_FILTER", "true").lower() == "true",
    max_position_risk_pct=float(os.getenv("STRATEGY_MAX_RISK_PCT", "0.05")),
    min_position_margin=float(os.getenv("STRATEGY_MIN_MARGIN", "5")),
)
account = PaperFutures(STATE_PATH, STARTING_BALANCE, LEVERAGE, PAPER_FEE_RATE,
                       STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS)
exchange = None
trading_active = True
runtime_lock = threading.RLock()
last_signal = last_mark = last_market_update = last_market_error = None


def telegram_call(method, payload, timeout=8):
    if not TELEGRAM_TOKEN:
        return None
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
                             json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API {method} returned an error")
    return result.get("result")


def send(chat_id, text, markup=None):
    if not TELEGRAM_TOKEN or not chat_id:
        return False
    try:
        telegram_call("sendMessage", {"chat_id": chat_id, "text": text,
                                      **({"reply_markup": markup} if markup else {})})
        return True
    except Exception:
        logging.exception("Telegram send failed")
        return False


def edit(chat_id, message_id, text, markup):
    try:
        telegram_call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                           "text": text, "reply_markup": markup})
    except Exception as exc:
        logging.info("Telegram panel edit ignored: %s", exc)


def create_market_data_client():
    if not hasattr(ccxt, DATA_EXCHANGE):
        raise ValueError(f"Unknown DATA_EXCHANGE: {DATA_EXCHANGE}")
    client = getattr(ccxt, DATA_EXCHANGE)({"enableRateLimit": True, "timeout": 15000})
    client.load_markets()
    if SYMBOL not in client.markets:
        raise ValueError(f"{SYMBOL} unavailable on {DATA_EXCHANGE}")
    return client


def fetch_candles():
    bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=200)
    # Ignore the potentially unfinished last candle.
    bars = bars[:-1] if bars else []
    if len(bars) < max(80, STRATEGY_CONFIG.ema_slow + STRATEGY_CONFIG.trend_slope_period + 2):
        raise RuntimeError("Not enough closed candles to evaluate strategy")
    return bars


def dashboard_data():
    with runtime_lock:
        mark, updated, error, active, signal = last_mark, last_market_update, last_market_error, trading_active, last_signal
    prices = {SYMBOL: mark} if mark is not None else {}
    snap = account.snapshot(prices)
    if updated is None:
        market = "⚪ waiting for data"
    elif error:
        market = "🔴 market error"
    else:
        age = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
        market = f"🟢 data {age}s old"
    return {
        **snap, "position": snap["positions"][0] if snap["positions"] else None,
        "signal": signal, "price": f"{mark:.4f}" if mark is not None else "—",
        "market": market, "bot_status": "ACTIVE" if active else "PAUSED", "timeframe": TIMEFRAME,
        "ema_fast_period": STRATEGY_CONFIG.ema_fast, "ema_slow_period": STRATEGY_CONFIG.ema_slow,
        "slope_period": STRATEGY_CONFIG.trend_slope_period,
        "min_volatility_pct": STRATEGY_CONFIG.min_volatility_pct,
        "max_volatility_pct": STRATEGY_CONFIG.max_volatility_pct,
        "rsi_long": STRATEGY_CONFIG.rsi_long_threshold,
        "rsi_short": STRATEGY_CONFIG.rsi_short_threshold,
    }


def show_page(chat_id, message_id=None, page="overview", new_message=False):
    data = dashboard_data()
    text = render(page, data)
    markup = keyboard(trading_active)
    if new_message:
        send(chat_id, text, markup)
    elif message_id is not None:
        edit(chat_id, message_id, text, markup)
    return text


def process_market():
    global last_signal, last_mark, last_market_update, last_market_error
    candles = fetch_candles()
    signal = signal_from_candles(candles, STRATEGY_CONFIG)
    ticker = exchange.fetch_ticker(SYMBOL)
    mark = float(ticker.get("last") or signal["price"])
    with runtime_lock:
        last_signal, last_mark = signal, mark
        last_market_update = datetime.now(timezone.utc)
        last_market_error = None
        active = trading_active

    closed = account.check_exit(SYMBOL, signal["high"], signal["low"], mark)
    if closed:
        send(TELEGRAM_CHAT_ID, f"📕 PAPER close {closed['reason']} · net {closed['net_pnl']:+.2f} USDT", keyboard(active))
    if active and signal["side"] and SYMBOL not in account.state["positions"]:
        snap = account.snapshot({SYMBOL: mark})
        margin = calculate_position_margin(snap["equity"], ORDER_MARGIN_USDT,
                                           STRATEGY_CONFIG.max_position_risk_pct,
                                           STRATEGY_CONFIG.min_position_margin)
        if margin > 0:
            position = account.open_position(SYMBOL, signal["side"], mark, margin)
            send(TELEGRAM_CHAT_ID, f"🧪 PAPER {position['side']} · {SYMBOL} @ {mark:.4f}\n"
                 f"Margin {margin:.2f} USDT · SL {position['stop_loss']:.4f} · TP {position['take_profit']:.4f}",
                 keyboard(active))


def handle_update(update):
    global trading_active
    message = update.get("message") or {}
    callback = update.get("callback_query")
    chat = (message.get("chat") or {}) if message else ((callback.get("message") or {}).get("chat") or {})
    chat_id = chat.get("id")
    if TELEGRAM_CHAT_ID and str(chat_id) != TELEGRAM_CHAT_ID:
        if callback:
            try:
                telegram_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "Not authorized"})
            except Exception:
                pass
        return
    if message:
        command = (message.get("text") or "").split("@", 1)[0].strip().lower()
        if command in ("/start", "/panel", "/menu", "/status"):
            show_page(chat_id, page="overview", new_message=True)
        elif command == "/performance":
            show_page(chat_id, page="performance", new_message=True)
        elif command == "/strategy":
            show_page(chat_id, page="strategy", new_message=True)
        elif command == "/pause":
            with runtime_lock:
                trading_active = False
            show_page(chat_id, page="overview", new_message=True)
        elif command == "/resume":
            with runtime_lock:
                trading_active = True
            show_page(chat_id, page="overview", new_message=True)
    elif callback:
        try:
            telegram_call("answerCallbackQuery", {"callback_query_id": callback.get("id")}, timeout=5)
        except Exception:
            pass
        msg = callback.get("message") or {}
        action = callback.get("data", "")
        if action.startswith("page:"):
            show_page(chat_id, msg.get("message_id"), action.split(":", 1)[1])
        elif action == "control:pause":
            with runtime_lock:
                trading_active = False
            show_page(chat_id, msg.get("message_id"), "overview")
        elif action == "control:resume":
            with runtime_lock:
                trading_active = True
            show_page(chat_id, msg.get("message_id"), "overview")


def telegram_worker():
    if not TELEGRAM_TOKEN:
        logging.warning("TELEGRAM_BOT_TOKEN unset; Telegram disabled")
        return
    offset = 0
    while True:
        try:
            response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                                   params={"offset": offset, "timeout": 20}, timeout=25)
            response.raise_for_status()
            for update in response.json().get("result", []):
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception:
                    logging.exception("Telegram update failed")
        except Exception:
            logging.exception("Telegram polling failed")
            time.sleep(3)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Paper simulator is running; live orders disabled.")

    def log_message(self, fmt, *args):
        return


def main():
    global exchange, last_market_error
    port = int(os.getenv("PORT", "10000"))
    threading.Thread(target=lambda: ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=telegram_worker, daemon=True).start()
    while True:
        try:
            exchange = create_market_data_client()
            break
        except Exception as exc:
            with runtime_lock:
                last_market_error = str(exc)
            logging.exception("Market data client initialization failed")
            time.sleep(30)
    send(TELEGRAM_CHAT_ID, "🧪 SOL simulator running in PAPER mode. Open /panel for overview.", keyboard())
    while True:
        try:
            process_market()
        except Exception as exc:
            with runtime_lock:
                last_market_error = str(exc)
            logging.exception("Market cycle failed")
        time.sleep(max(SCAN_SECONDS, 5))


if __name__ == "__main__":
    main()
