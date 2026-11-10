"""Paper-only SOL/USDT simulator with Telegram dashboard and HTTP health endpoints."""

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
SYMBOL, TIMEFRAME, DATA_EXCHANGE = CONFIG.symbol, CONFIG.timeframe, CONFIG.data_exchange
TELEGRAM_TOKEN, TELEGRAM_CHAT_ID = CONFIG.telegram_token, CONFIG.telegram_chat_id
SCAN_SECONDS = CONFIG.scan_seconds
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

account = PaperFutures(CONFIG.state_file, CONFIG.starting_balance_usdt, CONFIG.leverage,
                       CONFIG.paper_fee_rate, CONFIG.stop_loss_pct, CONFIG.take_profit_pct,
                       CONFIG.max_daily_loss_usdt)
exchange = None
trading_active = True
runtime_lock = threading.RLock()
stop_event = threading.Event()
last_signal = last_mark = last_market_update = last_market_error = None


def telegram_call(method, payload, timeout=8):
    if not TELEGRAM_TOKEN:
        return None
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=payload, timeout=timeout)
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
        LOG.warning("Telegram send failed", exc_info=True)
        return False


def edit(chat_id, message_id, text, markup):
    try:
        telegram_call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                           "text": text, "reply_markup": markup})
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
    bars = bars[:-1] if bars else []  # omit the still-forming candle
    if len(bars) < max(80, STRATEGY_CONFIG.ema_slow + STRATEGY_CONFIG.trend_slope_period + 2):
        raise RuntimeError("Not enough closed candles to evaluate strategy")
    return bars


def dashboard_data():
    with runtime_lock:
        mark, updated, error, active, sig = last_mark, last_market_update, last_market_error, trading_active, last_signal
    snap = account.snapshot({SYMBOL: mark} if mark is not None else {})
    if updated is None:
        market = "⚪ esperando datos"
    elif error:
        market = "🔴 error de mercado"
    else:
        market = f"🟢 datos {max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))}s"
    return {**snap, "position": snap["positions"][0] if snap["positions"] else None,
            "signal": sig, "price": f"{mark:.4f}" if mark is not None else "—", "market": market,
            "bot_status": "ACTIVE" if active else "PAUSED", "timeframe": TIMEFRAME,
            "ema_fast_period": STRATEGY_CONFIG.ema_fast, "ema_slow_period": STRATEGY_CONFIG.ema_slow,
            "slope_period": STRATEGY_CONFIG.trend_slope_period,
            "min_volatility_pct": STRATEGY_CONFIG.min_volatility_pct,
            "max_volatility_pct": STRATEGY_CONFIG.max_volatility_pct,
            "rsi_long": STRATEGY_CONFIG.rsi_long_threshold, "rsi_short": STRATEGY_CONFIG.rsi_short_threshold}


def show_page(chat_id, message_id=None, page="overview", new_message=False):
    text = render(page, dashboard_data())
    markup = keyboard(trading_active)
    if new_message:
        send(chat_id, text, markup)
    elif message_id is not None:
        edit(chat_id, message_id, text, markup)


def process_market():
    global last_signal, last_mark, last_market_update, last_market_error
    sig = signal_from_candles(fetch_candles(), STRATEGY_CONFIG)
    ticker = exchange.fetch_ticker(SYMBOL)
    mark = float(ticker.get("last") or sig["price"])
    with runtime_lock:
        last_signal, last_mark = sig, mark
        last_market_update, last_market_error = datetime.now(timezone.utc), None
        active = trading_active
    closed = account.check_exit(SYMBOL, sig["high"], sig["low"], mark)
    if closed:
        send(TELEGRAM_CHAT_ID, f"📕 PAPER close {closed['reason']} · net {closed['net_pnl']:+.2f} USDT", keyboard(active))
    if active and sig["side"] and SYMBOL not in account.state["positions"]:
        snap = account.snapshot({SYMBOL: mark})
        margin = calculate_position_margin(snap["equity"], CONFIG.order_margin_usdt,
                                           STRATEGY_CONFIG.max_position_risk_pct,
                                           STRATEGY_CONFIG.min_position_margin)
        if margin > 0:
            pos = account.open_position(SYMBOL, sig["side"], mark, margin)
            send(TELEGRAM_CHAT_ID, f"🧪 PAPER {pos['side']} · {SYMBOL} @ {mark:.4f}\n"
                 f"Margin {margin:.2f} USDT · SL {pos['stop_loss']:.4f} · TP {pos['take_profit']:.4f}", keyboard(active))
    return sig, mark


def handle_update(update):
    global trading_active
    message, callback = update.get("message") or {}, update.get("callback_query")
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
        pages = {"/start": "overview", "/panel": "overview", "/menu": "overview", "/status": "overview",
                 "/performance": "performance", "/strategy": "strategy"}
        if command in pages:
            show_page(chat_id, page=pages[command], new_message=True)
        elif command in ("/pause", "/resume"):
            with runtime_lock:
                trading_active = command == "/resume"
            show_page(chat_id, page="overview", new_message=True)
    elif callback:
        try:
            telegram_call("answerCallbackQuery", {"callback_query_id": callback.get("id")}, timeout=5)
        except Exception:
            pass
        msg, action = callback.get("message") or {}, callback.get("data", "")
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
    offset, delay = 0, 1
    while not stop_event.is_set():
        try:
            response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                                    params={"offset": offset, "timeout": 20}, timeout=25)
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
            delay = 1
        except Exception:
            LOG.warning("Telegram polling temporarily failed; retrying", exc_info=True)
            stop_event.wait(delay + random.random())
            delay = min(delay * 2, 60)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/healthz", "/readyz"):
            self.send_error(404)
            return
        if self.path == "/readyz" and last_market_update is None:
            self.send_response(503)
            body = b"starting\n"
        else:
            self.send_response(200)
            body = b"ok\n" if last_market_update is not None else b"starting\n"
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def start_health_server(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="health-server", daemon=True).start()
    return server


def _shutdown(signum, _frame):
    LOG.info("Shutdown signal received: %s", signum)
    stop_event.set()


def main():
    global exchange, last_market_error
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    port = int(os.getenv("PORT", "10000"))
    health = start_health_server(port)
    threading.Thread(target=telegram_worker, name="telegram-poller", daemon=True).start()
    delay = 2
    while not stop_event.is_set():
        try:
            exchange = create_market_data_client()
            LOG.info("Public data client initialized: %s %s", DATA_EXCHANGE, SYMBOL)
            break
        except Exception as exc:
            last_market_error = str(exc)
            LOG.warning("Market client initialization failed; retrying in %ss", delay, exc_info=True)
            stop_event.wait(delay + random.random())
            delay = min(delay * 2, 60)
    if stop_event.is_set():
        health.shutdown()
        health.server_close()
        return
    send(TELEGRAM_CHAT_ID, "🧪 Simulador PAPER iniciado. Usa /panel para ver el estado.", keyboard())
    LOG.info("Paper simulator started; live orders disabled")
    while not stop_event.is_set():
        started = time.monotonic()
        try:
            process_market()
            delay = SCAN_SECONDS
            LOG.debug("Market scan completed")
        except Exception as exc:
            last_market_error = str(exc)
            LOG.exception("Market scan failed; will retry")
            delay = min(max(SCAN_SECONDS, delay * 2), 60)
        stop_event.wait(max(0, delay - (time.monotonic() - started)))
    health.shutdown()
    health.server_close()
    LOG.info("Simulator stopped cleanly")


if __name__ == "__main__":
    main()
