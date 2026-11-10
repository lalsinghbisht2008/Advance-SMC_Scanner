"""Persistent state: active trades + closed history (atomic JSON writes)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import STATE_DIR


def _read(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class State:
    def __init__(self, directory: Path = STATE_DIR):
        self.dir = Path(directory)
        self.active: dict = _read(self.dir / "active.json", {})
        self.history: list = _read(self.dir / "history.json", [])
        self.meta: dict = _read(self.dir / "meta.json", {})
        self._dirty = False

    def seen(self, trade_id: str) -> bool:
        return trade_id in self.active or any(h.get("id") == trade_id for h in self.history[-500:])

    def add(self, trade: dict) -> None:
        self.active[trade["id"]] = trade
        self._dirty = True

    def close(self, trade_id: str, final: dict) -> None:
        t = self.active.pop(trade_id, None)
        if t is not None:
            t.update(final)
            self.history.append(t)
            self.history = self.history[-2000:]
            self._dirty = True

    def touch(self) -> None:
        self._dirty = True

    def active_for(self, market: str, symbol: str, profile: str) -> list:
        return [t for t in self.active.values()
                if t["market"] == market and t["symbol"] == symbol and t["profile"] == profile]

    def throttle(self, key: str, seconds: int, now_ts: float) -> bool:
        """True if `key` may fire now (and records it). Used for health alerts."""
        last = self.meta.get(key, 0)
        if now_ts - last >= seconds:
            self.meta[key] = now_ts
            self._dirty = True
            return True
        return False

    def save(self) -> None:
        if not self._dirty:
            return
        _write(self.dir / "active.json", self.active)
        _write(self.dir / "history.json", self.history)
        _write(self.dir / "meta.json", self.meta)
        self._dirty = False
