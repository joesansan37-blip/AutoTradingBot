"""Paper-only SOL/USDT strategy runner with a Telegram status dashboard.

Market data is public and all positions are stored in a local simulated ledger.
No wallet, exchange credentials, or live-order endpoints are used.
"""

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
    max_position_risk_pct=float(os.getenv("STRATEGY_MAX_RISK_PCT", "0.05")),
    min_position_margin=float(os.getenv("STRATEGY_MIN_MARGIN", "5.0")),
)

account = PaperFutures(STATE_PATH, STARTING_BALANCE, LEVERAGE, PAPER_FEE_RATE,
                       STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS)
exchange = None
trading_active = True
runtime_lock = threading.RLock()
last_signal = None
last_mark = None
last_market_update = None
last_market_error = None


def telegram_api(method, payload, timeout=8):
    if not TELEGRAM_TOKEN:
        return None
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
                             json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed")
    return result.get("result")


def telegram_send(text, markup=None, chat_id=None):
    target = str(chat_id or TELEGRAM_CHAT_ID)
    if not TELEGRAM_TOKEN or not target:
        logging.info("Telegram message not sent (token/chat not configured): %s", text)
        return False
    try:
        telegram_api("sendMessage", {"chat_id": target, "text": text,
                                     **({"reply_markup": markup} if markup else {})})
        return True
    except Exception:
        logging.exception("Telegram send failed")
        return False


def telegram_edit(chat_id, message_id, text, markup=None):
    try:
        telegram_api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                          "text": text,
                                          **({"reply_markup": markup} if markup else {})})
        return True
    except Exception as exc:
        # Telegram returns an error when the user refreshes an unchanged panel.
        logging.info("Telegram panel edit skipped/failed: %s", exc)
        return False


def menu():
    return {"inline_keyboard": [
        [{"text": "📊 Panel", "callback_data": "panel"},
         {"text": "🧭 Estrategia", "callback_data": "strategy"}],
        [{"text": "💰 Balance", "callback_data": "balance"},
         {"text": "📈 Posiciones", "callback_data": "positions"}],
        [{"text": "📡 Radar", "callback_data": "radar"},
         {"text": "🧾 Operaciones", "callback_data": "trades"}],
        [{"text": "⏸ Pausar", "callback_data": "pause"},
         {"text": "▶ Reanudar", "callback_data": "resume"}],
        [{"text": "🚨 Cerrar paper", "callback_data": "panic"}],
    ]}


def create_market_data_client():
    if not hasattr(ccxt, DATA_EXCHANGE):
        raise ValueError(f"Unknown DATA_EXCHANGE: {DATA_EXCHANGE}")
    client = getattr(ccxt, DATA_EXCHANGE)({"enableRateLimit": True, "timeout": 15000})
    client.load_markets()
    if SYMBOL not in client.markets:
        raise ValueError(f"{SYMBOL} is unavailable on public data venue {DATA_EXCHANGE}")
    return client


def fetch_candles():
    candles = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=200)
    if not candles or len(candles) < max(80, STRATEGY_CONFIG.ema_slow + 10):
        raise RuntimeError("Not enough candles to evaluate strategy")
    # CCXT's final OHLCV candle can still be forming. Exclude it from signals/exits.
    return candles[:-1]


def get_signal(candles=None):
    candles = candles if candles is not None else fetch_candles()
    return signal_from_candles(candles, STRATEGY_CONFIG)


