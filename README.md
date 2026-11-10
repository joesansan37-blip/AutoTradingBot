# AutoTradingBot — simulador paper-only de futuros SOL/USDT

La aplicación usa velas públicas para calcular una señal EMA/RSI con filtro de volatilidad y mantiene una cuenta simulada local. **No se conecta a Phantom, no usa claves de exchange y no envía órdenes reales.** La simulación no representa una garantía de ejecución ni de rentabilidad.

## Panel de Telegram

Configura `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como variables de entorno. El bot ofrece los comandos `/panel`, `/status`, `/strategy`, `/balance`, `/positions`, `/radar`, `/trades`, `/pause`, `/resume` y `/panic`. `/panic` solo cierra posiciones simuladas. El panel incluye estado del proceso, última lectura de mercado, señal/indicadores, equity paper, PnL y posiciones.

## Variables de entorno principales

- `EXECUTION_MODE=paper` — único modo permitido.
- `DATA_EXCHANGE=kraken` — acceso público de solo lectura.
- `TRADING_SYMBOL=SOL/USDT`, `TIMEFRAME=15m`.
- `PAPER_STARTING_BALANCE_USDT=500`, `ORDER_MARGIN_USDT=25`, `LEVERAGE=2` (1–10).
- `STOP_LOSS_PCT=2`, `TAKE_PROFIT_PCT=4`, `MAX_DAILY_LOSS_USDT=25`.
- `PAPER_STATE_FILE=paper_account.json` — usa almacenamiento persistente en el host de despliegue.
- Parámetros de estrategia: `STRATEGY_EMA_FAST=20`, `STRATEGY_EMA_SLOW=50`, `STRATEGY_RSI_PERIOD=14`, `STRATEGY_RSI_LONG=55`, `STRATEGY_RSI_SHORT=45`, `STRATEGY_MIN_VOLATILITY_PCT=0.003`, `STRATEGY_MAX_RISK_PCT=0.05`.
- `SCAN_SECONDS=15`.

No configures `API_KEY` ni `API_SECRET`: el cliente de mercado es público.

## Ejecutar y probar

```bash
pip install -r requirements.txt
pytest -q
python main.py
```

Despliega primero en un entorno de prueba y revisa el estado/panel y el ledger persistente. El PnL y los controles son simulados y educativos, no asesoramiento financiero.
