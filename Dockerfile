"""Paper-only SOL/USDT simulator with production-friendly startup and Telegram views."""

import logging
import os
import random
import signal
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ccxt
import requests

from app_config import configure_logging, load_config
from paper_futures import PaperFutures
from strategy import StrategyConfig, calculate_position_margin, signal_from_candles
from telegram_dashboard import keyboard, render

CONFIG = load_config()
configure_logging(CONFIG.log_level, CONFIG.log_format)
LOG = logging.getLogger("autotradingbot")

SYMBOL = CONFIG.symbol
TIMEFRAME = CONFIG.timeframe
DATA_EXCHANGE = CONFIG.data_exchange
LEVERAGE = CONFIG.leverage
ORDER_MARGIN_USDT = CONFIG.order_margin_usdt
STARTING_BALANCE = CONFIG.starting_balance_usdt
STOP_LOSS_PCT = CONFIG.stop_loss_pct
TAKE_PROFIT_PCT = CONFIG.take_profit_pct
PAPER_FEE_RATE = CONFIG.paper_fee_rate
MAX_DAILY_LOSS = CONFIG.max_daily_loss_usdt
SCAN_SECONDS = CONFIG.scan_seconds
STATE_PATH = CONFIG.state_file
TELEGRAM_TOKEN = CONFIG.telegram_token
TELEGRAM_CHAT_ID = CONFIG.telegram_chat_id

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
    trend_slope_filter=os.getenv("STRATEGY_TREND_SLOPE_FILTER", "true").strip().lower() in ("true", "1", "yes"),
    max_position_risk_pct=float(os.getenv("STRATEGY_MAX_RISK_PCT", "0.05")),
    min_position_margin=float(os.getenv("STRATEGY_MIN_MARGIN", "5")),
)

if not 0 <= STRATEGY_CONFIG.min_volatility_pct <= STRATEGY_CONFIG.max_volatility_pct:
    raise ValueError("Strategy volatility bounds must satisfy 0 <= min <= max")

account = PaperFutures(
    STATE_PATH,
    STARTING_BALANCE,
    LEVERAGE,
    PAPER_FEE_RATE,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    MAX_DAILY_LOSS,
)
exchange = None
trading_active = True
runtime_lock = threading.RLock()
stop_event = threading.Event()
last_signal = None
last_mark = None
last_market_update = None
last_market_error = None


def telegram_call(method, payload, timeout=8):
    if not TELEGRAM_TOKEN:
        return None
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API {method} returned an error")
    return result.get("result")


def send(chat_id, text, markup=None):
    if not TELEGRAM_TOKEN or not chat_id:
        return False
    try:
        telegram_call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, **({"reply_markup": markup} if markup else {})},
        )
        return True
    except Exception:
        LOG.warning("Telegram send failed", exc_info=True)
        return False


def edit(chat_id, message_id, text, markup):
    try:
        telegram_call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup},
        )
    except Exception as exc:
        LOG.debug("Telegram panel edit ignored: %s", exc)


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
    bars = bars[:-1] if bars else []
    if len(bars) < max(80, STRATEGY_CONFIG.ema_slow + STRATEGY_CONFIG.trend_slope_period + 2):
        raise RuntimeError("Not enough closed candles to evaluate strategy")
    return bars


def dashboard_data():
    with runtime_lock:
        mark = last_mark
        updated = last_market_update
        error = last_market_error
        active = trading_active
        sig = last_signal
    snap = account.snapshot({SYMBOL: mark} if mark is not None else {})
    if updated is None:
        market = "⚪ esperando datos"
    elif error:
        market = "🔴 error de mercado"
    else:
        age = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
        market = f"🟢 datos {age}s"
    return {
        **snap,
        "position": snap["positions"][0] if snap["positions"] else None,
        "signal": sig,
        "price": f"{mark:.4f}" if mark is not None else "—",
        "market": market,
        "bot_status": "ACTIVE" if active else "PAUSED",
        "timeframe": TIMEFRAME,
        "ema_fast_period": STRATEGY_CONFIG.ema_fast,
        "ema_slow_period": STRATEGY_CONFIG.ema_slow,
        "slope_period": STRATEGY_CONFIG.trend_slope_period,
        "min_volatility_pct": STRATEGY_CONFIG.min_volatility_pct,
        "max_volatility_pct": STRATEGY_CONFIG.max_volatility_pct,
        "rsi_long": STRATEGY_CONFIG.rsi_long_threshold,
        "rsi_short": STRATEGY_CONFIG.rsi_short_threshold,
    }


def show_page(chat_id, message_id=None, page="overview", new_message=False):
    text = render(page, dashboard_data())
    markup = keyboard(trading_active)
    if new_message:
        send(chat_id, text, markup)
    elif message_id is not None:
        edit(chat_id, message_id, text, markup)


