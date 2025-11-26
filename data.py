"""
Data access layer for Blueprint Trader AI.

Uses OANDA v20 REST API for OHLCV candles with intelligent caching
to reduce latency and API calls.
"""

import datetime as dt
from typing import List, Dict, Any, Optional

import requests

from config import OANDA_API_KEY, OANDA_API_URL, GRANULARITY_MAP
from cache import get_cache


def _oanda_headers() -> Dict[str, str]:
    if not OANDA_API_KEY:
        raise ValueError("OANDA_API_KEY not set in environment (Replit secrets).")
    return {"Authorization": f"Bearer {OANDA_API_KEY}"}


def get_ohlcv(
    instrument: str,
    timeframe: str = "D",
    count: int = 200,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles from OANDA for a given instrument and timeframe.
    
    Args:
        instrument: OANDA instrument name (e.g. EUR_USD)
        timeframe: Candle timeframe - "D", "H4", "W", "M"
        count: Number of candles to fetch
        use_cache: Whether to use caching (default True)

    Returns:
        List of candle dicts with keys: time, open, high, low, close, volume
    """
    cache = get_cache()
    
    if use_cache:
        cached = cache.get(instrument, timeframe, count)
        if cached is not None:
            return cached

    granularity = GRANULARITY_MAP.get(timeframe, timeframe)
    url = f"{OANDA_API_URL}/v3/instruments/{instrument}/candles"

    params = {
        "granularity": granularity,
        "count": count,
        "price": "M",
    }

    headers = _oanda_headers()
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[data.get_ohlcv] Network error for {instrument}, {timeframe}: {e}")
        return []
    
    if resp.status_code != 200:
        print(f"[data.get_ohlcv] Error {resp.status_code} for {instrument}, {timeframe}: {resp.text}")
        return []

    data = resp.json()
    candles = []

    for c in data.get("candles", []):
        if not c.get("complete", True):
            continue
        time_str = c["time"]
        t = time_str.split(".")[0].replace("Z", "")
        time_dt = dt.datetime.fromisoformat(t)

        mid = c["mid"]
        candles.append({
            "time": time_dt,
            "open": float(mid["o"]),
            "high": float(mid["h"]),
            "low": float(mid["l"]),
            "close": float(mid["c"]),
            "volume": float(c.get("volume", 0)),
        })

    if use_cache and candles:
        cache.set(instrument, timeframe, count, candles)

    return candles


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about the data cache."""
    return get_cache().get_stats()


def clear_cache() -> None:
    """Clear all cached data."""
    get_cache().clear()


def clear_instrument_cache(instrument: str) -> None:
    """Clear cache for a specific instrument."""
    get_cache().clear_instrument(instrument)