def process_market():
    global last_signal, last_mark, last_market_update, last_market_error
    candles = fetch_candles()
    signal = get_signal(candles)
    ticker = exchange.fetch_ticker(SYMBOL)
    mark = float(ticker.get("last") or signal["price"])
    with runtime_lock:
        last_signal = signal
        last_mark = mark
        last_market_update = datetime.now(timezone.utc)
        last_market_error = None

    closed = account.check_exit(SYMBOL, signal["high"], signal["low"], mark)
    if closed:
        telegram_send(f"📕 Cierre PAPER {closed['reason']} {SYMBOL} a {closed['exit']:.4f}\n"
                      f"PnL neto estimado: {closed['net_pnl']:.2f} USDT", menu())

    with runtime_lock:
        active = trading_active
    if active and signal["side"] and SYMBOL not in account.state["positions"]:
        try:
            snapshot = account.snapshot({SYMBOL: mark})
            margin = calculate_position_margin(
                snapshot["equity"], ORDER_MARGIN_USDT,
                risk_pct=STRATEGY_CONFIG.max_position_risk_pct,
                min_margin=STRATEGY_CONFIG.min_position_margin,
            )
            if margin > 0:
                position = account.open_position(SYMBOL, signal["side"], mark, margin)
                telegram_send(
                    f"🧪 Apertura PAPER {position['side']} {SYMBOL}\n"
                    f"Entrada: {mark:.4f} | Margen: {margin:.2f} USDT | "
                    f"Notional simulado: {position['notional']:.2f} USDT ({LEVERAGE}x)\n"
                    f"SL: {position['stop_loss']:.4f} | TP: {position['take_profit']:.4f}\n"
                    "Simulación únicamente; no se envió ninguna orden real.", menu())
        except ValueError as exc:
            logging.info("Paper position not opened: %s", exc)
    return signal, mark


def status_text():
    with runtime_lock:
        mark, updated, error, active, sig = last_mark, last_market_update, last_market_error, trading_active, last_signal
    prices = {SYMBOL: mark} if mark is not None else {}
    snap = account.snapshot(prices)
    market_status = "sin datos todavía" if updated is None else f"actualizado {updated.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    if error:
        market_status = f"error de datos: {error[:180]}"
    position = snap["positions"]
    pos_text = "sin posición abierta" if not position else f"{position[0]['side']} @ {position[0]['entry']:.4f}"
    signal_text = sig["side"] if sig and sig["side"] else "sin señal"
    return (
        "📊 PANEL DE ESTADO — PAPER\n"
        f"Bot: {'▶ activo' if active else '⏸ pausado'} | Mercado: {market_status}\n"
        f"Par: {SYMBOL} · marco: {TIMEFRAME} · fuente: {DATA_EXCHANGE}\n"
        f"Precio: {mark:.4f} USDT\n" if mark is not None else
        "📊 PANEL DE ESTADO — PAPER\n"
        f"Bot: {'▶ activo' if active else '⏸ pausado'} | Mercado: {market_status}\n"
        f"Par: {SYMBOL} · marco: {TIMEFRAME} · fuente: {DATA_EXCHANGE}\nPrecio: no disponible\n"
    ) + (
        f"Señal reciente: {signal_text} | RSI: {sig['rsi']:.1f}\n" if sig else "Señal reciente: no disponible\n"
    ) + (
        f"Posición: {pos_text}\nEquity: {snap['equity']:.2f} USDT | Disponible: {snap['available']:.2f} USDT\n"
        f"PnL flotante: {snap['unrealized_pnl']:.2f} | PnL realizado hoy: {snap['daily_realized']:.2f} USDT\n"
        f"Cierres registrados: {snap['closed_trades']} | Apalancamiento simulado: {LEVERAGE}x\n"
        "⚠️ Solo simulación; no hay órdenes reales."
    )


