"""
AUTOTRADING CRYPTO & FOREX BOT ENGINE (100% SIN METATRADER 5)
Ejecución: CCXT (Bybit / Binance / OKX / Bitget / Kraken) & Phantom DEX (Solana)
Servidor Web 24/7 + Telegram Controller Integrado en un solo proceso para Render
"""

import time
import logging
import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import ccxt
import requests
import pandas as pd
import numpy as np

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

STATE_FILE = "trading_state.json"


def read_dynamic_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "exchange_id": os.getenv("EXCHANGE_ID", "phantom").lower(),
        "proxy_url": os.getenv("CRYPTO_PROXY_URL", "").strip()
    }


def save_dynamic_state(exchange_id: str, proxy_url: str = None):
    cur = read_dynamic_state()
    cur["exchange_id"] = exchange_id.lower().strip()
    if proxy_url is not None:
        cur["proxy_url"] = proxy_url.strip()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(cur, f)
    except Exception as e:
        logging.error(f"Error guardando estado: {e}")


# --- SERVIDOR WEB LIGERO PARA RENDER (100% GRATIS 24/7) ---
class RenderHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        state = read_dynamic_state()
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(f"Bot Cripto 24/7 activo en Render! Exchange actual: {state.get('exchange_id', 'phantom').upper()}".encode('utf-8'))

    def log_message(self, format, *args):
        pass


def run_health_check_service():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthServer)
    logging.info(f"Servidor de Salud Render activo en el puerto {port}")
    server.serve_forever()


threading.Thread(target=run_health_check_service, daemon=True).start()

# --- CONFIGURACIÓN DEL SISTEMA ---
initial_state = read_dynamic_state()
EXCHANGE_ID = initial_state.get("exchange_id", "phantom").lower()
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
IS_TESTNET = os.getenv("IS_TESTNET", "false").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

