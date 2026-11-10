"""Glue between market config, candles and the SMC engine."""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pandas as pd

from .config import Market, Profile
from .engine import Info, Params, Setup, find_setups
from .utils import drop_unclosed, staleness_minutes, tf_delta


def params_for(market: Market, profile: Profile) -> Params:
    p = Params()
    if profile.name == "swing":
        p = replace(p, sweep_lookback=40, max_age_bars=30, fresh_bars=3)
    return p


def prepare(market: Market, profile: Profile, raw: dict, now: pd.Timestamp):
    """raw = {'ltf': df, 'htf': df, 'daily': df|None} -> closed-candle frames."""
    ltf = drop_unclosed(raw["ltf"], profile.ltf, now, market.session_end)
    htf = drop_unclosed(raw["htf"], profile.htf, now, market.session_end)
    daily = None
    if profile.use_daily and raw.get("daily") is not None:
        daily = drop_unclosed(raw["daily"], "1d", now, market.session_end)
    return ltf, htf, daily


def analyze(market: Market, profile: Profile, symbol: str, raw: dict, now: pd.Timestamp,
            p: Optional[Params] = None):
    """Returns (setups, ltf_closed_df, note). `note` explains why nothing was produced."""
    p = p or params_for(market, profile)
    ltf, htf, daily = prepare(market, profile, raw, now)
    if len(ltf) < 80 or len(htf) < 25:
        return [], ltf, f"not enough candles (ltf={len(ltf)}, htf={len(htf)})"
    if market.is_open(now) and staleness_minutes(ltf, profile.ltf, now) > \
            4 * tf_delta(profile.ltf).total_seconds() / 60:
        return [], ltf, "stale data"

    info = Info(killzone=market.in_killzone, eod_flags=market.eod_flags(ltf.index, tf_delta(profile.ltf)))
    found = find_setups(ltf, htf, daily, profile.ltf, profile.htf, p, info)

    last_local = market.local(ltf.index[-1])
    out = []
    for s in found:
        if market.same_session and market.local(s.mss_time).date() != last_local.date():
            continue
        if market.no_new_after and market.local(now).time() >= market.no_new_after:
            continue
        s.symbol, s.market, s.profile, s.ltf, s.htf = symbol, market.name, profile.name, profile.ltf, profile.htf
        out.append(s)
    best = {}
    for s in out:                                  # best setup per direction
        k = s.side
        if k not in best or (s.score, s.mss_time) > (best[k].score, best[k].mss_time):
            best[k] = s
    return list(best.values()), ltf, ""
