from __future__ import annotations

import threading
import time
from collections import deque

import pandas as pd


class DataError(Exception):
    """Problem fetching/parsing candles for one symbol."""


class AuthError(DataError):
    """Token rejected (expired / invalid). Fatal for the whole provider."""


class RateLimiter:
    """Sliding-window limiter (per second, per minute, per 30 minutes), thread-safe.
    If the 30-minute budget is used up, acquire() raises DataError instead of freezing
    the scan for many minutes - the symbol is skipped and picked up in a later batch."""

    def __init__(self, per_sec: int, per_min: int, per_30min: int = 1800, max_wait: float = 90.0):
        self.per_sec, self.per_min, self.per_30 = per_sec, per_min, per_30min
        self.max_wait = max_wait
        self.sec, self.min, self.half = deque(), deque(), deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        start = time.monotonic()
        while True:
            with self.lock:
                now = time.monotonic()
                while self.sec and now - self.sec[0] > 1.0:
                    self.sec.popleft()
                while self.min and now - self.min[0] > 60.0:
                    self.min.popleft()
                while self.half and now - self.half[0] > 1800.0:
                    self.half.popleft()
                if len(self.half) >= self.per_30:
                    raise DataError("Upstox 30-min call budget used up - skipped, will retry in a later batch")
                if len(self.sec) < self.per_sec and len(self.min) < self.per_min:
                    self.sec.append(now)
                    self.min.append(now)
                    self.half.append(now)
                    return
                wait = 0.05
                if len(self.min) >= self.per_min:
                    wait = max(wait, 60.0 - (now - self.min[0]))
            if time.monotonic() - start + wait > self.max_wait:
                raise DataError("rate limiter wait too long - skipped")
            time.sleep(min(wait, 5.0))


class Provider:
    name = "base"

    def resolve(self, symbol: str):
        """Provider-specific instrument spec, or None if the symbol is unknown."""
        return symbol

    def candles(self, spec, tf: str, days: int, now: pd.Timestamp) -> pd.DataFrame:
        raise NotImplementedError

    def fetch_frames(self, spec, profile, now: pd.Timestamp) -> dict:
        raw = {
            "ltf": self.candles(spec, profile.ltf, profile.ltf_days, now),
            "htf": self.candles(spec, profile.htf, profile.htf_days, now),
        }
        if profile.use_daily:
            raw["daily"] = self.daily_context(spec, now)
        return raw

    def daily_context(self, spec, now: pd.Timestamp) -> pd.DataFrame:
        return self.candles(spec, "1d", 20, now)