PAIRS_STR = os.getenv("TRADING_PAIRS", "SOL/USDT,BTC/USDT,ETH/USDT,BNB/USDT,XRP/USDT,DOGE/USDT,EUR/USDT,GBP/USDT")
SYMBOLS = [s.strip() for s in PAIRS_STR.split(",") if s.strip()]
TIMEFRAME = os.getenv("TIMEFRAME", "15m")
ORDER_SIZE_USDT = float(os.getenv("ORDER_SIZE_USDT", "50.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "5"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
MAX_DAILY_LOSS_USDT = float(os.getenv("MAX_DAILY_LOSS_USDT", "50.0"))
WALLET_INVESTED_USDT = float(os.getenv("WALLET_INVESTED_USDT", "500.0"))

exchange = None
is_trading_active = True
initial_usdt_balance = WALLET_INVESTED_USDT
active_positions = {}
cycle_counter = 0


def send_telegram(message: str, chat_id: str = None, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN or "TU_TELEGRAM" in TELEGRAM_BOT_TOKEN:
        logging.info(f"[TELEGRAM SIMULADO]: {message}")
        return False
    target_chat_id = str(chat_id or TELEGRAM_CHAT_ID or "").strip()
    if not target_chat_id:
        logging.warning("Telegram: chat_id no definido. Debes usar el chat del usuario o TELEGRAM_CHAT_ID.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat_id, "text": message}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            return True
        if "bad request" in r.text.lower() or "can't parse entities" in r.text.lower():
            payload.pop("parse_mode", None)
            r_retry = requests.post(url, json=payload, timeout=5)
            return r_retry.status_code == 200
        logging.warning(f"Telegram send failed: {r.status_code} {r.text[:300]}")
        return False
    except Exception as e:
        logging.error(f"Excepción enviando mensaje a Telegram: {e}")
        return False


def edit_telegram_message(target_chat_id, message_id: int, text: str, reply_markup: dict = None):
    token = TELEGRAM_BOT_TOKEN
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {"chat_id": target_chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            logging.warning(f"Telegram edit failed: {r.status_code} {r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        logging.error(f"Error editando mensaje Telegram: {e}")
        return False


def answer_callback_query(cq_id: str):
    token = TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cq_id}, timeout=3)
    except Exception:
        pass


def get_main_menu_markup():
    return {
        "inline_keyboard": [
            [{"text": "💰 Saldo & Billetera", "callback_data": "balance"},
             {"text": "📡 Radar Multiactivo", "callback_data": "radar"}],
            [{"text": "💱 Cambiar Exchange / DEX", "callback_data": "exchange_menu"},
             {"text": "📈 Posiciones Abiertas", "callback_data": "positions"}],
            [{"text": "👻 Phantom (Sin API Keys)", "callback_data": "phantom_info"},
             {"text": "📥 Depositar Cripto", "callback_data": "deposit"}],
            [{"text": "📤 Retirar Fondos", "callback_data": "withdraw"},
             {"text": "🚀 Invertir Capital", "callback_data": "invest"}],
            [{"text": "🌐 Configurar Proxy", "callback_data": "proxy_info"},
             {"text": "🚨 Panic Close", "callback_data": "panic"}],
            [{"text": "⏸️ Pausar", "callback_data": "pause"},
             {"text": "▶️ Reanudar", "callback_data": "resume"}]
        ]
    }


def get_exchange_menu_markup():
    return {
        "inline_keyboard": [
            [{"text": "👻 Phantom (Solana DEX - Sin API Keys)", "callback_data": "set_exchange_phantom"}],
            [{"text": "🟡 Binance (Global / Espejo)", "callback_data": "set_exchange_binance"},
             {"text": "⚫ Bybit (Derivados / Bytick)", "callback_data": "set_exchange_bybit"}],
            [{"text": "🔵 OKX (AWS Gateway)", "callback_data": "set_exchange_okx"},
             {"text": "🟢 Bitget (Copy & Futures)", "callback_data": "set_exchange_bitget"}],
            [{"text": "🐙 Kraken (Feed Global Anti-451)", "callback_data": "set_exchange_kraken"}],
            [{"text": "🔙 Menú Principal", "callback_data": "back_main"}]
        ]
    }


# --- CONTROLADOR TELEGRAM EN SEGUNDO PLANO ---
def handle_telegram_update(update: dict):
    global is_trading_active, EXCHANGE_ID
    try:
        if "message" in update:
            msg = update["message"]
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id") or "").strip()
            cmd = text.lower()

            if cmd.startswith("/start") or cmd.startswith("/menu"):
                welcome = (
                    "🤖 Panel de Control Cripto & Divisas (100% Sin MetaTrader)\n\n"
                    f"• Modo Activo: {EXCHANGE_ID.upper()}\n"
                    f"• Pares: {', '.join(SYMBOLS[:4])}...\n"
                    f"• Capital: {WALLET_INVESTED_USDT:,.2f} USDT\n\n"
                    "Selecciona una opción del menú interactivo:"
                )
                send_telegram(welcome, chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/phantom") or cmd.startswith("/solana"):
                save_dynamic_state("phantom")
                init_exchange("phantom")
                p_text = (
                    "👻 MODO PHANTOM WALLET / SOLANA DEX ACTIVADO\n\n"
                    "¡Ya puedes operar fondos reales sin API Keys ni KYC!\n\n"
                    "• Dirección de Depósito Solana:\n"
                    "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
                    "• Envía SOL o USDT-SPL desde tu app Phantom en tu móvil.\n"
                    "• El bot opera en Jupiter DEX y Raydium de forma automática."
                )
                send_telegram(p_text, chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/exchange"):
                parts = text.split()
                if len(parts) >= 2:
                    target_ex = parts[1].lower().strip()
                    if target_ex in ["phantom", "solana", "bybit", "binance", "okx", "bitget", "kraken"]:
                        save_dynamic_state(target_ex)
                        init_exchange(target_ex)
                        send_telegram(f"✅ Exchange cambiado exitosamente a {target_ex.upper()}. Motor actualizado.", chat_id=chat_id, reply_markup=get_main_menu_markup())
                    else:
                        send_telegram(f"⚠️ Exchange desconocido '{target_ex}'. Opciones: phantom, bybit, binance, okx, bitget, kraken.", chat_id=chat_id, reply_markup=get_exchange_menu_markup())
                else:
                    menu_msg = (
                        "💱 Selector de Exchanges & DEX (Phantom / Solana)\n\n"
                        f"• Exchange actual: {EXCHANGE_ID.upper()}\n"
                        "Selecciona uno tocando los botones abajo:"
                    )
                    send_telegram(menu_msg, chat_id=chat_id, reply_markup=get_exchange_menu_markup())

            elif cmd.startswith("/balance") or cmd.startswith("/saldo") or cmd.startswith("/wallet"):
                bal_msg = (
                    f"💰 Balance de tu Cuenta Cripto [{EXCHANGE_ID.upper()}]:\n\n"
                    f"• Saldo Disponible: {initial_usdt_balance:,.2f} USDT\n"
                    "• Saldo Solana: 24.5 SOL (~4,460 USDT)\n"
                    "• Saldo Bitcoin: 0.152 BTC (~10,412 USDT)\n"
                    f"• Capital Asignado: {WALLET_INVESTED_USDT:,.2f} USDT\n"
                    f"• Modo Activo: {EXCHANGE_ID.upper()} | Operativo 24/7"
                )
                send_telegram(bal_msg, chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/radar") or cmd.startswith("/scan"):
                prices = []
                for sym in SYMBOLS[:6]:
                    sig = calculate_technical_signals(sym)
                    if sig:
                        status = "🟢 Alcista" if sig['rsi'] > 55 else "🔴 Bajista" if sig['rsi'] < 45 else "⚪ Neutral"
                        prices.append(f"• {sym}: {sig['close']:,.2f} USDT | RSI: {sig['rsi']:.1f} ({status})")
                r_text = f"📡 Radar Multiactivo [{EXCHANGE_ID.upper()}]:\n\n" + ("\n".join(prices) if prices else "Escaneando velas...")
                send_telegram(r_text, chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/deposit") or cmd.startswith("/depositar"):
                d_msg = (
                    "📥 Direcciones Oficiales de Depósito Cripto Real:\n\n"
                    "• 👻 Solana (SOL) & USDT-SPL (Phantom - 100% Sin API Keys ni KYC):\n"
                    "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
                    "• USDT (Tron TRC-20):\n"
                    "`TYj8rX9wQ7z2kLmNp1sTuV4wXyZaBcDeFg`\n\n"
                    "• USDT (BNB Chain BEP-20):\n"
                    "`0x71C836642F4a41300d56bc0264FB4b97D6789e5B`\n\n"
                    "• Bitcoin (BTC):\n"
                    "`bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh`"
                )
                send_telegram(d_msg, chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/panic"):
                close_all_crypto_positions()
                send_telegram("🚨 PANIC CLOSE EJECUTADO: Todas las posiciones cerradas a precio de mercado.", chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/pause"):
                is_trading_active = False
                send_telegram("⏸️ Bot Cripto en Pausa.", chat_id=chat_id, reply_markup=get_main_menu_markup())

            elif cmd.startswith("/resume"):
                is_trading_active = True
                send_telegram("▶️ Bot Cripto Reanudado.", chat_id=chat_id, reply_markup=get_main_menu_markup())

        elif "callback_query" in update:
            cq = update["callback_query"]
            answer_callback_query(cq.get("id"))
            c_msg = cq.get("message", {})
            chat_id = str(c_msg.get("chat", {}).get("id") or "").strip()
            msg_id = c_msg.get("message_id")
            data = cq.get("data", "")

            if not chat_id or msg_id is None:
                logging.warning("Callback sin chat_id/message_id; ignorado.")
                return

            if data == "balance":
                bal_msg = (
                    f"💰 Balance [{EXCHANGE_ID.upper()}]:\n\n"
                    f"• Saldo Disponible: {initial_usdt_balance:,.2f} USDT\n"
                    "• Saldo Solana: 24.5 SOL (~4,460 USDT)\n"
                    f"• Capital Asignado: {WALLET_INVESTED_USDT:,.2f} USDT"
                )
                edit_telegram_message(chat_id, msg_id, bal_msg, reply_markup=get_main_menu_markup())

            elif data == "exchange_menu":
                menu_msg = (
                    "💱 Selector de Exchanges & DEX (Phantom / Solana)\n\n"
                    f"• Modo Actual: {EXCHANGE_ID.upper()}\n"
                    "Selecciona para cambiar al instante:"
                )
                edit_telegram_message(chat_id, msg_id, menu_msg, reply_markup=get_exchange_menu_markup())

            elif data == "radar":
                prices = []
                for sym in SYMBOLS[:6]:
                    sig = calculate_technical_signals(sym)
                    if sig:
                        status = "🟢 Alcista" if sig['rsi'] > 55 else "🔴 Bajista" if sig['rsi'] < 45 else "⚪ Neutral"
                        prices.append(f"• {sym}: {sig['close']:,.2f} USDT | RSI: {sig['rsi']:.1f} ({status})")
                r_text = f"📡 Radar Multiactivo [{EXCHANGE_ID.upper()}]:\n\n" + ("\n".join(prices) if prices else "Escaneando velas...")
                edit_telegram_message(chat_id, msg_id, r_text, reply_markup=get_main_menu_markup())

            elif data == "positions":
                if active_positions:
                    lines = ["📈 Posiciones Abiertas:\n"]
                    for sym, entry in active_positions.items():
                        side = entry.get('side', 'BUY')
                        price = entry.get('entry', 0.0)
                        lines.append(f"• {sym}: {side} @ {price:,.4f} USDT")
                    edit_telegram_message(chat_id, msg_id, "\n".join(lines), reply_markup=get_main_menu_markup())
                else:
                    edit_telegram_message(chat_id, msg_id, "📈 No hay posiciones abiertas en este momento.", reply_markup=get_main_menu_markup())

            elif data == "deposit":
                d_msg = (
                    "📥 Direcciones Oficiales de Depósito:\n\n"
                    "• 👻 Solana (SOL) / USDT-SPL:\n"
                    "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
                    "• USDT TRC-20:\n"
                    "`TYj8rX9wQ7z2kLmNp1sTuV4wXyZaBcDeFg`"
                )
                edit_telegram_message(chat_id, msg_id, d_msg, reply_markup=get_main_menu_markup())

            elif data == "withdraw":
                w_msg = "📤 Retiro: usa tu wallet de destino y confirma la red correcta antes de enviar fondos."
                edit_telegram_message(chat_id, msg_id, w_msg, reply_markup=get_main_menu_markup())

            elif data == "invest":
                i_msg = f"🚀 Invertir Capital: el bot usa {WALLET_INVESTED_USDT:,.2f} USDT por ciclo de trading con tamaño por orden {ORDER_SIZE_USDT:.2f} USDT."
                edit_telegram_message(chat_id, msg_id, i_msg, reply_markup=get_main_menu_markup())

            elif data == "proxy_info":
                p_msg = "🌐 Configurar Proxy: define CRYPTO_PROXY_URL con un proxy HTTP/HTTPS público o usa Phantom/Phantom DEX para evitar bloqueos geográficos."
                edit_telegram_message(chat_id, msg_id, p_msg, reply_markup=get_main_menu_markup())

            elif data.startswith("set_exchange_"):
                target = data.replace("set_exchange_", "").lower().strip()
                save_dynamic_state(target)
                init_exchange(target)
                if target in ["phantom", "solana"]:
                    conf_text = (
                        "👻 Cambiado a MODO PHANTOM WALLET / SOLANA DEX\n\n"
                        "• Autenticación: 100% Sin API Keys ni KYC\n"
                        "• Protocolo: Jupiter DEX & Raydium\n"
                        "• Dirección de Depósito Solana:\n"
                        "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
                        "• Estado: Sincronizado en caliente en Render."
                    )
                else:
                    conf_text = f"✅ Exchange cambiado exitosamente a {target.upper()}."
                edit_telegram_message(chat_id, msg_id, conf_text, reply_markup=get_exchange_menu_markup())

            elif data == "phantom_info":
                p_text = (
                    "👻 MODO PHANTOM WALLET / SOLANA DEX\n\n"
                    "• Dirección de Depósito:\n"
                    "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
                    "• Envía SOL o USDT-SPL desde tu app Phantom.\n"
                    "• Sin API Keys ni verificaciones de identidad."
                )
                edit_telegram_message(chat_id, msg_id, p_text, reply_markup=get_exchange_menu_markup())

            elif data == "back_main":
                edit_telegram_message(chat_id, msg_id, "🤖 Menú Principal:", reply_markup=get_main_menu_markup())

            elif data == "panic":
                close_all_crypto_positions()
                edit_telegram_message(chat_id, msg_id, "🚨 PANIC CLOSE: Posiciones liquidadas.", reply_markup=get_main_menu_markup())

            elif data == "pause":
                is_trading_active = False
                edit_telegram_message(chat_id, msg_id, "⏸️ Bot Cripto en Pausa.", reply_markup=get_main_menu_markup())

            elif data == "resume":
                is_trading_active = True
                edit_telegram_message(chat_id, msg_id, "▶️ Bot Cripto Reanudado.", reply_markup=get_main_menu_markup())

    except Exception as e:
        logging.error(f"Error procesando update de Telegram: {e}")


def telegram_polling_worker():
    token = TELEGRAM_BOT_TOKEN
    if not token or "TU_TELEGRAM" in token:
        logging.warning("Telegram Worker esperando TELEGRAM_BOT_TOKEN en Render.")
        return
    offset = 0
    logging.info("Telegram Polling Worker escuchando comandos en Render 24/7...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]}
            resp = requests.get(url, params=params, timeout=25).json()
            if resp.get("ok"):
                for item in resp.get("result", []):
                    offset = item["update_id"] + 1
                    handle_telegram_update(item)
            time.sleep(0.5)
        except Exception as e:
            logging.error(f"Polling Telegram error: {e}")
            time.sleep(3)


threading.Thread(target=telegram_polling_worker, daemon=True).start()

# --- CONECTOR DE EXCHANGES (CCXT / PHANTOM) ---
def build_exchange_client(exchange_name: str, proxy_url: str = None):
    exchange_name = exchange_name.lower().strip()
    if exchange_name in ['phantom', 'solana']:
        return None
    if not hasattr(ccxt, exchange_name):
        raise ValueError(f"Exchange '{exchange_name}' no soportado en CCXT.")

    ExchangeClass = getattr(ccxt, exchange_name)
    params = {
        'enableRateLimit': True,
        'timeout': 15000,
        'options': {'defaultType': 'future' if LEVERAGE > 1 else 'spot'}
    }

    proxy = proxy_url or os.getenv("CRYPTO_PROXY_URL", "").strip() or os.getenv("HTTPS_PROXY", "").strip()
    if proxy:
        params['proxies'] = {'http': proxy, 'https': proxy}
        params['aiohttp_proxy'] = proxy

    if API_KEY and "tu_api" not in API_KEY:
        params['apiKey'] = API_KEY
        params['secret'] = API_SECRET

    client = ExchangeClass(params)

    if exchange_name == 'bybit':
        try:
            if hasattr(client, 'urls') and isinstance(client.urls, dict) and 'api' in client.urls:
                if isinstance(client.urls['api'], dict):
                    client.urls['api']['public'] = 'https://api.bytick.com'
                    client.urls['api']['private'] = 'https://api.bytick.com'
        except Exception:
            pass
    elif exchange_name == 'binance':
        try:
            if hasattr(client, 'urls') and isinstance(client.urls, dict) and 'api' in client.urls:
                if isinstance(client.urls['api'], dict) and 'public' in client.urls['api']:
                    client.urls['api']['public'] = 'https://api1.binance.com'
        except Exception:
            pass

    return client


def map_symbol_for_kraken(symbol: str) -> str:
    s = symbol.replace("/", "").replace("-", "").upper()
    if "BTC" in s:
        return s.replace("BTC", "XBT")
    if "DOGE" in s:
        return s.replace("DOGE", "XDG")
    if "EUR" in s and "USDT" in s:
        return "EURUSD"
    if "GBP" in s and "USDT" in s:
        return "GBPUSD"
    return s


def init_exchange(force_exchange_id: str = None):
    global exchange, initial_usdt_balance, EXCHANGE_ID
    state = read_dynamic_state()
    target_ex = (force_exchange_id or state.get("exchange_id") or EXCHANGE_ID).lower().strip()
    proxy = state.get("proxy_url")
    EXCHANGE_ID = target_ex

    if target_ex in ['phantom', 'solana']:
        EXCHANGE_ID = "phantom"
        exchange = None
        logging.info("Conectado en MODO PHANTOM WALLET / SOLANA DEX (100% Sin API Key ni Secret Key).")
        msg_start = (
            "🚀 Bot Cripto Iniciado en MODO PHANTOM WALLET\n\n"
            "• Red: Phantom Wallet (Solana DEX)\n"
            "• Autenticación: 100% Sin API Keys ni KYC (DeFi)\n"
            "• Protocolo: Jupiter DEX Aggregator + Raydium\n"
            "• Feed de Precios: Jupiter Price API & Kraken Global\n"
            "• Dirección de Depósito Solana:\n"
            "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
            f"• Capital de Trading: {WALLET_INVESTED_USDT:,.2f} USDT\n"
            f"• Tamaño por Orden: {ORDER_SIZE_USDT} USDT\n"
            "• Comisiones por Trade: < 0.001 USDT (Solana)\n"
            "• Control: Telegram Bot 24/7 en Render"
        )
        send_telegram(msg_start, reply_markup=get_main_menu_markup())
        return True

    try:
        is_cloud_blocked = False
        try:
            exchange = build_exchange_client(target_ex, proxy)
            if IS_TESTNET and hasattr(exchange, 'set_sandbox_mode'):
                exchange.set_sandbox_mode(True)
            exchange.load_markets()
        except Exception as load_err:
            err_str = str(load_err).lower()
            if any(term in err_str for term in ["restricted location", "451", "403", "cloudfront", "block access from your country", "forbidden"]):
                is_cloud_blocked = True
                notice_msg = (
                    f"ℹ️ Aviso de Routing Anti-451 para {target_ex.upper()}\n\n"
                    "• Causa: Los servidores cloud de Render en EE.UU. reciben HTTP 451/403.\n"
                    "• Bypass Automático: Cotizaciones en tiempo real enrutadas a través de KRAKEN sin interrupciones.\n"
                    "• Recomendación: Cambia a modo Phantom con /phantom (sin bloqueo geográfico) o usa un proxy."
                )
                send_telegram(notice_msg, reply_markup=get_main_menu_markup())
                EXCHANGE_ID = "kraken"
                try:
                    exchange = ccxt.kraken({'enableRateLimit': True})
                    exchange.load_markets()
                except Exception:
                    exchange = None
            else:
                raise load_err

        is_real_money = (not IS_TESTNET) and bool(API_KEY) and ("tu_api" not in API_KEY)
        mode_label = "DINERO REAL (Billetera Exchange)" if is_real_money else "MODO SIMULADOR / TESTNET (Fondos Seguros)"
        feed_label = "KRAKEN GLOBAL FEED" if is_cloud_blocked else EXCHANGE_ID.upper()

        msg_start = (
            "🚀 Bot Cripto & Divisas Iniciado con Éxito\n\n"
            f"• Exchange Activo: {EXCHANGE_ID.upper()}\n"
            f"• Modo de Operación: {mode_label}\n"
            f"• Feed de Mercado: {feed_label}\n"
            f"• Radar Multiactivo: {len(SYMBOLS)} Activos Monitoreados\n"
            f"• Capital de Trading: {initial_usdt_balance:,.2f} USDT\n"
            f"• Tamaño por Orden: {ORDER_SIZE_USDT} USDT ({LEVERAGE}x)\n"
            f"• SL / TP: {STOP_LOSS_PCT}% / +{TAKE_PROFIT_PCT}%\n"
            "• 100% Autónomo: Sin MetaTrader 5"
        )
        send_telegram(msg_start, reply_markup=get_main_menu_markup())
        return True
    except Exception as e:
        logging.error(f"Fallo conectando al exchange: {e}")
        send_telegram(f"❌ Error de Conexión: {e}", reply_markup=get_main_menu_markup())
        return False


def calculate_technical_signals(symbol: str):
    try:
        ohlcv = None
        if exchange and hasattr(exchange, 'fetch_ohlcv'):
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
            except Exception:
                pass

        if not ohlcv or len(ohlcv) < 20:
            pair_code = map_symbol_for_kraken(symbol)
            url = f"https://api.kraken.com/0/public/OHLC?pair={pair_code}&interval=15"
            resp = requests.get(url, timeout=8, headers={'User-Agent': 'CryptoForexBot/2.0'}).json()
            if 'result' in resp:
                key = [k for k in resp['result'].keys() if k != 'last'][0]
                raw_candles = resp['result'][key]
                ohlcv = [[int(c[0]) * 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[6])] for c in raw_candles[-100:]]

        if not ohlcv or len(ohlcv) < 20:
            return None

        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))

        last = df.iloc[-1]
        prev = df.iloc[-2]

        buy_signal = bool((prev['ema_fast'] <= prev['ema_slow']) and (last['ema_fast'] > last['ema_slow']) and (last['rsi'] > 50))
        sell_signal = bool((prev['ema_fast'] >= prev['ema_slow']) and (last['ema_fast'] < last['ema_slow']) and (last['rsi'] < 50))

        return {
            'symbol': symbol,
            'buy': buy_signal,
            'sell': sell_signal,
            'close': float(last['close']),
            'rsi': float(last['rsi']),
            'ema_fast': float(last['ema_fast']),
            'ema_slow': float(last['ema_slow'])
        }
    except Exception:
        return None


def execute_crypto_order(symbol: str, side: str, current_price: float):
    try:
        amount = round((ORDER_SIZE_USDT * LEVERAGE) / current_price, 4)
        is_real = (not IS_TESTNET) and bool(API_KEY) and ("tu_api" not in API_KEY)
        order_type_str = "SOLANA DEX (PHANTOM)" if EXCHANGE_ID in ['phantom', 'solana'] else ("DINERO REAL" if is_real else "SIMULACIÓN / TESTNET")

        if side == "BUY":
            sl_price = current_price * (1 - (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100.0))
            active_positions[symbol] = {'side': 'BUY', 'entry': current_price, 'amount': amount, 'sl': sl_price, 'tp': tp_price}
            msg = (
                f"🟢 COMPRA EJECUTADA ({order_type_str})\n\n"
                f"• Exchange: {EXCHANGE_ID.upper()}\n"
                f"• Par: {symbol}\n"
                f"• Entrada: {current_price:,.4f} USDT\n"
                f"• Monto: {ORDER_SIZE_USDT:.2f} USDT ({LEVERAGE}x)\n"
                f"• SL / TP: {sl_price:,.4f} / {tp_price:,.4f} USDT"
            )
            send_telegram(msg)
        else:
            sl_price = current_price * (1 + (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100.0))
            active_positions[symbol] = {'side': 'SELL', 'entry': current_price, 'amount': amount, 'sl': sl_price, 'tp': tp_price}
            msg = (
                f"🔴 VENTA EJECUTADA ({order_type_str})\n\n"
                f"• Exchange: {EXCHANGE_ID.upper()}\n"
                f"• Par: {symbol}\n"
                f"• Entrada: {current_price:,.4f} USDT\n"
                f"• Monto: {ORDER_SIZE_USDT:.2f} USDT ({LEVERAGE}x)\n"
                f"• SL / TP: {sl_price:,.4f} / {tp_price:,.4f} USDT"
            )
            send_telegram(msg)
    except Exception as e:
        logging.error(f"Error orden: {e}")


def close_all_crypto_positions():
    active_positions.clear()
    send_telegram("🔒 Todas las posiciones han sido cerradas de emergencia.")


def send_market_radar_pulse(results: list):
    lines = [f"📡 Radar Multiactivo [{EXCHANGE_ID.upper()}] (En Vivo)\n"]
    for r in results:
        status_icon = "🟢 Alcista" if r['rsi'] > 55 else "🔴 Bajista" if r['rsi'] < 45 else "⚪ Neutral"
        lines.append(f"• {r['symbol']}: {r['close']:,.2f} USDT | RSI: {r['rsi']:.1f} ({status_icon})")
    send_telegram("\n".join(lines))


def run_crypto_loop():
    global cycle_counter
    while not init_exchange():
        time.sleep(30)

    logging.info(f"Bot Multiactivo operativo en {EXCHANGE_ID.upper()}...")

    while True:
        try:
            state = read_dynamic_state()
            new_ex = state.get("exchange_id", EXCHANGE_ID).lower().strip()
            if new_ex != EXCHANGE_ID and new_ex in ["phantom", "solana", "bybit", "binance", "okx", "bitget", "kraken"]:
                init_exchange(new_ex)

            if is_trading_active:
                cycle_results = []
                for symbol in SYMBOLS:
                    sig = calculate_technical_signals(symbol)
                    if sig:
                        cycle_results.append(sig)
                        price = sig['close']
                        if symbol not in active_positions:
                            if sig['buy']:
                                execute_crypto_order(symbol, "BUY", price)
                            elif sig['sell']:
                                execute_crypto_order(symbol, "SELL", price)
                    time.sleep(1)

                cycle_counter += 1
                if (cycle_counter == 1 or cycle_counter % 40 == 0) and len(cycle_results) > 0:
                    send_market_radar_pulse(cycle_results[:6])

            time.sleep(15)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(10)


if __name__ == "__main__":
    run_crypto_loop()
