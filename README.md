## Despliegue manual como Render Web Service

1. En Render, elige **New + → Web Service** y conecta `joesansan37-blip/AutoTradingBot`.
2. Selecciona la rama `feature/strategy-enhancements` (o la rama que contenga estos cambios).
3. Configura **Runtime: Python**; no elijas Docker para este flujo.
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `python main.py`
6. **Health Check Path:** `/healthz`
7. Añade variables del README, especialmente `EXECUTION_MODE=paper`, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. No introduzcas API keys de exchanges. Render asigna `PORT`; no necesitas configurarlo manualmente.
8. Despliega y comprueba Logs, que el deploy esté Live y la URL del servicio responda en `/healthz`. Luego abre el bot en Telegram y envía `/panel`.

Para mantener `paper_account.json` entre reinicios/despliegues, adjunta un Persistent Disk en Render (disponibilidad según plan), por ejemplo con mount path `/var/data`, y configura `PAPER_STATE_FILE=/var/data/paper_account.json`. Sin disco persistente se puede reiniciar el ledger local. Un Web Service gratuito puede dormir cuando está inactivo; para proceso continuo elige un plan/servicio que no se suspenda.

El repositorio también incluye un Dockerfile, pero para la configuración manual indicada arriba se selecciona Runtime Python y se usan los comandos Build/Start anteriores.
