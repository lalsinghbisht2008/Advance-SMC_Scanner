"""Forex / metals candles from Yahoo Finance chart API (free, no key, ~delayed by seconds).
Yahoo has no 4H candles, so 4H is built from 1H.  Yahoo limits: 5m/15m -> 60 days, 1h -> 730 days."""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from ..config import FOREX_WATCHLIST
from ..utils import normalize, resample_ohlcv
from .base import DataError, Provider

log = logging.getLogger("smc.yahoo")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = {"User-Agent": "Mozilla/5.0 (compatible; smc-scanner/2.0)"}
NATIVE = {"1m": ("1m", 5), "5m": ("5m", 58), "15m": ("15m", 58), "30m": ("30m", 58),
          "1h": ("60m", 700), "1d": ("1d", 1500)}


def parse_chart(payload: dict) -> pd.DataFrame:
    res = (payload.get("chart") or {}).get("result")
    if not res:
        err = (payload.get("chart") or {}).get("error")
        raise DataError(f"Yahoo returned no data: {err}")
    r = res[0]
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    if not ts or not q:
        return normalize(None)
    df = pd.DataFrame({k: q.get(k) for k in ("open", "high", "low", "close", "volume")})
    df.index = pd.to_datetime(ts, unit="s", utc=True)
    return normalize(df)


class YahooProvider(Provider):
    name = "yahoo"

    def __init__(self, http=None):
        self.http = http or requests

    def resolve(self, symbol: str):
        return FOREX_WATCHLIST.get(symbol)

    def _fetch(self, ysym: str, interval: str, days: int) -> pd.DataFrame:
        url = URL.format(sym=ysym)
        for attempt in range(3):
            try:
                r = self.http.get(url, params={"interval": interval, "range": f"{days}d"},
                                  headers=UA, timeout=20)
            except requests.RequestException as e:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200:
                return parse_chart(r.json())
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise DataError(f"Yahoo HTTP {r.status_code}")
        raise DataError("Yahoo unreachable / rate-limited")

    def candles(self, ysym: str, tf: str, days: int, now: pd.Timestamp) -> pd.DataFrame:
        if tf == "4h":
            return resample_ohlcv(self._fetch(ysym, "60m", min(days, 700)), "4h")
        if tf not in NATIVE:
            raise DataError(f"timeframe {tf} not supported for Yahoo")
        interval, cap = NATIVE[tf]
        return self._fetch(ysym, interval, min(days, cap))
