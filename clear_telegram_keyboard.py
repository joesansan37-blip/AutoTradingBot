"""One-shot utility to remove a persistent Telegram reply keyboard from a chat.

Usage: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment, then run
`python clear_telegram_keyboard.py`. The bot token is never printed.
"""

import os
import sys

import requests


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment.", file=sys.stderr)
        return 2

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "Teclado personalizado eliminado. Usa los comandos o el menú del bot.",
        "reply_markup": {"remove_keyboard": True},
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        if response.ok and data.get("ok"):
            print("Telegram reply keyboard removed for the configured chat.")
            return 0
        print(f"Telegram rejected the request: {data.get('description', 'unknown error')}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Telegram request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError:
        print("Telegram returned a non-JSON response.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
