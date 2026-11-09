# AutoTradingBot — simulador paper-only de futuros SOL

Esta rama incluye tres **estrategias Python** seleccionables para simular una posición lineal sobre `SOL/USDT`:

- `ema_trend`: cruce EMA20/EMA50 con confirmación RSI.
- `rsi_reversion`: regreso dentro de las bandas de Bollinger con recuperación/deterioro del RSI.
- `donchian_breakout`: ruptura del máximo/mínimo de 20 velas previas, filtrada por EMA50.

No son Expert Advisors de MetaTrader. Se evalúan velas cerradas de un feed público CCXT. El simulador mantiene ledger, balance, comisiones estimadas, SL/TP y PnL paper; **no lee claves de exchange, no se conecta a Phantom/DEX y no envía órdenes reales**. El mercado de futuros se emula desde precios spot de SOL/USDT; no modela funding, slippage ni liquidaciones. Un resultado histórico o paper no garantiza resultados futuros.

## Render

- Branch: `paper-futures-simulator`
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- `EXECUTION_MODE=paper` (único modo; cualquier otro valor detiene la aplicación)
- `DATA_EXCHANGE=kraken` (solo mercado público; comprueba que ofrezca `SOL/USDT`)
- `TRADING_SYMBOL=SOL/USDT`
- `STRATEGY=ema_trend` — opciones: `ema_trend`, `rsi_reversion`, `donchian_breakout`.
- `TIMEFRAME=15m`
- `PAPER_STARTING_BALANCE_USDT=500`
- `ORDER_MARGIN_USDT=25`
- `LEVERAGE=2` (rango aceptado: 1–10)
- `STOP_LOSS_PCT=2`
- `TAKE_PROFIT_PCT=4`
- `PAPER_FEE_RATE=0.0006`
- `MAX_DAILY_LOSS_USDT=25`
- `SCAN_SECONDS=60` (el código aplica un mínimo de 30 segundos)
- `MARKET_DATA_CACHE_SECONDS=60` (mínimo 30 segundos; el radar y el ciclo comparten la misma caché)
- `PAPER_STATE_FILE=/var/data/paper_account.json` — usa un disco persistente Render para conservar ledger entre reinicios.
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para avisos/comandos. Mantén el token secreto.

No configures `API_KEY` ni `API_SECRET`. El cliente de datos no usa credenciales. CCXT tiene rate limiter activado y una pausa de 3 segundos; el bot no hace un `fetch_ticker` adicional. Si Kraken limita igualmente, usa el último snapshot guardado y aplica backoff. Mantén una sola instancia del servicio para evitar consultas paralelas usando la misma IP.

## Telegram y pruebas

Comandos: `/start`, `/balance`, `/positions`, `/radar`, `/pause`, `/resume`, `/panic`. Pausar impide nuevas aperturas, pero mantiene la comprobación de SL/TP. El límite de pérdida diaria bloquea nuevas posiciones paper. El radar informa precio/cierre de vela y RSI; puede usar datos cacheados y no es una cotización en tiempo real garantizada.

Ejecuta `python -m unittest discover -s tests`. Despliega primero en una instancia de prueba y revisa cierres, balance y ledger persistente. El simulador no garantiza que el comportamiento reproduzca una ejecución real.