def process_market():
    global last_signal, last_mark, last_market_update, last_market_error
    bars = fetch_candles()
    sig = signal_from_candles(bars, STRATEGY_CONFIG)
    ticker = exchange.fetch_ticker(SYMBOL)
    mark = float(ticker.get("last") or sig["price"])
    with runtime_lock:
        last_signal = sig
        last_mark = mark
        last_market_update = datetime.now(timezone.utc)
        last_market_error = None

    closed = account.check_exit(SYMBOL, sig["high"], sig["low"], mark)
    if closed:
        send(
            TELEGRAM_CHAT_ID,
            "📕 PAPER close %s · net %+.2f USDT" % (closed["reason"], closed["net_pnl"]),
            keyboard(trading_active),
        )

    if trading_active and sig["side"] and SYMBOL not in account.state["positions"]:
        snapshot = account.snapshot({SYMBOL: mark})
        margin = calculate_position_margin(
            snapshot["equity"],
            ORDER_MARGIN_USDT,
            STRATEGY_CONFIG.max_position_risk_pct,
            STRATEGY_CONFIG.min_position_margin,
        )
        if margin > 0:
            position = account.open_position(SYMBOL, sig["side"], mark, margin)
            send(
                TELEGRAM_CHAT_ID,
                "🧪 PAPER %s · %s @ %.4f\nMargin %.2f USDT · SL %.4f · TP %.4f"
                % (position["side"], SYMBOL, mark, margin, position["stop_loss"], position["take_profit"]),
                keyboard(trading_active),
            )
    return sig, mark


def handle_update(update):
    global trading_active
    message = update.get("message") or {}
    callback = update.get("callback_query")
    chat = (message.get("chat") or {}) if message else ((callback.get("message") or {}).get("chat") or {})
    chat_id = chat.get("id")
    if TELEGRAM_CHAT_ID and str(chat_id) != TELEGRAM_CHAT_ID:
        if callback:
            try:
                telegram_call("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": "No autorizado"})
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
        elif action in ("control:pause", "control:resume"):
            with runtime_lock:
                trading_active = action == "control:resume"
            show_page(chat_id, msg.get("message_id"), "overview")


def telegram_worker():
    if not TELEGRAM_TOKEN:
        LOG.info("Telegram disabled: credentials not configured")
        return
    offset = 0
    retry_delay = 1
    while not stop_event.is_set():
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError("Telegram polling returned ok=false")
            for update in payload.get("result", []):
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception:
                    LOG.exception("Unable to process Telegram update")
            retry_delay = 1
        except Exception:
            LOG.warning("Telegram polling temporarily failed; retrying", exc_info=True)
            stop_event.wait(retry_delay + random.random())
            retry_delay = min(retry_delay * 2, 60)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/healthz", "/readyz"):
            self.send_error(404)
            return
        ready = exchange is not None and last_market_update is not None and last_market_error is None
        if self.path == "/readyz" and not ready:
            self.send_response(503)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ready\n" if ready else b"starting\n")

    def log_message(self, fmt, *args):  # noqa: ARG002
        return


def handle_shutdown(signum, _frame):
    LOG.info("Shutdown signal received", extra={"signal": signum})
    stop_event.set()


def start_health_server(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    return server


def main():
    global exchange
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    port = int(os.getenv("PORT", "10000"))
    health_server = start_health_server(port)

    telegram_thread = threading.Thread(target=telegram_worker, name="telegram-poller", daemon=True)
    telegram_thread.start()

    retry_delay = 2
    while not stop_event.is_set():
        try:
            exchange = create_market_data_client()
            LOG.info("Public market-data client ready", extra={"exchange": DATA_EXCHANGE, "symbol": SYMBOL})
            break
        except Exception as exc:
            global last_market_error
            last_market_error = str(exc)
            LOG.warning("Market-data initialization failed; retrying in %ss", retry_delay, exc_info=True)
            stop_event.wait(retry_delay + random.random())
            retry_delay = min(retry_delay * 2, 60)

    if stop_event.is_set():
        health_server.shutdown()
        health_server.server_close()
        return

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        send(TELEGRAM_CHAT_ID, "🧪 SOL simulator running in PAPER mode. Open /panel for overview.")

    LOG.info("Paper simulator started", extra={"symbol": SYMBOL, "timeframe": TIMEFRAME, "exchange": DATA_EXCHANGE})
    while not stop_event.is_set():
        started = time.monotonic()
        try:
            process_market()
            LOG.debug("Market cycle complete", extra={"signal": last_signal.get("side") if last_signal else None})
            sleep_for = SCAN_SECONDS
        except Exception as exc:
            last_market_error = str(exc)
            LOG.exception("Market cycle failed")
            sleep_for = max(SCAN_SECONDS, 10)
        stop_event.wait(max(0, sleep_for - (time.monotonic() - started)))

    health_server.shutdown()
    health_server.server_close()
    LOG.info("Paper simulator stopped cleanly")


if __name__ == "__main__":
    main()
