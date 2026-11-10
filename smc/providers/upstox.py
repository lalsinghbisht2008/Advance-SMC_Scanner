"""Upstox API V3 candles (native timeframes) = historical (past days) + intraday (today).

Docs used:
  GET /v3/historical-candle/{key}/{unit}/{interval}/{to_date}/{from_date}
  GET /v3/historical-candle/intraday/{key}/{unit}/{interval}        <- current trading day only
  unit: minutes(1-300) | hours(1-5) | days(1);  candle = [ts, o, h, l, c, vol, oi]
  limits: minutes 1-15 => 1 month per call; >15min & hours => 1 quarter; days => 10 years
  rate limit: 50/s, 500/min, 2000/30min  (we stay far below)
The 1-year *Analytics Token* works for these (read-only market data) endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests

from ..config import CACHE_DIR, UPSTOX_MAX_PER_MIN, UPSTOX_MAX_PER_SEC, env
from ..utils import normalize, empty_frame
from .base import AuthError, DataError, Provider, RateLimiter
from .instruments import InstrumentResolver

log = logging.getLogger("smc.upstox")
BASE = "https://api.upstox.com/v3/historical-candle"

UNIT = {"1m": ("minutes", 1), "3m": ("minutes", 3), "5m": ("minutes", 5), "15m": ("minutes", 15),
        "30m": ("minutes", 30), "1h": ("hours", 1), "2h": ("hours", 2), "4h": ("hours", 4),
        "1d": ("days", 1)}


def token_days_left(token: str) -> Optional[float]:
    """Days until the (JWT) token expires, or None if it can't be read."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return (exp - time.time()) / 86400.0
    except Exception:
        return None


def parse_candles(payload: dict) -> pd.DataFrame:
    candles = (payload.get("data") or {}).get("candles") or []
    if not candles:
        return empty_frame()
    df = pd.DataFrame(candles).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    ts = df.pop("ts")
    if pd.api.types.is_numeric_dtype(ts):
        idx = pd.to_datetime(ts, unit="ms", utc=True)
    else:
        idx = pd.to_datetime(ts, utc=True)
    df.index = pd.DatetimeIndex(idx)
    return normalize(df)


class UpstoxProvider(Provider):
    name = "upstox"

    def __init__(self, token: str = "", http=None, limiter: RateLimiter | None = None,
                 resolver: InstrumentResolver | None = None, cache_dir: Path = CACHE_DIR, market: str = "india"):
        self.token = token or env("UPSTOX_ACCESS_TOKEN", "UPSTOX_ANALYTICS_TOKEN")
        self.http = http or requests
        self.limiter = limiter or RateLimiter(UPSTOX_MAX_PER_SEC, UPSTOX_MAX_PER_MIN)
        self.resolver = resolver or InstrumentResolver(self.http, cache_dir)
        self.cache_dir = Path(cache_dir)
        self.market = market
        self.calls = 0

    # ---- instruments ---------------------------------------------------------------
    def resolve(self, symbol: str):
        return self.resolver.resolve(symbol, self.market)

    # ---- http ------------------------------------------------------------------------
    def _get(self, url: str) -> dict:
        if not self.token:
            raise AuthError("UPSTOX_ACCESS_TOKEN not set")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        last = ""
        for attempt in range(4):
            self.limiter.acquire()
            self.calls += 1
            try:
                r = self.http.get(url, headers=headers, timeout=20)
            except requests.RequestException as e:
                last = type(e).__name__
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                raise AuthError("Upstox token rejected (401) - expired or invalid")
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2.0 * (attempt + 1))
                continue
            try:
                msg = r.json().get("errors", [{}])[0].get("message", r.text[:150])
            except Exception:
                msg = r.text[:150]
            raise DataError(f"HTTP {r.status_code}: {msg}")
        raise DataError(f"Upstox request failed after retries ({last})")

    # ---- candles -----------------------------------------------------------------------
    def _history(self, key: str, tf: str, start, end) -> pd.DataFrame:
        unit, itv = UNIT[tf]
        span = 3650 if unit == "days" else (28 if unit == "minutes" and itv <= 15 else 85)
        parts, cur = [], start
        while cur <= end:
            chunk_end = min(end, cur + timedelta(days=span - 1))
            parts.append(self._history_call(key, unit, itv, cur, chunk_end))
            cur = chunk_end + timedelta(days=1)
        parts = [p for p in parts if not p.empty]
        return normalize(pd.concat(parts)) if parts else empty_frame()

    def _history_call(self, key, unit, itv, start, end) -> pd.DataFrame:
        url = f"{BASE}/{quote(key, safe='')}/{unit}/{itv}/{end:%Y-%m-%d}/{start:%Y-%m-%d}"
        cache = self.cache_dir / ("up_" + hashlib.md5(url.encode()).hexdigest() + ".json")
        today = pd.Timestamp.now(tz="Asia/Kolkata").date()
        immutable = end < today                      # past days never change
        if immutable and cache.exists():
            return parse_candles(json.loads(cache.read_text()))
        payload = self._get(url)
        if immutable:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload))
        return parse_candles(payload)

    def _intraday(self, key: str, tf: str) -> pd.DataFrame:
        unit, itv = UNIT[tf]
        return parse_candles(self._get(f"{BASE}/intraday/{quote(key, safe='')}/{unit}/{itv}"))

    def daily_context(self, key: str, now: pd.Timestamp) -> pd.DataFrame:
        """Completed daily candles only (up to yesterday) -> immutable -> cached for the whole day."""
        today = pd.Timestamp(now).tz_convert("Asia/Kolkata").date()
        return self._history(key, "1d", today - timedelta(days=20), today - timedelta(days=1))

    def candles(self, key: str, tf: str, days: int, now: pd.Timestamp) -> pd.DataFrame:
        if tf not in UNIT:
            raise DataError(f"timeframe {tf} not supported by Upstox mapping")
        today = pd.Timestamp(now).tz_convert("Asia/Kolkata").date()
        if tf == "1d":
            return self._history(key, tf, today - timedelta(days=days), today)
        hist = self._history(key, tf, today - timedelta(days=days), today - timedelta(days=1))
        live = self._intraday(key, tf)
        if hist.empty and live.empty:
            raise DataError("no candles returned")
        return normalize(pd.concat([hist, live]))
