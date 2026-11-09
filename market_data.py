"""Public-only OHLCV feed with shared cache and conservative rate-limit handling."""

import logging
import threading
import time

import ccxt


class MarketDataFeed:
    def __init__(self, exchange, symbol, timeframe, cache_seconds=60, limit=100):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.cache_seconds = max(30, int(cache_seconds))
        self.limit = limit
        self._lock = threading.RLock()
        self._candles = None
        self._fetched_at = 0.0

    @staticmethod
    def _is_rate_limit_error(exc):
        return (
            isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection))
            or "too many requests" in str(exc).lower()
            or "rate limit" in str(exc).lower()
            or "429" in str(exc)
        )

    def fetch_candles(self):
        """Share one OHLCV request between the loop and Telegram radar.

        Return a cached snapshot during the TTL. On rate limit errors, use stale cached
        candles rather than repeatedly hitting the public endpoint.
        """
        with self._lock:
            now = time.monotonic()
            if self._candles and now - self._fetched_at < self.cache_seconds:
                return [list(row) for row in self._candles]

            for attempt, delay in enumerate((0, 15), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    candles = self.exchange.fetch_ohlcv(
                        self.symbol, timeframe=self.timeframe, limit=self.limit
                    )
                    if not candles:
                        raise RuntimeError("Market data venue returned no candles")
                    self._candles = [list(row) for row in candles]
                    self._fetched_at = time.monotonic()
                    return [list(row) for row in self._candles]
                except Exception as exc:
                    if self._is_rate_limit_error(exc):
                        logging.warning(
                            "Market data rate-limited by %s (attempt %s); backing off",
                            getattr(self.exchange, "id", "exchange"), attempt,
                        )
                        if self._candles:
                            logging.warning("Using cached OHLCV snapshot after rate limit")
                            return [list(row) for row in self._candles]
                        if attempt < 2:
                            continue
                    raise

            raise RuntimeError("Could not retrieve market candles")
