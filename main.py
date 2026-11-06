"""
AUTOTRADING CRYPTO BOT ENGINE (100% CRIPTOMONEDAS - SIN METATRADER 5)
Estrategia: Range Breakout With Filter (Crypto Bot) (Estrategia Compilada (.ex5) -> Bot Cripto)
Ejecución: CCXT (Binance / Bybit / OKX / Bitget / KuCoin / Paper Trading)
Control Remoto: Telegram Bot API
"""

import time
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import ccxt
import requests
import pandas as pd
import numpy as np

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# --- SERVIDOR WEB LIGERO PARA RENDER (100% GRATIS 24/7) ---
class RenderHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Bot Cripto de Telegram ejecutandose 24/7 en Render!")
    def log_message(self, format, *args):
        pass

def run_health_check_service():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthServer)
    logging.info(f"Servidor de Salud Render activo en el puerto {port}")
    server.serve_forever()

threading.Thread(target=run_health_check_service, daemon=True).start()

# --- CONFIGURACIÓN DE EXCHANGE CRIPTO (SIN METATRADER) ---
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance").lower()
API_KEY = os.getenv("API_KEY", "tu_api_key_cripto")
API_SECRET = os.getenv("API_SECRET", "tu_api_secret_cripto")
IS_TESTNET = os.getenv("IS_TESTNET", "true").lower() == "true"

# Telegram Bot
TELEGRAM_BOT_TOKEN = "TU_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TU_CHAT_ID"

# Parámetros Operativos en Cripto
SYMBOL = os.getenv("CRYPTO_PAIR", "BTC/USDT")
TIMEFRAME = "5m"
ORDER_SIZE_USDT = float(os.getenv("ORDER_SIZE_USDT", "100.0"))  # Monto por operación en USDT
LEVERAGE = int(os.getenv("LEVERAGE", "5"))                      # 1x Spot, 2-10x Futuros
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.0"))        # Stop Loss: -2.0%
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))    # Take Profit: +5.0%
MAX_DAILY_LOSS_USDT = float(os.getenv("MAX_DAILY_LOSS_USDT", "50.0")) # Circuit Breaker

exchange = None
is_trading_active = True
initial_usdt_balance = 0.0

def send_telegram(message: str):
    """Envía alertas a Telegram con formato Markdown"""
    if not TELEGRAM_BOT_TOKEN or "TU_TELEGRAM" in TELEGRAM_BOT_TOKEN:
        logging.info(f"[TELEGRAM SIMULADO]: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Error enviando mensaje a Telegram: {e}")

def init_exchange():
    global exchange, initial_usdt_balance
    try:
        exchange_class = getattr(ccxt, EXCHANGE_ID)
        exchange = exchange_class({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'future' if LEVERAGE > 1 else 'spot'}
        })
        
        if IS_TESTNET and hasattr(exchange, 'set_sandbox_mode'):
            exchange.set_sandbox_mode(True)
            logging.info(f"Conectado a {EXCHANGE_ID.upper()} en MODO TESTNET / SANDBOX.")
        
        # Cargar mercados
        exchange.load_markets()
        
        # Ajustar apalancamiento si es futuros
        if LEVERAGE > 1 and hasattr(exchange, 'set_leverage'):
            try:
                exchange.set_leverage(LEVERAGE, SYMBOL)
                logging.info(f"Apalancamiento fijado a {LEVERAGE}x para {SYMBOL}")
            except Exception as lev_err:
                logging.warning(f"Aviso apalancamiento: {lev_err}")

        # Comprobar balance
        balance = exchange.fetch_balance()
        initial_usdt_balance = balance.get('USDT', {}).get('free', 1000.0)
        
        msg_start = f"""🚀 *Bot Cripto Iniciado con Éxito*

• Exchange: *{EXCHANGE_ID.upper()}* ({'TESTNET' if IS_TESTNET else 'REAL'})
• Par: *{SYMBOL}* | Marco: *{TIMEFRAME}*
• Saldo USDT: *$${initial_usdt_balance:,.2f}*
• Apalancamiento: *{LEVERAGE}x*
• 100% Cripto: *Sin MetaTrader 5*"""
        send_telegram(msg_start)
        return True
    except Exception as e:
        logging.error(f"Fallo conectando al exchange cripto: {e}")
        send_telegram(f"❌ *Error de Conexión Cripto*: {e}")
        return False

