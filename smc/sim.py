"""Trade lifecycle simulation on candles - shared by the live tracker, the
setup detector (to know whether a setup is still pending) and the backtester.

Rules (deliberately conservative):
  * entry is a LIMIT order: filled when a candle trades down to (BUY) / up to (SELL) the entry price
  * if SL and TP are both inside one candle, SL is assumed to hit first
  * a candle that fills the entry can only be stopped out in the same candle, never take profit
  * TP1 closes `tp1_frac` of the position and moves the stop to break-even
  * remaining part exits at TP2, at break-even, or at the end of the session (`eod` flag)
"""
from __future__ import annotations

import numpy as np

CLOSED = {"CLOSED_SL", "CLOSED_BE", "CLOSED_TP2", "CLOSED_EOD", "CANCELLED", "EXPIRED"}


def simulate_trade(h, l, c, side, entry, sl, tp1, tp2, start, eod=None,
                   expire_bars=None, tp1_frac=0.5):
    """Walk candles from index `start`. Returns a dict:

    status   : PENDING | OPEN | TP1 | CLOSED_SL | CLOSED_BE | CLOSED_TP2 |
               CLOSED_EOD | CANCELLED | EXPIRED
    events   : ordered list of (kind, bar_index, price)  kind in FILLED, TP1, TP2, SL, BE, EOD, CANCELLED, EXPIRED
    fill_idx, exit_idx, r (realised R, None while not closed)
    """
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    sgn = 1.0
    if side.upper().startswith("SELL"):
        sgn = -1.0
        h, l = -l, -h
        c = -c
        entry, sl, tp1, tp2 = -entry, -sl, -tp1, -tp2
    risk = entry - sl
    if risk <= 0:
        raise ValueError("Invalid trade levels: risk <= 0")
    r1 = (tp1 - entry) / risk
    r2 = (tp2 - entry) / risk
    N = len(h)
    events = []
    res = {"status": "PENDING", "events": events, "fill_idx": None, "exit_idx": None, "r": None}

    def ev(kind, k, price):
        events.append((kind, k, sgn * price))

    def done(status, k, price, r):
        res.update(status=status, exit_idx=k, r=float(r))
        return res

    state = "PENDING"
    cur_sl = sl
    tp1_hit = False
    for k in range(start, N):
        last_of_session = bool(eod[k]) if eod is not None else False
        if state == "PENDING":
            if expire_bars is not None and (k - start) >= expire_bars:
                ev("EXPIRED", k, c[k])
                return done("EXPIRED", k, c[k], 0.0)
            if l[k] <= entry:
                state = "OPEN"
                res["fill_idx"] = k
                res["status"] = "OPEN"
                ev("FILLED", k, entry)
                if l[k] <= sl:
                    ev("SL", k, sl)
                    return done("CLOSED_SL", k, sl, -1.0)
                if last_of_session:
                    ev("EOD", k, c[k])
                    return done("CLOSED_EOD", k, c[k], (c[k] - entry) / risk)
                continue
            if h[k] >= tp1:
                ev("CANCELLED", k, tp1)
                return done("CANCELLED", k, tp1, 0.0)
            if last_of_session:
                ev("EXPIRED", k, c[k])
                return done("EXPIRED", k, c[k], 0.0)
            continue

        # ---- position is open (fill happened on an earlier candle) ----
        if l[k] <= cur_sl:
            if tp1_hit:
                ev("BE", k, cur_sl)
                return done("CLOSED_BE", k, cur_sl, tp1_frac * r1)
            ev("SL", k, cur_sl)
            return done("CLOSED_SL", k, cur_sl, -1.0)
        if not tp1_hit and h[k] >= tp1:
            tp1_hit = True
            cur_sl = entry
            res["status"] = "TP1"
            ev("TP1", k, tp1)
        elif tp1_hit and h[k] >= tp2:
            ev("TP2", k, tp2)
            return done("CLOSED_TP2", k, tp2, tp1_frac * r1 + (1 - tp1_frac) * r2)
        if last_of_session:
            rest = (c[k] - entry) / risk
            ev("EOD", k, c[k])
            r = tp1_frac * r1 + (1 - tp1_frac) * rest if tp1_hit else rest
            return done("CLOSED_EOD", k, c[k], r)
    return res
