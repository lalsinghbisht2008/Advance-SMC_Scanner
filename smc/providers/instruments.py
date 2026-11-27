"""Resolve readable symbols (RELIANCE, GOLD ...) to Upstox instrument keys using the
official instrument master, so no ISIN/expiry has to be hard-coded or maintained."""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from ..config import CACHE_DIR, INDEX_KEYS

log = logging.getLogger("smc.instruments")
URL = "https://assets.upstox.com/market-quote/instruments/exchange/{}.json.gz"


class InstrumentResolver:
    def __init__(self, http=None, cache_dir: Path = CACHE_DIR):
        self.http = http or requests
        self.cache_dir = Path(cache_dir)
        self._eq: Optional[dict] = None
        self._fut: Optional[dict] = None

    # ---- master loading (reduced + cached once per day) --------------------------
    def _load(self, exch: str) -> dict:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        f = self.cache_dir / f"instr2_{exch}_{pd.Timestamp.now(tz='UTC'):%Y%m%d}.json"
        if f.exists():
            return json.loads(f.read_text())
        log.info("Downloading Upstox instrument master (%s) ...", exch)
        r = self.http.get(URL.format(exch), timeout=90)
        r.raise_for_status()
        rows = json.loads(gzip.decompress(r.content))
        eq, fut, opt = {}, [], []
        for x in rows:
            seg, typ = x.get("segment"), x.get("instrument_type")
            if seg == "NSE_EQ" and typ == "EQ":
                eq[x["trading_symbol"]] = x["instrument_key"]
            elif typ == "FUT" and seg in ("MCX_FO", "NSE_FO", "NCD_FO"):
                fut.append({"u": x.get("underlying_symbol") or x.get("name"), "k": x["instrument_key"],
                            "e": x.get("expiry"), "ts": x.get("trading_symbol"), "seg": seg})
            elif typ in ("CE", "PE") and seg in ("NSE_FO", "BSE_FO") and \
                    (x.get("underlying_symbol") or "").upper() in INDEX_KEYS:
                opt.append({"u": x["underlying_symbol"].upper(), "k": x["instrument_key"], "e": x.get("expiry"),
                            "st": x.get("strike_price"), "t": typ, "ts": x.get("trading_symbol"),
                            "ls": x.get("lot_size")})
        out = {"eq": eq, "fut": fut, "opt": opt}
        f.write_text(json.dumps(out))
        for old in self.cache_dir.glob(f"instr*_{exch}_*.json"):
            if old != f:
                old.unlink(missing_ok=True)
        return out

    def equity(self, symbol: str) -> Optional[str]:
        if self._eq is None:
            self._eq = self._load("NSE")["eq"]
        return self._eq.get(symbol)

    def future(self, underlying: str, exch: str = "MCX", min_days: int = 2) -> Optional[str]:
        """Nearest-expiry future with at least `min_days` left (avoids expiring contract)."""
        if self._fut is None:
            self._fut = {}
        if exch not in self._fut:
            self._fut[exch] = self._load(exch)["fut"]
        now = pd.Timestamp.now(tz="UTC")
        best = None
        for x in self._fut[exch]:
            if (x["u"] or "").upper() != underlying.upper() or not x["e"]:
                continue
            exp = pd.Timestamp(int(x["e"]), unit="ms", tz="UTC")
            if exp - now < pd.Timedelta(days=min_days):
                continue
            if best is None or exp < best[0]:
                best = (exp, x["k"])
        return best[1] if best else None

    def option(self, underlying: str, spot: float, typ: str, step: float, now: Optional[pd.Timestamp] = None) -> Optional[dict]:
        """ATM option (typ = CE | PE) of the nearest expiry that has not expired yet (today's expiry counts)."""
        exch = "BSE" if underlying.upper() == "SENSEX" else "NSE"
        if not hasattr(self, "_opt"):
            self._opt = {}
        if exch not in self._opt:
            self._opt[exch] = self._load(exch).get("opt", [])
        now = pd.Timestamp.now(tz="UTC") if now is None else now
        today = now.tz_convert("Asia/Kolkata").date()
        rows = []
        for x in self._opt[exch]:
            if x["u"] != underlying.upper() or x["t"] != typ or not x["e"] or x["st"] is None:
                continue
            exp = pd.Timestamp(int(x["e"]), unit="ms", tz="UTC").tz_convert("Asia/Kolkata").date()
            if exp >= today:
                rows.append((exp, x))
        if not rows:
            return None
        exp0 = min(e for e, _ in rows)
        cands = [x for e, x in rows if e == exp0]
        target = round(spot / step) * step
        best = min(cands, key=lambda x: abs(float(x["st"]) - target))
        return {"key": best["k"], "symbol": best["ts"], "strike": float(best["st"]), "type": typ,
                "expiry": exp0.isoformat(), "lot": best.get("ls")}

    def resolve(self, symbol: str, market: str) -> Optional[str]:
        if symbol in INDEX_KEYS:
            return INDEX_KEYS[symbol]
        if market == "mcx":
            return self.future(symbol, "MCX")
        return self.equity(symbol)