def strategy_text():
    with runtime_lock:
        sig = last_signal
        active = trading_active
    sig_line = "Todavía no hay lectura de mercado." if sig is None else (
        f"Precio de vela cerrada: {sig['price']:.4f} USDT\n"
        f"Dirección: {sig['side'] or 'sin señal'} | RSI({STRATEGY_CONFIG.rsi_period}): {sig['rsi']:.1f}\n"
        f"EMA({STRATEGY_CONFIG.ema_fast}): {sig['ema_fast']:.4f} | "
        f"EMA({STRATEGY_CONFIG.ema_slow}): {sig['ema_slow']:.4f}\n"
        f"ATR: {sig['atr']:.4f} ({sig['volatility_pct'] * 100:.3f}% del precio)"
    )
    return (
        "🧭 CONFIGURACIÓN DE ESTRATEGIA — PAPER\n"
        f"Estado: {'activa' if active else 'pausada'}\n"
        f"Regla: EMA rápida/lenta alineadas + filtro RSI + volatilidad mínima.\n"
        f"EMA: {STRATEGY_CONFIG.ema_fast}/{STRATEGY_CONFIG.ema_slow} | "
        f"RSI LONG ≥ {STRATEGY_CONFIG.rsi_long_threshold:g}, SHORT ≤ {STRATEGY_CONFIG.rsi_short_threshold:g}\n"
        f"ATR mínimo: {STRATEGY_CONFIG.min_volatility_pct * 100:.3f}% | "
        f"SL/TP simulados: {STOP_LOSS_PCT:g}%/{TAKE_PROFIT_PCT:g}%\n"
        f"Margen base máx.: {ORDER_MARGIN_USDT:.2f} USDT | Riesgo-sizing cap: "
        f"{STRATEGY_CONFIG.max_position_risk_pct * 100:.1f}% equity\n\n{sig_line}\n"
        "Los valores son configuración/simulación educativa, no asesoramiento financiero."
    )


def positions_text():
    prices = {SYMBOL: last_mark} if last_mark is not None else {}
    positions = account.snapshot(prices)["positions"]
    if not positions:
        return "📈 No hay posiciones PAPER abiertas."
    return "📈 POSICIONES PAPER\n" + "\n\n".join(
        f"{p['side']} {p['symbol']}\nEntrada: {p['entry']:.4f} | Marca: {p['mark']:.4f}\n"
        f"Cantidad: {p['quantity']:.6f} | Margen: {p['margin']:.2f} USDT\n"
        f"PnL flotante: {p['unrealized_pnl']:.2f} USDT\nSL: {p['stop_loss']:.4f} | TP: {p['take_profit']:.4f}"
        for p in positions)


def trades_text():
    trades = account.state.get("closed_trades", [])[-5:]
    if not trades:
        return "🧾 Aún no hay operaciones PAPER cerradas."
    return "🧾 ÚLTIMOS CIERRES PAPER\n" + "\n\n".join(
        f"{t['side']} {t['symbol']} · {t['reason']}\n"
        f"Entrada {t['entry']:.4f} → salida {t['exit']:.4f}\n"
        f"PnL neto: {t['net_pnl']:.2f} USDT · {t['closed_at']}" for t in reversed(trades))


def radar_text():
    sig = get_signal()
    return (f"📡 RADAR {SYMBOL} ({TIMEFRAME})\nPrecio vela cerrada: {sig['price']:.4f} USDT\n"
            f"Señal: {sig['side'] or 'sin señal'} | RSI: {sig['rsi']:.1f}\n"
            f"EMA{STRATEGY_CONFIG.ema_fast}: {sig['ema_fast']:.4f} | EMA{STRATEGY_CONFIG.ema_slow}: {sig['ema_slow']:.4f}\n"
            f"ATR: {sig['atr']:.4f} ({sig['volatility_pct'] * 100:.3f}%)\nSolo paper.")


def callback_text(action):
    global trading_active
    if action in ("panel", "balance"):
        return status_text()
    if action == "strategy":
        return strategy_text()
    if action == "positions":
        return positions_text()
    if action == "trades":
        return trades_text()
    if action == "radar":
        try:
            return radar_text()
        except Exception as exc:
            return f"Radar no disponible: {exc}"
    if action == "pause":
        with runtime_lock:
            trading_active = False
        return "⏸ Estrategia pausada. Las posiciones paper existentes siguen monitorizándose.\n\n" + status_text()
    if action == "resume":
        with runtime_lock:
            trading_active = True
        return "▶ Estrategia reanudada.\n\n" + status_text()
    if action == "panic":
        mark = last_mark
        if mark is None and exchange:
            mark = exchange.fetch_ticker(SYMBOL).get("last")
        closed = account.close_all({SYMBOL: float(mark)}) if mark else []
        return f"🚨 Cierre PAPER completado: {len(closed)} posición(es). No hubo órdenes reales.\n\n" + status_text()
    return "Acción no reconocida. Usa /panel para abrir el menú."


