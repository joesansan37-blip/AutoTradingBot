"""Paper-only Solana (SOL) perpetual-futures strategy runner.

Uses public spot-market candles as a price feed and a local paper ledger. It does not
connect a wallet, read exchange credentials, or submit real orders. SOL futures are
simulated from SOL/USDT prices; Solana itself is not a futures venue.
"""

import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ccxt
import requests

from paper_futures import PaperFutures
from strategies import STRATEGIES, signal_from_candles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
if os.getenv("EXECUTION_MODE", "paper").strip().lower() != "paper":
    raise RuntimeError("Only EXECUTION_MODE=paper is supported; live trading is not implemented.")

SYMBOL = os.getenv("TRADING_SYMBOL", "SOL/USDT").strip()
TIMEFRAME = os.getenv("TIMEFRAME", "15m").strip()
DATA_EXCHANGE = os.getenv("DATA_EXCHANGE", "kraken").strip().lower()
STRATEGY = os.getenv("STRATEGY", "ema_trend").strip().lower()
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
if STRATEGY not in STRATEGIES:
    raise ValueError(f"STRATEGY must be one of: {', '.join(STRATEGIES)}")
if not 1 <= LEVERAGE <= 10:
    raise ValueError("Set LEVERAGE between 1 and 10")
if min(ORDER_MARGIN_USDT, STARTING_BALANCE, MAX_DAILY_LOSS) <= 0 or SCAN_SECONDS < 1:
    raise ValueError("Balance, margin, daily loss limit and scan interval must be positive")
if not 0 < PAPER_FEE_RATE < 0.01:
    raise ValueError("PAPER_FEE_RATE must be between 0 and 0.01")

account = PaperFutures(STATE_PATH, STARTING_BALANCE, LEVERAGE, PAPER_FEE_RATE,
                       STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS)
exchange = None
trading_active = True


def telegram_send(text, markup=None, chat_id=None):
    if not TELEGRAM_TOKEN:
        logging.info("Telegram not configured; message: %s", text)
        return False
    target = str(chat_id or TELEGRAM_CHAT_ID)
    if not target:
        logging.warning("Telegram message not sent: TELEGRAM_CHAT_ID is unset")
        return False
    payload = {"chat_id": target, "text": text}
    if markup:
        payload["reply_markup"] = markup
    try:
        response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                 json=payload, timeout=8)
        response.raise_for_status()
        return response.json().get("ok", False)
    except Exception:
        logging.exception("Telegram send failed")
        return False


def telegram_edit(chat_id, message_id, text, markup=None):
    if not TELEGRAM_TOKEN:
        return False
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    try:
        response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                                 json=payload, timeout=8)
        response.raise_for_status()
        return response.json().get("ok", False)
    except Exception:
        logging.exception("Telegram message edit failed")
        return False


def menu():
    return {"inline_keyboard": [
        [{"text": "💰 Balance paper", "callback_data": "balance"},
         {"text": "📈 Posiciones", "callback_data": "positions"}],
        [{"text": "📡 Radar SOL", "callback_data": "radar"},
         {"text": "⏸ Pausar", "callback_data": "pause"}],
        [{"text": "▶ Reanudar", "callback_data": "resume"},
         {"text": "🚨 Cerrar paper", "callback_data": "panic"}],
    ]}


def create_market_data_client():
    # Public-only CCXT client: no API keys are read or passed to it.
    if not hasattr(ccxt, DATA_EXCHANGE):
        raise ValueError(f"Unknown DATA_EXCHANGE: {DATA_EXCHANGE}")
    client = getattr(ccxt, DATA_EXCHANGE)({"enableRateLimit": True, "timeout": 15000})
    client.load_markets()
    if SYMBOL not in client.markets:
        raise ValueError(f"{SYMBOL} is not available on public data venue {DATA_EXCHANGE}")
    return client


def fetch_candles():
    candles = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
    if not candles or len(candles) < 60:
        raise RuntimeError("Not enough candles to calculate the strategy")
    return candles


def make_signal(candles):
    return signal_from_candles(candles, STRATEGY)


def process_market():
    candles = fetch_candles()
    signal = make_signal(candles)
    ticker = exchange.fetch_ticker(SYMBOL)
    mark = float(ticker.get("last") or signal["price"])
    closed = account.check_exit(SYMBOL, signal["high"], signal["low"], mark)
    if closed:
        telegram_send(f"📕 Cierre paper {closed['reason']} {SYMBOL} a {closed['exit']:.4f}; "
                      f"PnL neto estimado: {closed['net_pnl']:.2f} USDT", menu())
    if trading_active and signal["side"] and SYMBOL not in account.state["positions"]:
        try:
            position = account.open_position(SYMBOL, signal["side"], mark, ORDER_MARGIN_USDT)
            telegram_send(f"🧪 APERTURA PAPER {position['side']} {SYMBOL} | estrategia: {STRATEGY}\n"
                          f"Entrada: {mark:.4f} | margen: {ORDER_MARGIN_USDT:.2f} USDT | "
                          f"nocional: {position['notional']:.2f} USDT ({LEVERAGE}x)\n"
                          f"SL: {position['stop_loss']:.4f} | TP: {position['take_profit']:.4f}\n"
                          "Solo simulación; no se envió ninguna orden real.", menu())
        except ValueError as exc:
            logging.info("Paper position not opened: %s", exc)
    return signal, mark


def snapshot_text(mark=None):
    prices = {SYMBOL: mark} if mark else {}
    snap = account.snapshot(prices)
    return ("🧪 CUENTA PAPER (sin dinero real)\n"
            f"Estrategia: {STRATEGY}\n"
            f"Equity: {snap['equity']:.2f} USDT | Disponible: {snap['available']:.2f} USDT\n"
            f"PnL flotante: {snap['unrealized_pnl']:.2f} USDT | "
            f"PnL realizado hoy: {snap['daily_realized']:.2f} USDT\n"
            f"Operaciones cerradas: {snap['closed_trades']} | Apalancamiento simulado: {LEVERAGE}x")


