"""Turns a Setup into a tracked trade and keeps its status in sync with new candles.

The status is recomputed from candles every run (idempotent) - so it does not matter
if a scheduled run is late or skipped; events are only announced once.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Market
from .engine import Params, Setup
from .sim import CLOSED, simulate_trade
from .utils import tf_delta


def _iso(ts):
    return None if ts is None else pd.Timestamp(ts).isoformat()


def trade_from_setup(s: Setup, market: Market, now: pd.Timestamp) -> dict:
    return {
        "id": s.id, "symbol": s.symbol, "market": s.market, "market_label": market.label,
        "profile": s.profile, "ltf": s.ltf, "htf": s.htf, "side": s.side,
        "score": s.score, "reasons": s.reasons, "bias": s.bias, "zone_pd": s.zone_pd,
        "pool_kind": s.pool_kind, "pool_level": s.pool_level, "sweep_extreme": s.sweep_extreme,
        "sweep_time": _iso(s.sweep_time), "mss_time": _iso(s.mss_time), "mss_level": s.mss_level,
        "ob": list(s.ob) if s.ob else None, "fvg": list(s.fvg) if s.fvg else None,
        "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2, "tp_kind": s.tp_kind,
        "rr1": s.rr1, "rr2": s.rr2, "status": "PENDING", "events_done": 0,
        "stage": s.stage, "idm_level": s.idm_level, "idm_taken_time": _iso(s.idm_time),
        "hh_level": s.hh_level, "bos_time": _iso(s.bos_time),
        "created": _iso(now), "r": None,
    }


def update_trade(t: dict, ltf_df: pd.DataFrame, market: Market, p: Params):
    """Re-simulate the trade on closed candles after the MSS.
    Returns (new_events, closed_flag). new_events = [(kind, timestamp, price)]."""
    if ltf_df.empty:
        return [], False
    mss = pd.Timestamp(t["mss_time"])
    start = int(ltf_df.index.searchsorted(mss, side="right"))
    extra = []
    idm = t.get("idm_level")
    if idm is not None:                                  # entry is only live after the inducement is swept
        lows = ltf_df["low"].to_numpy()
        hit = next((k for k in range(start, len(lows)) if lows[k] < idm), None)
        if hit is None:
            t["stage"] = "WAIT_IDM"
            start = len(lows)                            # nothing can fill yet
        else:
            t["stage"] = "ARMED"
            start = max(start, hit)
            if not t.get("idm_taken_time"):
                t["idm_taken_time"] = _iso(ltf_df.index[hit])
                extra.append(("IDM_TAKEN", ltf_df.index[hit], idm))
    eod = market.eod_flags(ltf_df.index, tf_delta(t["ltf"]))
    sim = simulate_trade(ltf_df["high"].to_numpy(), ltf_df["low"].to_numpy(), ltf_df["close"].to_numpy(),
                         t["side"], t["entry"], t["sl"], t["tp1"], t["tp2"], start, eod=eod,
                         expire_bars=p.max_age_bars, tp1_frac=p.tp1_frac)
    new = extra + [(k, ltf_df.index[i], price) for (k, i, price) in sim["events"][t["events_done"]:]]
    t["events_done"] = len(sim["events"])
    t["status"] = sim["status"]
    if sim["fill_idx"] is not None:
        t["fill_time"] = _iso(ltf_df.index[sim["fill_idx"]])
    closed = sim["status"] in CLOSED
    if closed:
        t["r"] = sim["r"]
        t["exit_time"] = _iso(ltf_df.index[sim["exit_idx"]])
    return new, closed
