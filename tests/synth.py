"""Synthetic candle generator with a known textbook SMC pattern (for tests / smoke runs)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc.utils import normalize, resample_ohlcv


def _candles(path, rng, wick=0.08, vol=1000.0):
    """path = list of close prices; each candle opens at previous close."""
    rows, prev = [], path[0]
    for c in path[1:]:
        o = prev
        hi = max(o, c) + abs(rng.normal(0, wick))
        lo = min(o, c) - abs(rng.normal(0, wick))
        rows.append((o, hi, lo, c, vol * (1 + rng.normal(0, 0.1))))
        prev = c
    return rows


def build(retrace: str = "pending", seed: int = 7, start="2026-11-02 03:45:00+00:00", reclaim: bool = True):
    """Returns (ltf_5m_df, htf_1h_df).  retrace: 'pending' | 'trigger'."""
    rng = np.random.default_rng(seed)
    # --- phase A: slow triangle wave 100..110, period 120 bars (HTF swing lows ~100)
    base = []
    for i in range(720):
        ph = (i % 120) / 120.0
        base.append(100 + 10 * (1 - abs(2 * ph - 1)) + rng.normal(0, 0.03))
    # --- phase B: fall to the pool in lower-highs, sweep, reclaim, displacement, retrace
    p = list(base)
    p += list(np.linspace(base[-1], 103.6, 12)[1:])          # drop
    p += list(np.linspace(103.6, 104.6, 5)[1:])              # bounce -> LTF swing high ~104.6 (the MSS level)
    p += list(np.linspace(104.6, 100.6, 14)[1:])             # drop again
    p += [100.9, 100.55, 100.3, 100.0]                       # grind into the pool (bearish candles = OB)
    # sweep candle added by hand below
    rows = _candles(p, rng)
    last_close = p[-1]
    # sweep candle: opens 100.0, wicks to 98.9 (pool ~99.9), closes back at 100.35 (reclaim)
    rows.append((last_close, 100.4, 98.9, 100.35 if reclaim else 99.3, 2500.0))
    # displacement leg WITH an inducement: up, up, small 2-candle pull-back (its low = IDM 101.8), up, up (MSS)
    o0 = 100.35 if reclaim else 99.3
    rows.append((o0, 102.1, 100.3, 102.0, 4200.0))            # d1
    rows.append((102.0, 103.3, 101.95, 103.2, 4400.0))         # d2
    rows.append((103.2, 103.25, 102.5, 102.6, 2000.0))         # p1 (pull-back)
    rows.append((102.6, 102.65, 101.8, 102.0, 2000.0))         # p2 -> minor swing low = IDM @101.8
    rows.append((102.0, 104.3, 101.9, 104.2, 4800.0))          # d3
    rows.append((104.2, 105.6, 104.0, 105.4, 5200.0))          # d4 closes above 104.68 => MSS (gap vs p2 = FVG)
    if retrace == "pending":
        # shallow pull-back: IDM (101.8) NOT taken yet
        rows += [(105.4, 105.5, 104.5, 104.7, 1500.0), (104.7, 104.9, 103.9, 104.1, 1400.0)]
    else:
        # pull-back that takes the IDM and trades into the order block / entry
        for c in (104.4, 103.0, 101.6, 100.9, 100.4, 100.0):
            o = rows[-1][3]
            rows.append((o, max(o, c) + 0.05, min(o, c) - 0.05, c, 1300.0))
    idx = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    ltf = normalize(pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"]))
    htf = resample_ohlcv(ltf, "1h", origin=ltf.index[0].floor("1h"))
    # HTF candles must be closed ones only
    htf = htf[(htf.index + pd.Timedelta(hours=1)) <= ltf.index[-1] + pd.Timedelta(minutes=5)]
    return ltf, htf


def mirror(df: pd.DataFrame, pivot: float = 210.0) -> pd.DataFrame:
    """Price-inverted copy -> bullish pattern becomes bearish."""
    out = df.copy()
    out["open"], out["close"] = pivot - df["open"], pivot - df["close"]
    out["high"], out["low"] = pivot - df["low"], pivot - df["high"]
    return out


def random_walk(n=4000, seed=1, start="2026-10-01 03:45:00+00:00", vol=0.25):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, vol, n))
    rows, prev = [], 100.0
    for x in c:
        hi = max(prev, x) + abs(rng.normal(0, vol / 3))
        lo = min(prev, x) - abs(rng.normal(0, vol / 3))
        rows.append((prev, hi, lo, x, 1000 * (1 + abs(rng.normal()))))
        prev = x
    idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return normalize(pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"]))
