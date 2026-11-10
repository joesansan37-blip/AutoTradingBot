# AutoTradingBot — simulador paper-only de futuros SOL

Esta rama incluye cuatro **estrategias Python** seleccionables para simular una posición sobre `SOL/USDT` con precios públicos:

- `ema_trend`: cruce EMA20/EMA50 con confirmación RSI.
- `rsi_reversion`: regreso dentro de las bandas de Bollinger con recuperación/deterioro del RSI.
- `donchian_breakout`: ruptura del máximo/mínimo de 20 velas previas, filtrada por EMA50.
- `multiasset_trend_pro`: conversión paper parcial del EA MQL5: cruce EMA12/EMA26, filtro ADX(14) >= 22, stop a 1.8 ATR y objetivo a 3 ATR.

La estrategia convertida también actualiza el stop a break-even al alcanzar 1 ATR y aplica trailing de 1.5 ATR. Los indicadores y señales se calculan sobre velas cerradas; el cálculo Python de ADX/ATR es una aproximación y puede no coincidir exactamente con MetaTrader. Las posiciones y ejecuciones son exclusivamente simuladas.

No es un Expert Advisor ejecutable en MetaTrader. Se evalúan velas de un feed público CCXT y se mantienen ledger, balance, comisiones estimadas, SL/TP y PnL paper. El bot no lee claves de exchange ni envía órdenes reales; los precios del feed pueden estar cacheados.

## Límites de la conversión

Aún no se han portado los filtros de noticias, spread, horario/días de operación, el límite de operaciones diarias, el dimensionamiento por porcentaje de riesgo ni los límites de pérdida diaria/total del EA original. El filtro de noticias de ese código MQL5 usa fechas aproximadas y no debe considerarse calendario económico fiable. La gestión de riesgo actual del simulador sigue usando margen fijo y `MAX_DAILY_LOSS_USDT`; esto no equivale al riesgo por operación del EA. Esta estrategia debe probarse primero en paper y no es una recomendación de inversión.

## Render

- Branch: `paper-futures-simulator`
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- `EXECUTION_MODE=paper` (único modo; cualquier otro valor detiene la aplicación)
- `DATA_EXCHANGE=kraken` (solo mercado público; comprueba que ofrezca `SOL/USDT`)
- `TRADING_SYMBOL=SOL/USDT` (único símbolo permitido actualmente)
- `STRATEGY=ema_trend` — opciones: `ema_trend`, `rsi_reversion`, `donchian_breakout`, `multiasset_trend_pro`.
- `TIMEFRAME=15m`
- `PAPER_STARTING_BALANCE_USDT=500`
- `ORDER_MARGIN_USDT=25`
- `LEVERAGE=2` (rango aceptado: 1–10)
- `STOP_LOSS_PCT=2` y `TAKE_PROFIT_PCT=4` para los perfiles existentes; `multiasset_trend_pro` usa sus niveles SL/TP por ATR.
- `PAPER_FEE_RATE=0.0006`
- `MAX_DAILY_LOSS_USDT=25`
- `SCAN_SECONDS=60` (el código aplica un mínimo de 30 segundos)
- `MARKET_DATA_CACHE_SECONDS=60` (mínimo 30 segundos; el radar y el ciclo comparten la misma caché)
- `PAPER_STATE_FILE=/var/data/paper_account.json` — usa un disco persistente Render para conservar ledger entre reinicios.
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para avisos/comandos. Mantén el token secreto.

No configures `API_KEY` ni `API_SECRET`. El cliente de datos no usa credenciales. CCXT tiene rate limiter activado y una pausa de 3 segundos; el bot no hace un `fetch_ticker` adicional. Si Kraken no está disponible, los errores se registran y el ciclo vuelve a intentarlo.

## Telegram y pruebas

Comandos: `/start`, `/balance`, `/positions`, `/radar`, `/pause`, `/resume`, `/panic`. Pausar impide nuevas aperturas, pero mantiene la comprobación de SL/TP. El límite de pérdida diaria bloquea nuevas posiciones según la configuración del ledger paper.

Ejecuta `python -m unittest discover -s tests`. Despliega primero en una instancia de prueba y revisa cierres, balance y ledger persistente. El simulador no garantiza que el comportamiento reproduzca exactamente un broker, MetaTrader ni los resultados futuros.
