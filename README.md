# AutoTradingBot — simulador de futuros SOL/USDT en modo paper

El bot consume velas públicas, calcula señales EMA/RSI/ATR y mantiene una cuenta simulada local. **Solo admite `EXECUTION_MODE=paper`: no conecta wallets, no usa claves de exchange y no envía órdenes reales.** La simulación es educativa y no garantiza resultados.

## Configuración de entorno

Copia `.env.example` a `.env` para desarrollo local o configura las variables directamente en Render. No subas un `.env` con secretos. En Render, configura `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como secretos. Ambos deben estar configurados o ambos vacíos. No configures `API_KEY` ni `API_SECRET`.

| Variable | Predeterminado | Descripción / validación |
|---|---:|---|
| `EXECUTION_MODE` | `paper` | Único modo aceptado; otro valor detiene el arranque. |
| `DATA_EXCHANGE` | `kraken` | Exchange CCXT usado solo para datos públicos. |
| `TRADING_SYMBOL` | `SOL/USDT` | Único símbolo soportado. |
| `TIMEFRAME` | `15m` | Marco temporal de las velas. |
| `PAPER_STARTING_BALANCE_USDT` | `500` | Balance inicial simulado, debe ser > 0. |
| `PAPER_STATE_FILE` | `paper_account.json` | Ruta del ledger; usar disco persistente en Render para retenerlo entre despliegues. |
| `ORDER_MARGIN_USDT` | `25` | Margen simulado base por operación, > 0. |
| `LEVERAGE` | `2` | Apalancamiento simulado entre 1 y 10. |
| `STOP_LOSS_PCT` / `TAKE_PROFIT_PCT` | `2` / `4` | Barreras de salida simuladas en porcentaje. |
| `PAPER_FEE_RATE` | `0.0006` | Comisión simulada por lado; debe estar entre 0 y 0.01. |
| `MAX_DAILY_LOSS_USDT` | `25` | Límite diario de pérdida simulada, > 0. |
| `SCAN_SECONDS` | `15` | Intervalo de escaneo de 1 a 3600 segundos. |
| `TELEGRAM_BOT_TOKEN` | vacío | Token del bot (secreto); opcional junto con chat ID. |
| `TELEGRAM_CHAT_ID` | vacío | Chat autorizado; debe configurarse junto con el token. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. |
| `LOG_FORMAT` | `plain` | `plain` legible o `json` estructurado. |
| `STRATEGY_EMA_FAST` / `STRATEGY_EMA_SLOW` | `20` / `50` | Periodos EMA; rápida debe ser menor que lenta. |
| `STRATEGY_RSI_PERIOD` | `14` | Periodo RSI. |
| `STRATEGY_RSI_LONG` / `STRATEGY_RSI_SHORT` | `55` / `45` | Umbrales RSI de entrada. |
| `STRATEGY_ATR_PERIOD` | `14` | Periodo ATR. |
| `STRATEGY_MIN_VOLATILITY_PCT` / `STRATEGY_MAX_VOLATILITY_PCT` | `0.003` / `0.05` | Banda ATR/precio que permite señales. |
| `STRATEGY_TREND_SLOPE_PERIOD` | `5` | Velas cerradas para pendiente de EMA lenta. |
| `STRATEGY_TREND_SLOPE_FILTER` | `true` | Requiere pendiente de tendencia en la dirección de la señal. |
| `STRATEGY_MAX_RISK_PCT` / `STRATEGY_MIN_MARGIN` | `0.05` / `5` | Límites de dimensionamiento de margen paper. |
| `PORT` | `10000` | Puerto HTTP asignado por Render; se lee del entorno del host. |

## Arranque y salud

Render puede usar `python main.py` como comando de inicio (instalación: `pip install -r requirements.txt`). El proceso valida configuración antes de empezar, levanta `/healthz` para liveness y `/readyz` para readiness y reintenta errores transitorios de datos con backoff exponencial limitado. SIGTERM/SIGINT detienen los bucles y cierran el servidor de salud.

El logging va a stdout/stderr. Para logs estructurados de Render configura `LOG_FORMAT=json`; el nivel predeterminado `INFO` evita ruido habitual de CCXT y HTTP. `DEBUG` muestra ciclos de mercado y solicitudes de health.

## Telegram

`/panel` muestra las pantallas Overview, Performance y Strategy. Los botones permiten navegar y pausar/reanudar la simulación. El control de pausa solo evita nuevas aperturas; continúa monitorizando cierres paper.

## Pruebas

```bash
pip install -r requirements.txt
pytest -q
```
