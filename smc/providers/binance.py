"""Crypto candles from Binance public market-data endpoints (no API key needed).
`data-api.binance.vision` is tried first because api.binance.com refuses US IPs
(GitHub Actions runners) with HTTP 451."""
from __future__ import annotations

import logging

import pandas as pd
import requests

from ..utils import normalize, tf_minutes
from .base import DataError, Provider

log = logging.getLogger("smc.binance")
HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com",
         "https://api.binance.us"]
INTERVAL = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h",
            "4h": "4h", "1d": "1d"}


def parse_klines(rows: list) -> pd.DataFrame:
    if not rows:
        return normalize(None)
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.pop("ts").astype("int64"), unit="ms", utc=True)
    return normalize(df)


class BinanceProvider(Provider):
    name = "binance"

    def __init__(self, http=None):
        self.http = http or requests
        self.host_idx = 0
        self.max_bars = 1000          # live scanning needs one page only; backtest raises this

    def _page(self, params: dict) -> list:
        last = ""
        for off in range(len(HOSTS)):
            host = HOSTS[(self.host_idx + off) % len(HOSTS)]
            try:
                r = self.http.get(f"{host}/api/v3/klines", params=params, timeout=15)
            except requests.RequestException as e:
                last = type(e).__name__
                continue
            if r.status_code == 200:
                self.host_idx = (self.host_idx + off) % len(HOSTS)
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code == 400:          # bad symbol - same on every host
                raise DataError(f"Binance rejected {params.get('symbol')}: {r.text[:100]}")
        raise DataError(f"Binance unreachable ({last})")

    def candles(self, symbol: str, tf: str, days: int, now: pd.Timestamp) -> pd.DataFrame:
        want = int(max(50, days * 1440 / tf_minutes(tf)))
        rows, end = [], None
        while len(rows) < want:                       # page backwards, 1000 candles per call
            params = {"symbol": symbol, "interval": INTERVAL[tf], "limit": min(1000, want - len(rows))}
            if end is not None:
                params["endTime"] = end
            page = self._page(params)
            if not page:
                break
            rows = page + rows
            end = int(page[0][0]) - 1
            if len(page) < params["limit"] or len(rows) >= self.max_bars:
                break
        return parse_klines(rows)
