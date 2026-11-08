"""Safe, read-only Solana deposit monitoring and paper-trading helpers.

This module never signs or broadcasts transactions. Real funds movement is deliberately
out of scope: withdrawals must be initiated and confirmed by the wallet owner.
"""

import logging
import os
import threading
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
SOLANA_WALLET_ADDRESS = os.getenv("SOLANA_WALLET_ADDRESS", "").strip()
SOLANA_POLL_SECONDS = max(30, int(os.getenv("SOLANA_POLL_SECONDS", "60")))

# Paper trading is disabled by default and has no access to exchange or wallet credentials.
_paper_lock = threading.RLock()
_paper_enabled = False
_paper_positions = {}
_paper_realized_pnl = 0.0
_paper_pnl_day = date.today()


def start_deposit_monitor(send_message):
    """Start a read-only SOL deposit monitor. Requires the user's public address.

    Reports new transactions with positive native-SOL balance changes. It does not
    monitor SPL-token deposits or move funds. Existing signatures are baselined on
    startup to avoid sending historical notifications.
    """
    if not SOLANA_WALLET_ADDRESS:
        logger.info("Solana monitor disabled: set SOLANA_WALLET_ADDRESS to a public address.")
        return None

    def rpc(method, params):
        response = requests.post(
            SOLANA_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result")

    def worker():
        seen = set()
        initialized = False
        while True:
            try:
                signatures = rpc("getSignaturesForAddress", [SOLANA_WALLET_ADDRESS, {"limit": 20}]) or []
                if not initialized:
                    seen.update(item.get("signature") for item in signatures if item.get("signature"))
                    initialized = True
                else:
                    for item in reversed(signatures):
                        signature = item.get("signature")
                        if not signature or signature in seen:
                            continue
                        seen.add(signature)
                        if item.get("err"):
                            continue
                        tx = rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
                        if not tx:
                            continue
                        meta = tx.get("meta") or {}
                        message = ((tx.get("transaction") or {}).get("message") or {})
                        keys = message.get("accountKeys") or []
                        addresses = [key if isinstance(key, str) else key.get("pubkey") for key in keys]
                        try:
                            wallet_index = addresses.index(SOLANA_WALLET_ADDRESS)
                            pre = (meta.get("preBalances") or [])[wallet_index]
                            post = (meta.get("postBalances") or [])[wallet_index]
                        except (ValueError, IndexError, TypeError):
                            continue
                        delta_lamports = post - pre
                        if delta_lamports > 0:
                            sol_amount = delta_lamports / 1_000_000_000
                            send_message(
                                "📥 Actividad entrante de SOL detectada (solo lectura).\n"
                                f"Importe neto aproximado: {sol_amount:.9f} SOL\n"
                                f"Transacción: https://explorer.solana.com/tx/{signature}\n"
                                "No se detectan depósitos SPL; comprueba la transacción en un explorador."
                            )
                    # Bound memory; newer signatures are returned first.
                    if len(seen) > 500:
                        seen = {item.get("signature") for item in signatures if item.get("signature")}
            except Exception as exc:
                logger.warning("Solana deposit monitor error: %s", exc)
            time.sleep(SOLANA_POLL_SECONDS)

    thread = threading.Thread(target=worker, name="solana-deposit-monitor", daemon=True)
    thread.start()
    return thread


def set_paper_trading(enabled: bool) -> None:
    """Explicitly enable/disable local paper trading; this never places real orders."""
    global _paper_enabled
    with _paper_lock:
        _paper_enabled = bool(enabled)


def paper_trading_enabled() -> bool:
    with _paper_lock:
        return _paper_enabled


def paper_positions_snapshot() -> dict:
    with _paper_lock:
        return {symbol: position.copy() for symbol, position in _paper_positions.items()}


def process_paper_signal(signal: dict, order_size_usdt: float, stop_loss_pct: float,
                         take_profit_pct: float, send_message) -> None:
    """Open/close simulated long/short positions using price signals and SL/TP.

    Signals should contain symbol, close, buy, and sell. No exchange order API is called.
    A daily simulated loss cap uses MAX_DAILY_LOSS_USDT and blocks new entries.
    """
    global _paper_realized_pnl, _paper_pnl_day
    today = date.today()
    with _paper_lock:
        if today != _paper_pnl_day:
            _paper_pnl_day = today
            _paper_realized_pnl = 0.0
        if not _paper_enabled:
            return

        symbol = signal["symbol"]
        price = float(signal["close"])
        existing = _paper_positions.get(symbol)
        close_reason = None
        if existing:
            side = existing["side"]
            stop_hit = price <= existing["sl"] if side == "BUY" else price >= existing["sl"]
            target_hit = price >= existing["tp"] if side == "BUY" else price <= existing["tp"]
            opposite_signal = signal.get("sell") if side == "BUY" else signal.get("buy")
            if stop_hit:
                close_reason = "stop loss simulado"
            elif target_hit:
                close_reason = "take profit simulado"
            elif opposite_signal:
                close_reason = "señal opuesta"

            if close_reason:
                direction = 1 if side == "BUY" else -1
                pnl = (price - existing["entry"]) * existing["amount"] * direction
                _paper_realized_pnl += pnl
                del _paper_positions[symbol]
                send_message(
                    f"🧪 Cierre de posición SIMULADA: {symbol} ({close_reason}).\n"
                    f"Salida: {price:.8f} | P/L estimado: {pnl:.2f} USDT\n"
                    f"P/L simulado diario: {_paper_realized_pnl:.2f} USDT"
                )
            return

        daily_loss_cap = max(0.0, float(os.getenv("MAX_DAILY_LOSS_USDT", "50")))
        if _paper_realized_pnl <= -daily_loss_cap:
            return
        if signal.get("buy") or signal.get("sell"):
            side = "BUY" if signal.get("buy") else "SELL"
            amount = max(0.0, float(order_size_usdt)) / price if price > 0 else 0.0
            if amount <= 0:
                return
            if side == "BUY":
                sl = price * (1 - float(stop_loss_pct) / 100)
                tp = price * (1 + float(take_profit_pct) / 100)
            else:
                sl = price * (1 + float(stop_loss_pct) / 100)
                tp = price * (1 - float(take_profit_pct) / 100)
            _paper_positions[symbol] = {"side": side, "entry": price, "amount": amount, "sl": sl, "tp": tp}
            send_message(
                f"🧪 Apertura SIMULADA {side}: {symbol} a {price:.8f}. "
                f"Tamaño nocional: {float(order_size_usdt):.2f} USDT. "
                f"SL/TP simulados: {sl:.8f} / {tp:.8f}. No se envió ninguna orden real."
            )


def manual_withdrawal_notice() -> str:
    """Explain the safe manual-only withdrawal path; deliberately does not transfer funds."""
    return (
        "🔐 Los retiros no se ejecutan desde este bot. Abre tu wallet Solana, "
        "verifica dirección, red e importe y confirma allí la transacción. "
        "Nunca compartas aquí tu frase semilla ni clave privada."
    )
