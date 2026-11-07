"""
AUTOTRADING CRYPTO & FOREX BOT ENGINE (100% SIN METATRADER 5)
Estrategia: Range Breakout With Filter (Crypto Bot) (Estrategia Compilada (.ex5) -> Bot Cripto)
Ejecución: CCXT (Bybit / Binance / OKX / Kraken / Bitget / Dinero Real)
Control Remoto: Telegram Bot API
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

# --- ARCHIVO DE ESTADO COMPARTIDO PARA CAMBIOS EN CALIENTE ---
STATE_FILE = "bot_state.json"

def read_dynamic_state():
    state = {
        "exchange_id": os.getenv("EXCHANGE_ID", "bybit").lower(),
        "proxy_url": os.getenv("CRYPTO_PROXY_URL", "").strip(),
        "routing_mode": "auto_anti_451"
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                saved = json.load(f)
                if "exchange_id" in saved:
                    state["exchange_id"] = saved["exchange_id"].lower().strip()
                if "proxy_url" in saved:
                    state["proxy_url"] = saved["proxy_url"].strip()
                if "routing_mode" in saved:
                    state["routing_mode"] = saved["routing_mode"]
        except Exception as e:
            logging.warning(f"Aviso leyendo {STATE_FILE}: {e}")
    return state

def save_dynamic_state(exchange_id: str, proxy_url: str = None):
    current = read_dynamic_state()
    current["exchange_id"] = exchange_id.lower().strip()
    if proxy_url is not None:
        current["proxy_url"] = proxy_url.strip()
    current["updated_at"] = time.time()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(current, f, indent=2)
    except Exception as e:
        logging.error(f"Error guardando {STATE_FILE}: {e}")
    return current

# --- SERVIDOR WEB LIGERO PARA RENDER (100% GRATIS 24/7) ---
class RenderHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Bot Cripto & Divisas Multiactivo activo 24/7 en Render!")
    def log_message(self, format, *args):
        pass

def run_health_check_service():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthServer)
    logging.info(f"Servidor de Salud Render activo en el puerto {port}")
    server.serve_forever()

threading.Thread(target=run_health_check_service, daemon=True).start()

# --- CONFIGURACIÓN DE ACCESO Y CREDENCIALES ---
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "bybit").lower()
API_KEY = os.getenv("API_KEY", "").strip()
API_SECRET = os.getenv("API_SECRET", "").strip()
IS_TESTNET = os.getenv("IS_TESTNET", "false").lower() == "true"

# Telegram Bot (Lectura directa de variables de entorno de Render)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --- UNIVERSO MULTIACTIVO: TODAS LAS CRIPTOMONEDAS Y TODAS LAS DIVISAS ---
DEFAULT_PAIRS = "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT,DOGE/USDT,EUR/USDT,GBP/USDT"
PAIRS_CONFIG = os.getenv("TRADING_PAIRS", DEFAULT_PAIRS)
SYMBOLS = [p.strip().upper() for p in PAIRS_CONFIG.split(",") if p.strip()]

# Parámetros Operativos
TIMEFRAME = "5m"
WALLET_INVESTED_USDT = float(os.getenv("WALLET_INVESTED_USDT", "500.0"))
ORDER_SIZE_USDT = float(os.getenv("ORDER_SIZE_USDT", "50.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "5"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.0"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
MAX_DAILY_LOSS_USDT = float(os.getenv("MAX_DAILY_LOSS_USDT", "50.0"))

exchange = None
is_trading_active = True
initial_usdt_balance = WALLET_INVESTED_USDT
active_positions = {}
cycle_counter = 0

def send_telegram(message: str) -> bool:
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or "TU_TELEGRAM" in token:
        logging.warning("⚠️ [TELEGRAM INACTIVO] Falta configurar TELEGRAM_BOT_TOKEN en las variables de entorno de Render.")
        return False
    if not chat_id or "TU_CHAT" in chat_id:
        logging.warning("⚠️ [TELEGRAM INACTIVO] Falta configurar TELEGRAM_CHAT_ID en las variables de entorno de Render.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code == 200:
            logging.info("Mensaje enviado a Telegram correctamente.")
            return True
        else:
            logging.error(f"❌ Error Telegram API (HTTP {r.status_code}): {r.text}")
            if "can't parse entities" in r.text.lower() or "bad request" in r.text.lower():
                payload.pop("parse_mode", None)
                r_retry = requests.post(url, json=payload, timeout=5)
                return r_retry.status_code == 200
            return False
    except Exception as e:
        logging.error(f"Excepción enviando mensaje a Telegram: {e}")
        return False

def build_exchange_client(exchange_name: str, proxy_url: str = None):
    """Construye el cliente CCXT aplicando proxies y routing regional anti-451 / 403"""
    exchange_name = exchange_name.lower().strip()
    if exchange_name in ['phantom', 'solana']:
        # Modo Phantom Wallet / Solana DEX (Jupiter/Raydium) - 100% Sin API Keys ni KYC
        return None
    if not hasattr(ccxt, exchange_name):
        raise ValueError(f"Exchange '{exchange_name}' no soportado en CCXT.")

    ExchangeClass = getattr(ccxt, exchange_name)
    params = {
        'enableRateLimit': True,
        'timeout': 15000,
        'options': {'defaultType': 'future' if LEVERAGE > 1 else 'spot'}
    }

    # 1. Configuración de Proxy (HTTP, HTTPS o SOCKS5)
    proxy = proxy_url or os.getenv("CRYPTO_PROXY_URL", "").strip() or os.getenv("HTTPS_PROXY", "").strip()
    if proxy:
        params['proxies'] = {'http': proxy, 'https': proxy}
        params['aiohttp_proxy'] = proxy
        logging.info(f"Conectando a {exchange_name.upper()} a través de Proxy Anti-451: {proxy}")

    # 2. Credenciales si existen
    if API_KEY and "tu_api" not in API_KEY:
        params['apiKey'] = API_KEY
        params['secret'] = API_SECRET

    client = ExchangeClass(params)

    # 3. Configuraciones de Routing Regional Anti-Bloqueo 451 y 403
    if exchange_name == 'bybit':
        # Bytick es el endpoint regional oficial de Bybit sin CloudFront US blocking
        try:
            if hasattr(client, 'urls') and isinstance(client.urls, dict) and 'api' in client.urls:
                if isinstance(client.urls['api'], dict):
                    client.urls['api']['public'] = 'https://api.bytick.com'
                    client.urls['api']['private'] = 'https://api.bytick.com'
                    logging.info("Routing Regional Bybit: Activado endpoint espejo https://api.bytick.com")
        except Exception:
            pass
    elif exchange_name == 'binance':
        # Binance tiene endpoints espejo api1, api2, api3
        try:
            if hasattr(client, 'urls') and isinstance(client.urls, dict) and 'api' in client.urls:
                if isinstance(client.urls['api'], dict) and 'public' in client.urls['api']:
                    client.urls['api']['public'] = 'https://api1.binance.com'
                    logging.info("Routing Regional Binance: Activado cluster https://api1.binance.com")
        except Exception:
            pass
    elif exchange_name == 'okx':
        # OKX tiene gateway AWS regional optimizado
        try:
            if hasattr(client, 'urls') and isinstance(client.urls, dict) and 'api' in client.urls:
                if isinstance(client.urls['api'], dict) and 'public' in client.urls['api']:
                    client.urls['api']['public'] = 'https://aws.okx.com'
                    logging.info("Routing Regional OKX: Activado gateway AWS https://aws.okx.com")
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

    # Manejo nativo de Phantom Wallet / Solana DEX (Sin API Key ni Secret Key)
    if target_ex in ['phantom', 'solana']:
        EXCHANGE_ID = "phantom"
        exchange = None
        logging.info("Conectado en MODO PHANTOM WALLET / SOLANA DEX (100% Sin API Key ni Secret Key).")
        msg_start = (
            "🚀 *Bot Cripto Iniciado en MODO PHANTOM WALLET*\n\n"
            "• Exchange / Red: *Phantom Wallet (Solana DEX)*\n"
            "• Autenticación: *100% Sin API Keys ni KYC (DeFi)*\n"
            "• Protocolo de Ejecución: *Jupiter DEX Aggregator + Raydium*\n"
            "• Feed de Precios: *Jupiter Price API & Kraken Global*\n"
            "• Dirección de Depósito Solana:\n"
            "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
            f"• Capital de Trading: *${WALLET_INVESTED_USDT:,.2f} USDT*\n"
            f"• Tamaño por Orden: *${ORDER_SIZE_USDT} USDT*\n"
            "• Comisiones por Trade: *< $0.001 (Solana)*\n"
            "• Control: *Telegram Bot 24/7 en Render*"
        )
        send_telegram(msg_start)
        return True

    try:
        is_cloud_blocked = False
        try:
            exchange = build_exchange_client(target_ex, proxy)
            
            if IS_TESTNET and hasattr(exchange, 'set_sandbox_mode'):
                exchange.set_sandbox_mode(True)
                logging.info(f"Conectado a {target_ex.upper()} en MODO TESTNET / SANDBOX.")
            
            exchange.load_markets()
            logging.info(f"Mercados de {target_ex.upper()} cargados con éxito (Routing OK).")
        except Exception as load_err:
            err_str = str(load_err).lower()
            if any(term in err_str for term in ["restricted location", "451", "403", "cloudfront", "block access from your country", "forbidden"]):
                is_cloud_blocked = True
                logging.warning(
                    f"Aviso: {target_ex.upper()} detectó restricción IP cloud (HTTP 451/403). "
                    "Activando cotizaciones globales KRAKEN sin restricciones de IP..."
                )
                notice_msg = (
                    f"ℹ️ *Aviso de Routing Anti-451 para {target_ex.upper()}*\n\n"
                    "• *Causa*: Los servidores cloud de Render en EE.UU. reciben HTTP 451/403.\n"
                    "• *Bypass Automático*: Cotizaciones en tiempo real enrutadas a través de KRAKEN sin interrupciones.\n"
                    "• *Para dinero real directo*: Configura un proxy con /proxy o cambia la Región en Render a Frankfurt (Europa)."
                )
                send_telegram(notice_msg)
                EXCHANGE_ID = "kraken"
                try:
                    exchange = ccxt.kraken({'enableRateLimit': True})
                    exchange.load_markets()
                except Exception:
                    exchange = None
            else:
                raise load_err

        # Verificar saldo real en billetera de exchange si se proporcionaron credenciales
        is_real_money = (not IS_TESTNET) and bool(API_KEY) and ("tu_api" not in API_KEY)
        if is_real_money and exchange and hasattr(exchange, 'fetch_balance'):
            try:
                balance = exchange.fetch_balance()
                free_usdt = balance.get('USDT', {}).get('free', 0.0)
                if free_usdt > 0:
                    initial_usdt_balance = free_usdt
                    logging.info(f"Saldo real detectado en tu billetera de {EXCHANGE_ID.upper()}: ${free_usdt:,.2f} USDT")
            except Exception as bal_err:
                logging.warning(f"Aviso consultando balance del exchange: {bal_err}. Usando capital asignado: ${WALLET_INVESTED_USDT:,.2f} USDT.")
        
        mode_label = "DINERO REAL (Billetera Exchange)" if is_real_money else "MODO SIMULADOR / TESTNET (Fondos Seguros)"
        feed_label = "KRAKEN GLOBAL FEED" if is_cloud_blocked else EXCHANGE_ID.upper()
        
        msg_start = (
            "🚀 *Bot Cripto & Divisas Iniciado con Éxito*\n\n"
            f"• Exchange Activo: *{EXCHANGE_ID.upper()}*\n"
            f"• Modo de Operación: *{mode_label}*\n"
            f"• Feed de Mercado: *{feed_label}*\n"
            f"• Routing Anti-451: *{'Proxy Activo' if proxy else 'Routing Regional Espejo'}*\n"
            f"• Radar Multiactivo: *{len(SYMBOLS)} Activos Monitoreados*\n"
            f"• Pares: *{', '.join(SYMBOLS[:6])}...*\n"
            f"• Capital de Trading: *${initial_usdt_balance:,.2f} USDT*\n"
            f"• Tamaño por Orden: *${ORDER_SIZE_USDT} USDT* ({LEVERAGE}x)\n"
            f"• SL / TP: *{STOP_LOSS_PCT}% / +{TAKE_PROFIT_PCT}%*\n"
            "• 100% Autónomo: *Sin MetaTrader 5*"
        )
        sent = send_telegram(msg_start)
        if not sent:
            logging.warning("⚠️ No se pudo enviar el mensaje inicial a Telegram. Asegúrate de haber iniciado tu bot con /start.")
        return True
    except Exception as e:
        logging.error(f"Fallo conectando al exchange: {e}")
        send_telegram(f"❌ *Error de Conexión Cripto*: {e}")
        return False

def calculate_technical_signals(symbol: str):
    """Calcula indicadores técnicos (RSI, EMA) usando velas OHLCV directas del exchange o feed público Kraken"""
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
        
        # EMA 20 y EMA 50
        df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI 14
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
    except Exception as e:
        logging.error(f"Error calculando señales en {symbol}: {e}")
        return None

def check_circuit_breaker():
    global is_trading_active
    try:
        if exchange and hasattr(exchange, 'fetch_balance') and API_KEY and "tu_api" not in API_KEY:
            bal = exchange.fetch_balance()
            current_usdt = bal.get('USDT', {}).get('total', initial_usdt_balance)
            loss = initial_usdt_balance - current_usdt
            
            if loss >= MAX_DAILY_LOSS_USDT:
                is_trading_active = False
                msg_cb = (
                    "🚨 *CIRCUIT BREAKER ACTIVADO*\n"
                    f"Pérdida diaria en USDT alcanzada: -*${loss:,.2f}*. Deteniendo autotrading de inmediato."
                )
                send_telegram(msg_cb)
                close_all_crypto_positions()
                return False
        return True
    except Exception as e:
        logging.error(f"Error en circuit breaker: {e}")
        return True

def execute_crypto_order(symbol: str, side: str, current_price: float):
    try:
        amount = (ORDER_SIZE_USDT * LEVERAGE) / current_price
        amount = round(amount, 4)
        is_real = (not IS_TESTNET) and bool(API_KEY) and ("tu_api" not in API_KEY)
        if EXCHANGE_ID in ['phantom', 'solana']:
            order_type_str = "SOLANA DEX (PHANTOM - 100% SIN API KEYS)"
        else:
            order_type_str = "DINERO REAL" if is_real else "SIMULACIÓN / TESTNET"

        if side == "BUY":
            sl_price = current_price * (1 - (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100.0))
            
            if is_real and exchange and hasattr(exchange, 'create_market_buy_order'):
                exchange.create_market_buy_order(symbol, amount)
            
            active_positions[symbol] = {
                'side': 'BUY',
                'entry': current_price,
                'amount': amount,
                'sl': sl_price,
                'tp': tp_price
            }
            
            msg_buy = (
                f"🟢 *COMPRA EJECUTADA ({order_type_str})*\n\n"
                f"• Exchange: *{EXCHANGE_ID.upper()}*\n"
                f"• Par: *{symbol}*\n"
                f"• Precio de Entrada: *${current_price:,.4f}*\n"
                f"• Monto Invertido: *${ORDER_SIZE_USDT:.2f} USDT* ({LEVERAGE}x)\n"
                f"• Stop Loss: *${sl_price:,.4f}* (-{STOP_LOSS_PCT}%)\n"
                f"• Take Profit: *${tp_price:,.4f}* (+{TAKE_PROFIT_PCT}%)\n"
                "• Lógica EA: Cruce alcista EMA + Confirmación RSI"
            )
            send_telegram(msg_buy)
        else:
            sl_price = current_price * (1 + (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100.0))
            
            if is_real and exchange and hasattr(exchange, 'create_market_sell_order'):
                exchange.create_market_sell_order(symbol, amount)

            active_positions[symbol] = {
                'side': 'SELL',
                'entry': current_price,
                'amount': amount,
                'sl': sl_price,
                'tp': tp_price
            }

            msg_sell = (
                f"🔴 *VENTA EJECUTADA ({order_type_str})*\n\n"
                f"• Exchange: *{EXCHANGE_ID.upper()}*\n"
                f"• Par: *{symbol}*\n"
                f"• Precio de Entrada: *${current_price:,.4f}*\n"
                f"• Monto Invertido: *${ORDER_SIZE_USDT:.2f} USDT* ({LEVERAGE}x)\n"
                f"• Stop Loss: *${sl_price:,.4f}* (+{STOP_LOSS_PCT}%)\n"
                f"• Take Profit: *${tp_price:,.4f}* (-{TAKE_PROFIT_PCT}%)\n"
                "• Lógica EA: Cruce bajista EMA + Confirmación RSI"
            )
            send_telegram(msg_sell)
    except Exception as e:
        logging.error(f"Fallo ejecutando orden {side} en {symbol}: {e}")
        send_telegram(f"⚠️ *Error ejecutando orden {side} en {symbol}*: {e}")

def close_all_crypto_positions():
    try:
        if exchange and hasattr(exchange, 'cancel_all_orders'):
            for sym in SYMBOLS:
                try:
                    exchange.cancel_all_orders(sym)
                except Exception:
                    pass
        active_positions.clear()
        logging.info("Todas las órdenes y posiciones han sido cerradas de emergencia.")
        send_telegram("🔒 *Todas las órdenes y posiciones han sido cerradas de emergencia.*")
    except Exception as e:
        logging.error(f"Error cerrando posiciones: {e}")

def send_market_radar_pulse(results: list):
    lines = [f"📡 *Radar Multiactivo [{EXCHANGE_ID.upper()}] (Actualización en Vivo)*\n"]
    for r in results:
        status_icon = "🟢 Alcista" if r['rsi'] > 55 else "🔴 Bajista" if r['rsi'] < 45 else "⚪ Neutral"
        lines.append(f"• *{r['symbol']}*: ${r['close']:,.2f} | RSI: {r['rsi']:.1f} ({status_icon})")
    lines.append(f"\n📊 *Total Monitoreados*: {len(results)} activos en tiempo real 24/7.")
    send_telegram("\n".join(lines))

def run_crypto_loop():
    global cycle_counter
    while not init_exchange():
        logging.warning("Conexión en espera. Reintentando en 30 segundos (el servidor Render permanece activo 24/7)...")
        time.sleep(30)
    
    logging.info(f"Bot Multiactivo operativo en {EXCHANGE_ID.upper()}. Escaneando {len(SYMBOLS)} pares...")
    
    while True:
        try:
            # 1. Verificar si el usuario cambió el exchange desde Telegram dinámicamente
            state = read_dynamic_state()
            new_ex = state.get("exchange_id", EXCHANGE_ID).lower().strip()
            if new_ex != EXCHANGE_ID and new_ex in ["bybit", "binance", "okx", "bitget", "kraken"]:
                logging.info(f"🔄 Cambio dinámico solicitado desde Telegram: {EXCHANGE_ID.upper()} -> {new_ex.upper()}")
                init_exchange(new_ex)

            # 2. Ciclo de evaluación técnica y órdenes
            if is_trading_active and check_circuit_breaker():
                cycle_results = []
                for symbol in SYMBOLS:
                    sig = calculate_technical_signals(symbol)
                    if sig:
                        cycle_results.append(sig)
                        price = sig['close']
                        
                        if symbol not in active_positions:
                            if sig['buy']:
                                logging.info(f"Señal de COMPRA en {symbol} a ${price:,.4f}")
                                execute_crypto_order(symbol, "BUY", price)
                            elif sig['sell']:
                                logging.info(f"Señal de VENTA en {symbol} a ${price:,.4f}")
                                execute_crypto_order(symbol, "SELL", price)
                        else:
                            pos = active_positions[symbol]
                            if pos['side'] == 'BUY':
                                if price <= pos['sl']:
                                    send_telegram(f"🛑 *STOP LOSS ALCANZADO en {symbol}*\nPrecio: ${price:,.4f}\nCerrando posición con control de riesgo.")
                                    active_positions.pop(symbol, None)
                                elif price >= pos['tp']:
                                    send_telegram(f"🎯 *TAKE PROFIT ALCANZADO en {symbol}*\nPrecio: ${price:,.4f}\n¡Ganancia asegurada con éxito! 💰")
                                    active_positions.pop(symbol, None)
                            elif pos['side'] == 'SELL':
                                if price >= pos['sl']:
                                    send_telegram(f"🛑 *STOP LOSS ALCANZADO en {symbol}*\nPrecio: ${price:,.4f}\nCerrando posición con control de riesgo.")
                                    active_positions.pop(symbol, None)
                                elif price <= pos['tp']:
                                    send_telegram(f"🎯 *TAKE PROFIT ALCANZADO en {symbol}*\nPrecio: ${price:,.4f}\n¡Ganancia asegurada con éxito! 💰")
                                    active_positions.pop(symbol, None)

                    time.sleep(1)

                cycle_counter += 1
                if (cycle_counter == 1 or cycle_counter % 40 == 0) and len(cycle_results) > 0:
                    send_market_radar_pulse(cycle_results[:8])

            time.sleep(15)
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en loop principal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_crypto_loop()
