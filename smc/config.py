"""All settings in one place (no secrets here - secrets come from env / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
CACHE_DIR = ROOT / ".cache"


def load_env(path: Path = ROOT / ".env") -> None:
    """Tiny .env loader (KEY=VALUE per line). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()


def env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


# --------------------------------------------------------------------------- markets
@dataclass
class Market:
    name: str
    provider: str                      # upstox | binance | yahoo
    tz: str
    symbols: list
    kind: str = "24x7"                 # session | 24x7 | fx
    open_t: Optional[time] = None
    close_t: Optional[time] = None
    weekdays: tuple = (0, 1, 2, 3, 4)
    killzones: list = field(default_factory=list)   # [(time, time)] in market tz
    no_new_after: Optional[time] = None             # no fresh alerts after this local time
    same_session: bool = False                      # setup only valid on its own trading day
    eod_exit: bool = False                          # intraday square-off at session end
    grace_min: int = 7
    label: str = ""

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def local(self, ts: pd.Timestamp) -> pd.Timestamp:
        ts = pd.Timestamp(ts)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        return ts.tz_convert(self.zone)

    def session_end(self, ts: pd.Timestamp) -> Optional[pd.Timestamp]:
        if self.kind != "session" or self.close_t is None:
            return None
        d = self.local(ts).date()
        end = pd.Timestamp.combine(pd.Timestamp(d), self.close_t).tz_localize(self.zone)
        return end.tz_convert("UTC")

    def is_open(self, now: pd.Timestamp) -> bool:
        loc = self.local(now)
        if self.kind == "24x7":
            return True
        if self.kind == "fx":
            u = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
            wd, hh = u.weekday(), u.hour + u.minute / 60
            return (wd in (0, 1, 2, 3)) or (wd == 4 and hh < 22) or (wd == 6 and hh >= 22)
        if loc.weekday() not in self.weekdays:
            return False
        start = pd.Timestamp.combine(loc.normalize(), self.open_t).tz_localize(self.zone)
        end = pd.Timestamp.combine(loc.normalize(), self.close_t).tz_localize(self.zone)
        return start <= loc <= end + pd.Timedelta(minutes=self.grace_min)

    def in_killzone(self, ts: pd.Timestamp) -> bool:
        t = self.local(ts).time()
        return any(a <= t < b for a, b in self.killzones)

    def eod_flags(self, index: pd.DatetimeIndex, tf_delta: pd.Timedelta):
        import numpy as np
        if self.kind != "session" or not self.eod_exit:
            return None
        return np.array([(self.session_end(ts) is not None and ts + tf_delta >= self.session_end(ts))
                         for ts in index])


INDEX_KEYS = {  # Upstox index instrument keys
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "SENSEX": "BSE_INDEX|SENSEX",
}
OPTION_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "SENSEX": 100}

INDIA_WATCHLIST = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX",
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC",
    "KOTAKBANK", "LT", "AXISBANK", "HINDUNILVR", "MARUTI", "SUNPHARMA", "TITAN",
    "BAJFINANCE", "ADANIENT", "TATASTEEL", "WIPRO", "HCLTECH", "NTPC", "POWERGRID",
    "M&M", "ONGC", "JSWSTEEL", "COALINDIA", "BAJAJFINSV", "TECHM", "ADANIPORTS",
    "DRREDDY", "CIPLA", "BPCL", "EICHERMOT", "HINDALCO", "INDUSINDBK", "SHRIRAMFIN",
    "ETERNAL", "BEL", "HAL", "DLF", "VEDL", "SAIL", "PNB", "BANKBARODA", "CANBK",
    "IDFCFIRSTB", "YESBANK", "TATAPOWER", "LUPIN", "DIXON", "POLYCAB", "JINDALSTEL",
    "GAIL", "IOC", "NMDC", "RVNL", "IRFC", "NHPC", "SUZLON", "OLAELEC", "BALRAMCHIN",
]
MCX_WATCHLIST = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]
CRYPTO_WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
FOREX_WATCHLIST = {   # display name -> Yahoo symbol
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "AUDUSD": "AUDUSD=X",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
}

MARKETS = {
    "india": Market(
        name="india", label="NSE/BSE", provider="upstox", tz="Asia/Kolkata", symbols=INDIA_WATCHLIST,
        kind="session", open_t=time(9, 15), close_t=time(15, 30),
        killzones=[(time(9, 20), time(11, 30)), (time(13, 30), time(15, 0))],
        no_new_after=time(15, 0), same_session=True, eod_exit=True),
    "mcx": Market(
        name="mcx", label="MCX", provider="upstox", tz="Asia/Kolkata", symbols=MCX_WATCHLIST,
        kind="session", open_t=time(9, 0), close_t=time(23, 30),
        killzones=[(time(9, 30), time(12, 0)), (time(18, 30), time(22, 30))],
        no_new_after=time(23, 0), same_session=True, eod_exit=True),
    "crypto": Market(
        name="crypto", label="Crypto", provider="binance", tz="UTC", symbols=CRYPTO_WATCHLIST,
        kind="24x7", killzones=[(time(7, 0), time(10, 0)), (time(12, 30), time(15, 30))]),
    "forex": Market(
        name="forex", label="Forex/Metals", provider="yahoo", tz="UTC", symbols=list(FOREX_WATCHLIST),
        kind="fx", killzones=[(time(7, 0), time(10, 0)), (time(12, 0), time(15, 0))]),
}


# --------------------------------------------------------------------------- profiles
@dataclass
class Profile:
    name: str
    htf: str
    ltf: str
    ltf_days: int
    htf_days: int
    use_daily: bool = True
    description: str = ""


PROFILES = {
    "5m": Profile("5m", htf="1h", ltf="5m", ltf_days=7, htf_days=35,
                  description="Intraday: 1H liquidity -> 5M execution"),
    "15m": Profile("15m", htf="4h", ltf="15m", ltf_days=14, htf_days=90,
                   description="Intraday/BTST: 4H liquidity -> 15M execution"),
    "swing": Profile("swing", htf="1d", ltf="1h", ltf_days=60, htf_days=400, use_daily=False,
                     description="Swing: Daily liquidity -> 1H execution"),
}
DEFAULT_PROFILES = {"india": ["5m"], "mcx": ["5m"], "crypto": ["5m"], "forex": ["5m"]}

# --------------------------------------------------------------------------- misc
SCAN_WORKERS = 4
STALE_FACTOR = 4          # data older than 4 x LTF candles while market open = stale
UPSTOX_MAX_PER_SEC = 8
UPSTOX_MAX_PER_MIN = 350  # API limit is 500/min - keep head-room
ALERT_PENDING = True      # also alert "setup formed, waiting for retrace" (not only fills)
MAX_ACTIVE_PER_SYMBOL = 2