def positions_text():
    positions = account.snapshot()["positions"]
    if not positions:
        return "Sin posiciones paper abiertas."
    return "\n".join(f"{p['side']} {p['symbol']} entrada {p['entry']:.4f}, "
                     f"qty {p['quantity']:.6f}, SL {p['stop_loss']:.4f}, TP {p['take_profit']:.4f}"
                     for p in positions)


def panic_close():
    mark = exchange.fetch_ticker(SYMBOL).get("last") if exchange else None
    return account.close_all({SYMBOL: float(mark)}) if mark else []


def handle_update(update):
    global trading_active
    message = update.get("message") or {}
    callback = update.get("callback_query")
    source_message = callback.get("message", {}) if callback else message
    sender = (source_message.get("chat") or {}).get("id")
    if TELEGRAM_CHAT_ID and str(sender) != TELEGRAM_CHAT_ID:
        logging.warning("Ignoring Telegram update from unauthorized chat")
        return

    if message:
        text = (message.get("text") or "").strip().lower()
        if text.startswith(("/start", "/menu", "/help")):
            telegram_send(f"🧪 SOL futures PAPER only. Strategy: {STRATEGY}. No live orders.\n"
                          "/balance, /positions, /radar, /pause, /resume, /panic", menu(), sender)
        elif text.startswith(("/balance", "/saldo")):
            telegram_send(snapshot_text(), menu(), sender)
        elif text.startswith("/positions"):
            telegram_send(positions_text(), menu(), sender)
        elif text.startswith("/pause"):
            trading_active = False
            telegram_send("⏸ Simulación pausada; SL/TP siguen monitorizándose.", menu(), sender)
        elif text.startswith("/resume"):
            trading_active = True
            telegram_send("▶ Simulación reanudada.", menu(), sender)
        elif text.startswith("/panic"):
            closed = panic_close()
            telegram_send(f"Cierre paper completado: {len(closed)} posición(es). No hubo órdenes reales.", menu(), sender)
        elif text.startswith("/radar"):
            try:
                sig = make_signal(fetch_candles())
                telegram_send(f"Radar {SYMBOL} [{STRATEGY}]: {sig['price']:.4f} USDT, "
                              f"RSI {sig['rsi']:.1f}, señal: {sig['side'] or 'sin señal'} (paper)", menu(), sender)
            except Exception as exc:
                telegram_send(f"No se pudo obtener el radar: {exc}", menu(), sender)
        return

    if not callback:
        return
    cq = callback
    if TELEGRAM_TOKEN:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": cq.get("id")}, timeout=5).raise_for_status()
        except Exception:
            logging.exception("Could not acknowledge Telegram button")
    data = cq.get("data")
    if data == "balance":
        text_out = snapshot_text()
    elif data == "positions":
        text_out = positions_text()
    elif data == "radar":
        try:
            sig = make_signal(fetch_candles())
            text_out = f"{SYMBOL} [{STRATEGY}]: {sig['price']:.4f} USDT | RSI {sig['rsi']:.1f} | " \
                       f"{sig['side'] or 'sin señal'} (paper)"
        except Exception as exc:
            text_out = f"Radar no disponible: {exc}"
    elif data == "pause":
        trading_active = False
        text_out = "Simulación pausada; SL/TP siguen monitorizándose."
    elif data == "resume":
        trading_active = True
        text_out = "Simulación reanudada."
    elif data == "panic":
        closed = panic_close()
        text_out = f"Cierre paper: {len(closed)} posición(es). No hubo órdenes reales."
    else:
        text_out = "Acción no reconocida."
    telegram_edit(sender, source_message.get("message_id"), text_out, menu())


def telegram_worker():
    if not TELEGRAM_TOKEN:
        logging.warning("TELEGRAM_BOT_TOKEN unset; Telegram controller disabled")
        return
    offset = 0
    while True:
        try:
            response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                                    params={"offset": offset, "timeout": 20}, timeout=25)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logging.error("Telegram polling returned an error: %s", payload)
                time.sleep(3)
                continue
            for item in payload.get("result", []):
                offset = item["update_id"] + 1
                try:
                    handle_update(item)
                except Exception:
                    logging.exception("Failed to process Telegram update")
        except Exception:
            logging.exception("Telegram polling failed")
            time.sleep(3)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"SOL futures paper simulator is running; live orders disabled.")

    def log_message(self, fmt, *args):
        return


def main():
    global exchange
    port = int(os.getenv("PORT", "10000"))
    threading.Thread(target=lambda: ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(),
                     daemon=True).start()
    threading.Thread(target=telegram_worker, daemon=True).start()
    while True:
        try:
            exchange = create_market_data_client()
            break
        except Exception:
            logging.exception("Unable to initialize public market-data client; retrying in 30s")
            time.sleep(30)
    telegram_send(f"🧪 Simulador PAPER iniciado para {SYMBOL}. Estrategia: {STRATEGY}. "
                  "Solo usa datos públicos; no se envían órdenes reales. /start para controles.", menu())
    while True:
        try:
            signal, mark = process_market()
            logging.info("%s mark=%.4f strategy=%s signal=%s active=%s",
                         SYMBOL, mark, STRATEGY, signal["side"], trading_active)
            time.sleep(SCAN_SECONDS)
        except Exception:
            logging.exception("Paper strategy cycle failed")
            time.sleep(max(SCAN_SECONDS, 5))


if __name__ == "__main__":
    main()
