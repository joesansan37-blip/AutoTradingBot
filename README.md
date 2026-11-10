## Telegram overview y filtros

El bot incluye tres pantallas breves en `/panel`: Overview (estado, precio y posición), Performance (PnL y operaciones UTC, drawdown actual/máximo) y Strategy (lectura EMA/RSI/ATR y diagnóstico de filtros). Los botones editan el mismo mensaje y permiten pausar/reanudar la simulación.

Filtros configurables por variables de entorno:
- `STRATEGY_TREND_SLOPE_PERIOD=5`: velas cerradas utilizadas para medir la pendiente de la EMA lenta.
- `STRATEGY_TREND_SLOPE_FILTER=true`: exige alineación de EMA rápida/lenta y pendiente en la dirección del trade.
- `STRATEGY_MIN_VOLATILITY_PCT=0.003` y `STRATEGY_MAX_VOLATILITY_PCT=0.05`: límites inferior/superior de ATR como fracción del precio. Un valor fuera de la banda bloquea entradas.

Todos los controles y señales siguen siendo paper-only; el dashboard no habilita ejecución real.