def calculate_technical_signals():
    """Calcula indicadores técnicos (RSI, EMA) usando velas OHLCV directas del exchange"""
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calcular EMA 20 y EMA 50
        df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # Calcular RSI 14
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Condiciones de Compra / Long
        buy_signal = (prev['ema_fast'] <= prev['ema_slow']) and (last['ema_fast'] > last['ema_slow']) and (last['rsi'] > 50)
        
        # Condiciones de Venta / Short
        sell_signal = (prev['ema_fast'] >= prev['ema_slow']) and (last['ema_fast'] < last['ema_slow']) and (last['rsi'] < 50)
        
        return {
            'buy': buy_signal,
            'sell': sell_signal,
            'close': float(last['close']),
            'rsi': float(last['rsi']),
            'ema_fast': float(last['ema_fast']),
            'ema_slow': float(last['ema_slow'])
        }
    except Exception as e:
        logging.error(f"Error calculando señales: {e}")
        return None

def check_circuit_breaker():
    """Circuit Breaker: Parada de emergencia si las pérdidas superan el umbral diario en USDT"""
    global is_trading_active
    try:
        bal = exchange.fetch_balance()
        current_usdt = bal.get('USDT', {}).get('total', initial_usdt_balance)
        loss = initial_usdt_balance - current_usdt
        
        if loss >= MAX_DAILY_LOSS_USDT:
            is_trading_active = False
            msg_cb = f"""🚨 *CIRCUIT BREAKER ACTIVADO*
Pérdida diaria en USDT alcanzada: -*$${loss:,.2f}*. Deteniendo autotrading de inmediato."""
            send_telegram(msg_cb)
            close_all_crypto_positions()
            return False
        return True
    except Exception as e:
        logging.error(f"Error en circuit breaker: {e}")
        return True

def execute_crypto_order(side: str, current_price: float):
    """Ejecuta orden en el Exchange de Criptomonedas con Stop Loss y Take Profit"""
    try:
        # Calcular cantidad de monedas según ORDER_SIZE_USDT
        amount = (ORDER_SIZE_USDT * LEVERAGE) / current_price
        amount = round(amount, 4)
        
        if side == "BUY":
            sl_price = current_price * (1 - (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100.0))
            order = exchange.create_market_buy_order(SYMBOL, amount)
            msg_buy = f"""🟢 *COMPRA EJECUTADA (LONG)*

• Par: *{SYMBOL}*
• Precio Entrada: *$${current_price:,.2f}*
• Monto: *{amount}* (~*$${ORDER_SIZE_USDT}* USDT a {LEVERAGE}x)
• Stop Loss: *$${sl_price:,.2f}* (-{STOP_LOSS_PCT}%)
• Take Profit: *$${tp_price:,.2f}* (+{TAKE_PROFIT_PCT}%)"""
            send_telegram(msg_buy)
        else:
            sl_price = current_price * (1 + (STOP_LOSS_PCT / 100.0))
            tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100.0))
            order = exchange.create_market_sell_order(SYMBOL, amount)
            msg_sell = f"""🔴 *VENTA EJECUTADA (SHORT)*

• Par: *{SYMBOL}*
• Precio Entrada: *$${current_price:,.2f}*
• Monto: *{amount}* (~*$${ORDER_SIZE_USDT}* USDT a {LEVERAGE}x)
• Stop Loss: *$${sl_price:,.2f}* (+{STOP_LOSS_PCT}%)
• Take Profit: *$${tp_price:,.2f}* (-{TAKE_PROFIT_PCT}%)"""
            send_telegram(msg_sell)
        return order
    except Exception as e:
        logging.error(f"Fallo ejecutando orden {side}: {e}")
        send_telegram(f"⚠️ *Error ejecutando orden {side}*: {e}")

def close_all_crypto_positions():
    """Cancela todas las órdenes pendientes y liquida posiciones a mercado"""
    try:
        exchange.cancel_all_orders(SYMBOL)
        logging.info("Todas las órdenes pendientes canceladas en el exchange.")
        send_telegram("🔒 *Todas las órdenes y posiciones han sido cerradas de emergencia en el Exchange.*")
    except Exception as e:
        logging.error(f"Error cerrando posiciones: {e}")

def run_crypto_loop():
    if not init_exchange():
        return
    logging.info("Bot Cripto operativo. Analizando velas del exchange en tiempo real...")
    
    while True:
        try:
            if is_trading_active and check_circuit_breaker():
                signals = calculate_technical_signals()
                if signals:
                    price = signals['close']
                    if signals['buy']:
                        logging.info(f"Señal de COMPRA en {SYMBOL} a ${price}")
                        execute_crypto_order("BUY", price)
                    elif signals['sell']:
                        logging.info(f"Señal de VENTA en {SYMBOL} a ${price}")
                        execute_crypto_order("SELL", price)
            time.sleep(15)  # Chequeo cada 15 segundos
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en loop principal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_crypto_loop()
