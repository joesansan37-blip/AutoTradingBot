# AutoTradingBot — simulador de futuros de SOL

Esta rama sustituye el modo de ejecución por un **simulador paper-only** de una posición lineal USDT-margined sobre `SOL/USDT`. Las señales se calculan con velas públicas de CCXT. El ledger, las posiciones, comisiones estimadas, SL/TP y PnL son simulados y se guardan en `paper_account.json`.

> **No se conecta a Phantom ni a un DEX, no lee claves de exchange y no envía órdenes reales.** La red Solana no es un exchange de futuros; este primer simulador modela un futuro perpetuo sobre SOL a partir de precios públicos. No modela funding, slippage ni liquidaciones. Si el servicio se reinicia, el archivo `paper_account.json` debe persistir para mantener el ledger (configura un disco persistente en Render).

## Configuración en Render

- `EXECUTION_MODE=paper` (único modo aceptado; cualquier otro valor hace que el programa se detenga)
- `DATA_EXCHANGE=kraken` (solo lectura pública; el exchange debe ofrecer `SOL/USDT`)
- `TRADING_SYMBOL=SOL/USDT`
- `TIMEFRAME=15m`
- `PAPER_STARTING_BALANCE_USDT=500`
- `ORDER_MARGIN_USDT=25` — margen simulado por operación; el nocional es margen × apalancamiento
- `LEVERAGE=2` — permitido de 1 a 10
- `STOP_LOSS_PCT=2`
- `TAKE_PROFIT_PCT=4`
- `PAPER_FEE_RATE=0.0006` — comisión simulada por cada lado de la operación
- `MAX_DAILY_LOSS_USDT=25`
- `SCAN_SECONDS=15`
- `PAPER_STATE_FILE=/ruta/persistente/paper_account.json`
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para los avisos y controles opcionales

No configures `API_KEY` o `API_SECRET`: el cliente de mercado es público y la aplicación no implementa ejecución real.

## Telegram

`/start`, `/balance`, `/positions`, `/radar`, `/pause`, `/resume`, `/panic`. Los botones del menú ofrecen las mismas acciones. Si se configura `TELEGRAM_CHAT_ID`, se ignoran actualizaciones de otros chats. Al pausar, el bot deja de abrir posiciones pero continúa comprobando SL/TP de las abiertas.

La estrategia abre paper-long o paper-short cuando el cruce EMA20/EMA50 en una vela cerrada coincide con el filtro RSI. SL/TP se comprueban con máximos/mínimos de velas; si ambos niveles aparecen tocados en la misma vela, el simulador asigna conservadoramente el stop.

## Prueba

Despliega primero en un entorno de prueba y revisa balance, posiciones y cierres en Telegram y en el ledger persistente. El PnL es una estimación educativa, no una garantía de ejecución ni de resultados futuros.
