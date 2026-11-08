# Funciones seguras de Solana y trading simulado

`safe_solana.py` añade utilidades de solo lectura y simulación. No firma ni transmite
transacciones, y no envía órdenes a exchanges.

## Activación

- Configura `SOLANA_WALLET_ADDRESS` con la dirección pública de tu wallet para habilitar
  el monitor de actividad entrante de SOL. El monitor toma una línea base al iniciar y
  luego reporta transacciones nuevas con un cambio neto positivo de SOL. No detecta SPL.
- `SOLANA_RPC_URL` es opcional; por defecto usa el RPC público de Solana, que puede tener
  límites de uso. Para producción, configura un proveedor RPC confiable.
- El trading simulado empieza desactivado. La aplicación puede llamar a
  `set_paper_trading(True)` solo después de que el usuario lo active explícitamente y
  luego pasar cada señal a `process_paper_signal(...)`.
- Los retiros son manuales desde Phantom u otra wallet. El bot no almacena claves ni
  envía fondos.

**Importante:** este módulo es una biblioteca aislada y requiere integración explícita
con el controlador de Telegram y el ciclo principal antes de ejecutarse. No cambies el
comando de inicio del servicio hasta integrar y probar esos puntos. Las posiciones y el
P/L simulado viven en memoria y se reinician al reiniciar el proceso.
