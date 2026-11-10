"""Candle helpers: timeframe maths, resampling, closed-candle filtering.

Convention used everywhere in this project:
  * DataFrame index = candle START time, tz-aware UTC
  * columns = open, high, low, close, volume
"""
from __future__ import annotations

import pandas as pd

TF_MIN = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}
COLS = ["open", "high", "low", "close", "volume"]


def tf_minutes(tf: str) -> int:
    if tf not in TF_MIN:
        raise ValueError(f"Unsupported timeframe '{tf}'. Use one of {list(TF_MIN)}")
    return TF_MIN[tf]


def tf_delta(tf: str) -> pd.Timedelta:
    return pd.Timedelta(minutes=tf_minutes(tf))


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts"))


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case columns, UTC index, numeric, sorted, de-duplicated, no NaN rows."""
    if df is None or len(df) == 0:
        return empty_frame()
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[COLS]
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx.rename("ts")
    for c in COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0.0)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def resample_ohlcv(df: pd.DataFrame, tf: str, origin: str | pd.Timestamp = "start_day") -> pd.DataFrame:
    """Build `tf` candles from finer candles. `origin` anchors the bucket grid
    (e.g. a Timestamp of 09:15 IST for NSE-aligned hourly candles)."""
    if df.empty:
        return df
    rule = f"{tf_minutes(tf)}min"
    out = df.resample(rule, origin=origin, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open"])


def drop_unclosed(df: pd.DataFrame, tf: str, now: pd.Timestamp, session_end_fn=None) -> pd.DataFrame:
    """Remove candles that are still forming at `now`.

    A candle is closed if start+tf <= now, OR if the market session it belongs
    to has already ended (so the last 15:15-15:30 hourly candle counts as
    closed at 15:30 even though start+1h is later).
    """
    if df.empty:
        return df
    now = pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    closed = (df.index + tf_delta(tf)) <= now
    if session_end_fn is not None:
        ends = [session_end_fn(ts) for ts in df.index]
        extra = [(e is not None and now >= e) for e in ends]
        closed = closed | pd.Series(extra, index=df.index).values
    return df[closed]


def staleness_minutes(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> float:
    """Minutes between 'now' and the END of the last candle we have."""
    if df.empty:
        return float("inf")
    end = df.index[-1] + tf_delta(tf)
    return (pd.Timestamp(now) - end).total_seconds() / 60.0