def handle_update(update):
    message = update.get("message") or {}
    callback = update.get("callback_query")
    chat = (message.get("chat") or {}) if message else ((callback.get("message") or {}).get("chat") or {})
    sender = chat.get("id")
    if TELEGRAM_CHAT_ID and str(sender) != TELEGRAM_CHAT_ID:
        logging.warning("Ignoring Telegram update from unauthorized chat")
        if callback:
            try:
                telegram_api("answerCallbackQuery", {"callback_query_id": callback.get("id"),
                                                     "text": "No autorizado"})
            except Exception:
                pass
        return

    if message:
        text = (message.get("text") or "").strip().lower().split("@", 1)[0]
        if text in ("/start", "/menu", "/panel", "/help"):
            telegram_send("🧪 Panel de control del simulador SOL/USDT. Modo PAPER: no usa fondos reales.\n"
                          "Comandos: /panel, /status, /strategy, /balance, /positions, /radar, /trades, /pause, /resume, /panic",
                          menu(), sender)
        elif text in ("/status", "/balance", "/saldo"):
            telegram_send(status_text(), menu(), sender)
        elif text == "/strategy":
            telegram_send(strategy_text(), menu(), sender)
        elif text == "/positions":
            telegram_send(positions_text(), menu(), sender)
        elif text == "/trades":
            telegram_send(trades_text(), menu(), sender)
        elif text == "/radar":
            try:
                telegram_send(radar_text(), menu(), sender)
            except Exception as exc:
                telegram_send(f"Radar no disponible: {exc}", menu(), sender)
        elif text == "/pause":
            with runtime_lock:
                global trading_active
                trading_active = False
            telegram_send("⏸ Simulación pausada; los SL/TP paper siguen monitorizándose.", menu(), sender)
        elif text == "/resume":
            with runtime_lock:
                trading_active = True
            telegram_send("▶ Simulación reanudada.", menu(), sender)
        elif text == "/panic":
            telegram_send(callback_text("panic"), menu(), sender)
    elif callback:
        try:
            telegram_api("answerCallbackQuery", {"callback_query_id": callback.get("id")}, timeout=5)
        except Exception:
            pass
        callback_chat = (callback.get("message") or {}).get("chat") or {}
        message_id = (callback.get("message") or {}).get("message_id")
        text = callback_text(callback.get("data"))
        telegram_edit(callback_chat.get("id"), message_id, text, menu())


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
    global exchange, last_market_error
    port = int(os.getenv("PORT", "10000"))
    threading.Thread(target=lambda: ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever(),
                     daemon=True).start()
    threading.Thread(target=telegram_worker, daemon=True).start()
    while True:
        try:
            exchange = create_market_data_client()
            break
        except Exception as exc:
            with runtime_lock:
                last_market_error = str(exc)
            logging.exception("Unable to initialize public market-data client; retrying in 30s")
            time.sleep(30)
    telegram_send("🧪 Simulador PAPER iniciado para SOL/USDT. Datos públicos; ninguna orden real. /panel para el dashboard.", menu())
    while True:
        try:
            signal, mark = process_market()
            logging.info("SOL mark=%.4f signal=%s active=%s", mark, signal["side"], trading_active)
            time.sleep(SCAN_SECONDS)
        except Exception as exc:
            with runtime_lock:
                last_market_error = str(exc)
            logging.exception("Paper strategy cycle failed")
            time.sleep(max(SCAN_SECONDS, 5))


if __name__ == "__main__":
    main()
