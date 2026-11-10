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
    """Sliding-window limiter (per second + per minute), thread-safe."""

    def __init__(self, per_sec: int, per_min: int):
        self.per_sec, self.per_min = per_sec, per_min
        self.sec, self.min = deque(), deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.sec and now - self.sec[0] > 1.0:
                    self.sec.popleft()
                while self.min and now - self.min[0] > 60.0:
                    self.min.popleft()
                if len(self.sec) < self.per_sec and len(self.min) < self.per_min:
                    self.sec.append(now)
                    self.min.append(now)
                    return
                wait = 0.05
                if len(self.min) >= self.per_min:
                    wait = max(wait, 60.0 - (now - self.min[0]))
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
            raw["daily"] = self.candles(spec, "1d", 20, now)
        return raw
