"""Paper-only SOL perpetual futures simulator; no exchange orders are submitted."""

import json
import os
import threading
from datetime import datetime, timezone


class PaperFutures:
    """Persistent paper account for a linear USDT-margined contract."""

    def __init__(self, state_path, starting_balance, leverage, fee_rate, stop_loss_pct,
                 take_profit_pct, max_daily_loss):
        self.path = state_path
        self.starting_balance = float(starting_balance)
        self.leverage = int(leverage)
        self.fee_rate = float(fee_rate)
        self.stop_loss_pct = float(stop_loss_pct) / 100
        self.take_profit_pct = float(take_profit_pct) / 100
        self.max_daily_loss = float(max_daily_loss)
        self.lock = threading.RLock()
        self.state = self._load()

    def _new_state(self):
        return {"available": self.starting_balance, "positions": {}, "closed_trades": [],
                "daily_realized": 0.0, "daily_date": datetime.now(timezone.utc).date().isoformat()}

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            if not isinstance(state.get("positions"), dict) or "available" not in state:
                raise ValueError("Invalid paper account state")
            return state
        except FileNotFoundError:
            return self._new_state()
        except Exception as exc:
            raise RuntimeError(f"Cannot load paper account {self.path}: {exc}") from exc

    def _save(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self.path)

    def _roll_day(self):
        today = datetime.now(timezone.utc).date().isoformat()
        if self.state.get("daily_date") != today:
            self.state["daily_date"] = today
            self.state["daily_realized"] = 0.0

    def open_position(self, symbol, side, price, margin, stop_loss=None, take_profit=None):
        with self.lock:
            self._roll_day()
            side = side.upper()
            price, margin = float(price), float(margin)
            if side not in ("LONG", "SHORT") or price <= 0 or margin <= 0:
                raise ValueError("Side must be LONG/SHORT and price/margin must be positive")
            if symbol in self.state["positions"]:
                raise ValueError(f"A position for {symbol} is already open")
            if self.state["daily_realized"] <= -self.max_daily_loss:
                raise ValueError("Daily realized-loss limit reached; no new paper positions allowed")
            notional = margin * self.leverage
            entry_fee = notional * self.fee_rate
            required = margin + entry_fee
            if required > self.state["available"]:
                raise ValueError("Insufficient paper balance for margin plus entry fee")
            qty = notional / price
            default_sl = price * (1 - self.stop_loss_pct if side == "LONG" else 1 + self.stop_loss_pct)
            default_tp = price * (1 + self.take_profit_pct if side == "LONG" else 1 - self.take_profit_pct)
            sl = float(stop_loss) if stop_loss is not None else default_sl
            tp = float(take_profit) if take_profit is not None else default_tp
            if side == "LONG" and not (0 < sl < price < tp):
                raise ValueError("LONG stop/target must satisfy 0 < stop < entry < target")
            if side == "SHORT" and not (0 < tp < price < sl):
                raise ValueError("SHORT stop/target must satisfy 0 < target < entry < stop")
            position = {"symbol": symbol, "side": side, "entry": price, "quantity": qty,
                        "margin": margin, "notional": notional, "entry_fee": entry_fee,
                        "stop_loss": sl, "take_profit": tp,
                        "opened_at": datetime.now(timezone.utc).isoformat()}
            self.state["available"] -= required
            self.state["positions"][symbol] = position
            self._save()
            return dict(position)

    def update_trailing_stop(self, symbol, price, atr, breakeven_atr=1.0, trailing_atr=1.5):
        """Move paper stop to break-even and then trail by ATR, only in risk-reducing direction."""
        with self.lock:
            position = self.state["positions"].get(symbol)
            price, atr = float(price), float(atr)
            if not position or price <= 0 or atr <= 0:
                return False
            entry, old_stop = position["entry"], position["stop_loss"]
            if position["side"] == "LONG":
                candidate = old_stop
                if price >= entry + atr * breakeven_atr:
                    candidate = max(candidate, entry * (1 + 1e-8))
                if price >= entry + atr * trailing_atr:
                    candidate = max(candidate, price - atr * trailing_atr)
                candidate = min(candidate, price * (1 - 1e-8))
                changed = candidate > old_stop
            else:
                candidate = old_stop
                if price <= entry - atr * breakeven_atr:
                    candidate = min(candidate, entry * (1 - 1e-8))
                if price <= entry - atr * trailing_atr:
                    candidate = min(candidate, price + atr * trailing_atr)
                candidate = max(candidate, price * (1 + 1e-8))
                changed = candidate < old_stop
            if changed:
                position["stop_loss"] = candidate
                self._save()
            return changed

    def close_position(self, symbol, price, reason="manual"):
        with self.lock:
            position = self.state["positions"].get(symbol)
            if not position:
                return None
            price = float(price)
            if price <= 0:
                raise ValueError("Closing price must be positive")
            direction = 1 if position["side"] == "LONG" else -1
            gross = (price - position["entry"]) * position["quantity"] * direction
            exit_fee = price * position["quantity"] * self.fee_rate
            net = gross - position["entry_fee"] - exit_fee
            self.state["available"] += position["margin"] + gross - exit_fee
            self.state["daily_realized"] += net
            trade = {**position, "exit": price, "gross_pnl": gross, "exit_fee": exit_fee,
                     "net_pnl": net, "reason": reason,
                     "closed_at": datetime.now(timezone.utc).isoformat()}
            self.state["closed_trades"].append(trade)
            self.state["closed_trades"] = self.state["closed_trades"][-500:]
            del self.state["positions"][symbol]
            self._save()
            return trade

    def check_exit(self, symbol, high, low, last_price):
        """Check candle barriers; if both hit in one candle, conservatively use the stop."""
        with self.lock:
            position = self.state["positions"].get(symbol)
            if not position:
                return None
            if position["side"] == "LONG":
                if float(low) <= position["stop_loss"]:
                    return self.close_position(symbol, position["stop_loss"], "stop_loss")
                if float(high) >= position["take_profit"]:
                    return self.close_position(symbol, position["take_profit"], "take_profit")
            else:
                if float(high) >= position["stop_loss"]:
                    return self.close_position(symbol, position["stop_loss"], "stop_loss")
                if float(low) <= position["take_profit"]:
                    return self.close_position(symbol, position["take_profit"], "take_profit")
            return None

    def close_all(self, prices):
        closed = []
        for symbol in list(self.state["positions"]):
            price = prices.get(symbol)
            if price is not None:
                trade = self.close_position(symbol, price, "panic_close")
                if trade:
                    closed.append(trade)
        return closed

    def snapshot(self, prices=None):
        with self.lock:
            self._roll_day()
            prices = prices or {}
            positions, unrealized, used_margin = [], 0.0, 0.0
            for symbol, position in self.state["positions"].items():
                mark = float(prices.get(symbol, position["entry"]))
                direction = 1 if position["side"] == "LONG" else -1
                pnl = (mark - position["entry"]) * position["quantity"] * direction
                unrealized += pnl
                used_margin += position["margin"]
                positions.append({**position, "mark": mark, "unrealized_pnl": pnl})
            equity = self.state["available"] + used_margin + unrealized
            return {"available": self.state["available"], "equity": equity,
                    "unrealized_pnl": unrealized, "daily_realized": self.state["daily_realized"],
                    "positions": positions, "closed_trades": len(self.state["closed_trades"])}
