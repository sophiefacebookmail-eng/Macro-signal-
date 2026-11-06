import asyncio
import time
from datetime import datetime, timezone
import aiohttp

class TwelveDataClient:
    """Serializes requests and spaces them to stay below the configured per-minute credit limit."""
    BASE_URL = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key, spacing_seconds=9, retry_wait_seconds=65):
        self.api_key = api_key
        self.spacing = max(8.5, float(spacing_seconds))
        self.retry_wait = max(60, int(retry_wait_seconds))
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._session = None
        self._cache = {}

    async def start(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _one_request(self, params):
        await self.start()
        async with self._lock:
            wait = self.spacing - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
            # API key is sent as a query parameter, but request URLs are never logged.
            async with self._session.get(self.BASE_URL, params=params) as response:
                payload = await response.json(content_type=None)
                if response.status == 429:
                    raise RateLimitError(str(payload.get("message", "HTTP 429 rate limit")))
                if response.status >= 400:
                    raise RuntimeError(f"Twelve Data HTTP {response.status}: {payload.get('message', 'request failed')}")
                if isinstance(payload, dict) and payload.get("status") == "error":
                    message = str(payload.get("message", "Twelve Data returned an error"))
                    if "credit" in message.lower() or "limit" in message.lower():
                        raise RateLimitError(message)
                    raise RuntimeError(message)
                return payload

    async def candles(self, symbol, interval="15min", outputsize=250):
        key = (symbol, interval, outputsize)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 45:
            return cached[1]

        params = {
            "symbol": symbol, "interval": interval, "outputsize": outputsize,
            "apikey": self.api_key, "timezone": "UTC", "format": "JSON"
        }
        try:
            payload = await self._one_request(params)
        except RateLimitError:
            # Wait for the provider's minute window to reset, then retry once.
            await asyncio.sleep(self.retry_wait)
            payload = await self._one_request(params)

        values = payload.get("values") if isinstance(payload, dict) else None
        if not values:
            raise RuntimeError(f"No candle data returned for {symbol}: {payload.get('message', 'empty response')}")
        candles = []
        for item in reversed(values):
            stamp = item.get("datetime")
            try:
                dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                epoch = int(dt.timestamp())
                candles.append({
                    "timestamp": epoch,
                    "open": float(item["open"]), "high": float(item["high"]),
                    "low": float(item["low"]), "close": float(item["close"]),
                    "volume": float(item.get("volume") or 0)
                })
            except (TypeError, ValueError, KeyError):
                continue
        if len(candles) < 202:
            raise RuntimeError(f"Insufficient candles for {symbol}: received {len(candles)}, need at least 202")
        self._cache[key] = (time.monotonic(), candles)
        return candles

class RateLimitError(RuntimeError):
    pass
