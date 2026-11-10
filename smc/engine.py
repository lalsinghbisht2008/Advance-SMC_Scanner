"""Smart-Money-Concepts engine.

Everything here is CAUSAL: it only uses candles that are already closed and
pivots that are already confirmed, so a signal never changes (repaints) once it
has been produced.  `tests/test_engine.py::test_no_repaint` checks this.

Model implemented (bullish; bearish is the same code run on a price-inverted
copy of the data - see `Frame.flip`):

  1. Liquidity pool (SSL) below price: HTF swing low / equal lows / previous-day
     low / internal LTF swing low, that has not been traded through before.
  2. Sweep: a candle wicks BELOW the pool and the market closes back ABOVE it
     within `reject_bars` candles (a real grab, not a breakdown).
  3. MSS / CHoCH: after the sweep a candle CLOSES above the last LTF swing high
     that existed before the sweep low.
  4. Displacement: strong bullish candle(s) in that leg AND a fair value gap.
  5. POI: the last bearish candle (order block) at the start of the leg, with
     the FVG as confluence.  Entry = limit inside the OB (default 50%).
  6. SL below the sweep extreme, TP at the next opposing liquidity (BSL) that
     gives >= min_rr, TP2 at the following pool.
  7. Filters / score: premium-discount of the HTF range, HTF structure bias,
     kill-zone, volume expansion, RR.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .sim import simulate_trade
from .utils import tf_delta


# --------------------------------------------------------------------------- params
@dataclass
class Params:
    swing_n: int = 3              # LTF pivot strength (bars each side)
    htf_swing_n: int = 3          # HTF pivot strength
    atr_n: int = 14
    sweep_lookback: int = 60      # sweep must be within the last N LTF bars
    reject_bars: int = 3          # sweep candle must reclaim the level within N bars
    max_sweep_atr: float = 3.0    # deeper than this = breakdown, not a sweep
    disp_mult: float = 1.3        # displacement body >= mult * avg body(20)
    disp_body_ratio: float = 0.55 # ... and body >= 55% of the candle range
    require_fvg: bool = True
    ob_search: int = 5            # look back this many bars for the order block
    entry_mode: str = "mid"       # mid | proximal | distal
    sl_buf_atr: float = 0.15
    min_rr: float = 1.5           # TP1 must be at least this many R
    max_rr: float = 6.0
    fallback_rr: tuple = (2.0, 3.5)
    min_risk_atr: float = 0.4
    max_risk_atr: float = 8.0
    max_age_bars: int = 48        # pending setup expires this many bars after MSS
    fresh_bars: int = 6           # "just triggered" window for new alerts
    pending_max_progress: float = 0.85  # skip pending setup if price already covered this share of entry->TP1
    eq_tol_atr: float = 0.15      # equal highs/lows tolerance (x HTF ATR)
    min_score: int = 6
    require_discount: bool = True # longs only in discount, shorts only in premium
    htf_bias: str = "soft"        # off | soft | hard
    tp1_frac: float = 0.5
    require_idm: bool = True      # setup needs an inducement (IDM) that is defined and swept
    idm_n: int = 1                # minor-pivot strength used to find the IDM


# --------------------------------------------------------------------------- frame
def _pivots(high: np.ndarray, low: np.ndarray, n: int):
    """Confirmed fractal pivots. Pivot at i is only known at bar i+n."""
    N = len(high)
    ph, pl = [], []
    for i in range(n, N - n):
        if high[i] > high[i - n:i].max() and high[i] >= high[i + 1:i + n + 1].max():
            ph.append(i)
        if low[i] < low[i - n:i].min() and low[i] <= low[i + 1:i + n + 1].min():
            pl.append(i)
    return ph, pl


@dataclass
class Frame:
    t: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    atr: np.ndarray
    delta: pd.Timedelta
    n: int
    ph: list = field(default_factory=list)
    pl: list = field(default_factory=list)
    flipped: bool = False

    def __len__(self):
        return len(self.c)

    @classmethod
    def from_df(cls, df: pd.DataFrame, tf: str, n: int, atr_n: int = 14) -> "Frame":
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        v = df["volume"].to_numpy(float)
        prev_c = np.r_[c[0], c[:-1]]
        tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
        atr = pd.Series(tr).rolling(atr_n, min_periods=1).mean().to_numpy()
        ph, pl = _pivots(h, l, n)
        return cls(df.index, o, h, l, c, v, atr, tf_delta(tf), n, ph, pl, False)

    def flip(self) -> "Frame":
        """Price-inverted copy: a bearish setup becomes a bullish one."""
        return Frame(self.t, -self.o, -self.l, -self.h, -self.c, self.v, self.atr,
                     self.delta, self.n, list(self.pl), list(self.ph), not self.flipped)


# --------------------------------------------------------------------------- structures
@dataclass
class Pool:
    level: float
    kind: str
    weight: int
    known_at: pd.Timestamp


@dataclass
class Setup:
    side: str                     # BUY | SELL
    pool_kind: str
    pool_level: float
    sweep_time: pd.Timestamp
    sweep_extreme: float
    mss_time: pd.Timestamp
    mss_level: float
    fvg: Optional[tuple]
    ob: Optional[tuple]
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp_kind: str
    rr1: float
    rr2: float
    score: int
    reasons: list
    state: str                    # PENDING | TRIGGERED
    bias: str
    zone_pd: str                  # discount | premium
    atr: float
    last_close: float
    trigger_time: Optional[pd.Timestamp] = None
    stage: str = "NO_IDM"           # WAIT_IDM | ARMED | NO_IDM
    idm_level: Optional[float] = None
    idm_time: Optional[pd.Timestamp] = None
    hh_level: Optional[float] = None
    bos_time: Optional[pd.Timestamp] = None
    # filled by strategy layer
    symbol: str = ""
    market: str = ""
    profile: str = ""
    ltf: str = ""
    htf: str = ""

    @property
    def id(self) -> str:
        return f"{self.market}:{self.symbol}|{self.profile}|{self.side}|{self.mss_time:%Y%m%d%H%M}"


def walk_up(h, l, c, ph, pl, n, start=0, hl0=None):
    """Bullish structure walker with INDUCEMENT (IDM) validation.

    candidate high  = confirmed pivot high; its IDM = last pivot low in its left leg
                      (above the protected low).  A higher pivot replaces the candidate
                      until the IDM is taken.
    IDM_TAKEN       = a candle trades below the IDM low  -> candidate becomes a valid HH
    BOS_UP          = a candle CLOSES above the valid HH (never before IDM is taken)
    CHOCH_DOWN      = close below the protected low (HL)
    Returns {'events': [...], 'cand': (level, idx) | None, 'idm': (level, idx) | None}
    """
    N = len(c)
    conf_h = {i + n: i for i in ph}
    hl = hl0
    floor = start - 1
    cand = idm = None
    taken = None
    retrace_low = None
    events = []
    for t in range(start, N):
        q = conf_h.get(t)
        if q is not None and q > floor and taken is None and (cand is None or h[q] > cand[0]):
            lows = [x for x in pl if floor < x < q and x + n <= t and (hl is None or l[x] > hl)]
            if lows and hl is None:
                # leg origin (lowest pivot low) is the start of the leg, not an inducement
                origin = min(lows, key=lambda x: l[x])
                lows = [x for x in lows if x > origin]
            if lows:
                cand, idm = (h[q], q), (l[lows[-1]], lows[-1])
            else:
                cand = idm = None
        if cand is not None and taken is None and t > cand[1] and l[t] < idm[0]:
            taken, retrace_low = t, l[t]
            events.append({"idx": t, "kind": "IDM_TAKEN", "level": idm[0], "high": cand[0], "high_idx": cand[1]})
        elif taken is not None:
            retrace_low = min(retrace_low, l[t])
        if hl is not None and c[t] < hl:
            events.append({"idx": t, "kind": "CHOCH_DOWN", "level": hl})
            hl, cand, idm, taken, floor = None, None, None, None, t
            continue
        if taken is not None and t > taken and c[t] > cand[0]:
            events.append({"idx": t, "kind": "BOS_UP", "level": cand[0]})
            hl, floor = retrace_low, t
            cand = idm = taken = None
    return {"events": events, "cand": cand, "idm": idm}


def htf_bias(f: Frame) -> int:
    """+1 / -1 / 0 from the latest IDM-validated BOS or CHoCH (both directions)."""
    up = walk_up(f.h, f.l, f.c, f.ph, f.pl, f.n)["events"]
    fl = f.flip()
    dn = walk_up(fl.h, fl.l, fl.c, fl.ph, fl.pl, fl.n)["events"]
    last = None
    for e in up:
        if e["kind"] in ("BOS_UP", "CHOCH_DOWN") and (last is None or e["idx"] >= last[0]):
            last = (e["idx"], 1 if e["kind"] == "BOS_UP" else -1)
    for e in dn:
        if e["kind"] in ("BOS_UP", "CHOCH_DOWN") and (last is None or e["idx"] > last[0]):
            last = (e["idx"], -1 if e["kind"] == "BOS_UP" else 1)
    return last[1] if last else 0


def dealing_range(f: Frame):
    if f.ph and f.pl:
        hi, lo = f.h[f.ph[-1]], f.l[f.pl[-1]]
        if hi > lo:
            return hi, lo
    w = min(len(f), 50)
    return f.h[-w:].max(), f.l[-w:].min()


def pools_low(ltf: Frame, htf: Frame, daily: Optional[Frame], p: Params) -> list:
    """Sell-side liquidity (resting stops under lows) in the frame's orientation."""
    out: list[Pool] = []
    n = htf.n
    known = {}
    for i in htf.pl:
        if i + n < len(htf):
            k = htf.t[i + n] + htf.delta
            known[i] = k
            out.append(Pool(htf.l[i], "HTF swing low", 2, k))
    pls = [i for i in htf.pl if i in known][-40:]
    for a in range(len(pls)):
        for b in range(a + 1, len(pls)):
            i, j = pls[a], pls[b]
            if j - i > 80:
                continue
            if abs(htf.l[i] - htf.l[j]) <= p.eq_tol_atr * htf.atr[j]:
                out.append(Pool(min(htf.l[i], htf.l[j]), "Equal lows", 3, max(known[i], known[j])))
    if daily is not None and len(daily) > 0:
        out.append(Pool(daily.l[-1], "Previous-day low", 3, daily.t[-1] + daily.delta))
    nl = ltf.n
    for i in ltf.pl:
        if i + nl < len(ltf):
            out.append(Pool(ltf.l[i], "Internal swing low", 1, ltf.t[i + nl] + ltf.delta))
    # de-duplicate near-identical levels, keep the most significant
    out.sort(key=lambda x: -x.weight)
    kept: list[Pool] = []
    for pool in out:
        if not any(abs(pool.level - k.level) <= 1e-4 * abs(k.level) for k in kept):
            kept.append(pool)
    return kept


def _consumed_before(htf: Frame, pool: Pool, until: pd.Timestamp) -> bool:
    """Was the level already traded through on HTF candles that the LTF data does not cover?"""
    for k in range(len(htf)):
        if htf.t[k] >= pool.known_at and htf.t[k] + htf.delta <= until and htf.l[k] < pool.level:
            return True
    return False


# --------------------------------------------------------------------------- detection
@dataclass
class Info:
    """Market context injected by the strategy layer (keeps the engine pure)."""
    killzone: Callable[[pd.Timestamp], bool] = lambda ts: False
    eod_flags: Optional[np.ndarray] = None     # True on the last candle of each session


def detect_long(ltf: Frame, htf: Frame, daily: Optional[Frame], p: Params, info: Info,
                targets_src: Optional[tuple] = None) -> list:
    """Bullish setups in the frame orientation. `targets_src` = (ltf, htf, daily)
    in the OPPOSITE orientation, used to read buy-side liquidity as targets."""
    N = len(ltf)
    if N < 60 or len(htf) < 20:
        return []
    pools = pools_low(ltf, htf, daily, p)
    trend = htf_bias(htf)
    mph, mpl = _pivots(ltf.h, ltf.l, p.idm_n)
    hi, lo = dealing_range(htf)
    eq = (hi + lo) / 2.0
    body = np.abs(ltf.c - ltf.o)
    avgbody = pd.Series(body).rolling(20, min_periods=5).mean().shift(1).to_numpy()
    bsl = []
    if targets_src is not None:
        bsl = [(-x.level, x) for x in pools_low(*targets_src, p)]   # un-invert to this frame's prices
    setups: list[Setup] = []

    for pool in pools:
        s0 = int(ltf.t.searchsorted(pool.known_at))
        if s0 >= N:
            continue
        if _consumed_before(htf, pool, ltf.t[0]):
            continue
        breach = np.nonzero(ltf.l[s0:] < pool.level)[0]
        if len(breach) == 0:
            continue
        s = s0 + int(breach[0])
        if s < N - p.sweep_lookback:
            continue
        r = next((k for k in range(s, min(s + p.reject_bars, N)) if ltf.c[k] > pool.level), None)
        if r is None:
            continue                               # closed below = breakdown, not a sweep
        ext = s + int(np.argmin(ltf.l[s:r + 1]))
        ext_low = ltf.l[ext]
        if pool.level - ext_low > p.max_sweep_atr * ltf.atr[ext]:
            continue
        qs = [q for q in ltf.ph if ext - 80 <= q < ext]
        if not qs:
            continue
        mss_level = ltf.h[qs[-1]]
        if mss_level <= ext_low:
            continue

        m = None
        for k in range(max(ext + 1, r), N):
            if ltf.l[k] < ext_low:                 # sweep kept extending
                ext, ext_low = k, ltf.l[k]
                if pool.level - ext_low > p.max_sweep_atr * ltf.atr[k]:
                    break
            if ltf.c[k] > mss_level:
                m = k
                break
        if m is None or m <= ext:
            continue

        disp = strong = False
        for k in range(ext + 1, m + 1):
            rng = ltf.h[k] - ltf.l[k]
            ab = avgbody[k]
            if rng <= 0 or np.isnan(ab) or ab <= 0:
                continue
            if ltf.c[k] > ltf.o[k] and body[k] >= p.disp_mult * ab and body[k] >= p.disp_body_ratio * rng:
                disp = True
                strong = strong or body[k] >= 1.8 * ab
        if not disp:
            continue
        fvg = None
        for k in range(ext + 1, min(m + 1, N - 1)):
            if ltf.l[k + 1] > ltf.h[k - 1]:
                gap = (ltf.h[k - 1], ltf.l[k + 1])
                if fvg is None or (gap[1] - gap[0]) > (fvg[1] - fvg[0]):
                    fvg = gap
        if p.require_fvg and fvg is None:
            continue
        ob = None
        for j in range(ext, max(ext - p.ob_search, 0) - 1, -1):
            if ltf.c[j] < ltf.o[j]:
                ob = (ltf.l[j], ltf.h[j])
                break
        zone = ob or fvg
        if zone is None:
            continue
        atr_m = ltf.atr[m]
        confluence = bool(ob and fvg and fvg[0] <= ob[1] + 0.3 * atr_m and fvg[1] >= ob[0])
        entry = {"mid": (zone[0] + zone[1]) / 2.0, "proximal": zone[1], "distal": zone[0]}[p.entry_mode]
        sl = ext_low - p.sl_buf_atr * atr_m
        risk = entry - sl
        if risk <= 0 or risk < p.min_risk_atr * atr_m or risk > p.max_risk_atr * atr_m:
            continue
        discount = entry <= eq
        if p.require_discount and not discount:
            continue
        if p.htf_bias == "hard" and trend < 0:
            continue

        run_high = ltf.h[m:].max()
        above = sorted({lvl for lvl, bp in bsl if lvl > max(entry, run_high) and bp.known_at <= ltf.t[-1] + ltf.delta})
        tp1 = next((x for x in above if (x - entry) / risk >= p.min_rr), None)
        tp_kind = "liquidity"
        if tp1 is None:
            tp1, tp_kind = entry + p.fallback_rr[0] * risk, "fixed R"
            tp2 = entry + p.fallback_rr[1] * risk
        else:
            if (tp1 - entry) / risk > p.max_rr:
                tp1, tp_kind = entry + p.max_rr * risk, "capped"
            tp2 = next((x for x in above if x > tp1 + 0.5 * risk), None)
            if tp2 is None:
                tp2 = entry + max(p.fallback_rr[1], 1.6 * (tp1 - entry) / risk) * risk
        rr1, rr2 = (tp1 - entry) / risk, (tp2 - entry) / risk

        # ---- inducement (IDM) stage after the MSS --------------------------------------
        wk = walk_up(ltf.h, ltf.l, ltf.c, mph, mpl, p.idm_n, start=ext + 1, hl0=ext_low)
        ev = wk["events"]
        taken_ev = next((e for e in ev if e["kind"] == "IDM_TAKEN"), None)
        choch = next((e for e in ev if e["kind"] == "CHOCH_DOWN"), None)
        if choch is not None and (taken_ev is None or choch["idx"] <= taken_ev["idx"]):
            continue                                # structure broke before the setup armed
        bos_ev = next((e for e in ev if e["kind"] == "BOS_UP" and taken_ev and e["idx"] > taken_ev["idx"]), None)
        if taken_ev is not None:
            stage, idm_level = "ARMED", taken_ev["level"]
            sim_start = max(taken_ev["idx"], m + 1)
        elif wk["cand"] is not None:
            stage, idm_level = "WAIT_IDM", wk["idm"][0]
            sim_start = m + 1
        else:
            if p.require_idm:
                continue                            # no valid inducement -> no valid HH/BOS yet
            stage, idm_level, sim_start = "NO_IDM", None, m + 1

        sim = simulate_trade(ltf.h, ltf.l, ltf.c, "BUY", entry, sl, tp1, tp2, sim_start,
                             eod=info.eod_flags, expire_bars=p.max_age_bars, tp1_frac=p.tp1_frac)
        trig_time = None
        if sim["status"] == "PENDING":
            state = "PENDING"
            # price already ran most of the way to TP1 without retracing -> the entry is unlikely
            if (run_high - entry) / (tp1 - entry) > p.pending_max_progress:
                continue
        elif stage != "WAIT_IDM" and sim["status"] == "OPEN" and sim["fill_idx"] >= N - p.fresh_bars:
            state = "TRIGGERED"
            trig_time = ltf.t[sim["fill_idx"]]
        else:
            continue                                # already played out / stale / expired / filled before IDM

        score, reasons = 0, []
        if pool.weight >= 2:
            score += 2
            reasons.append(f"{pool.kind} swept (HTF liquidity)")
        else:
            score += 1
            reasons.append(f"{pool.kind} swept (internal only)")
        if strong:
            score += 1
            reasons.append("Strong displacement")
        if confluence:
            score += 1
            reasons.append("OB + FVG confluence")
        if trend > 0:
            score += 2
            reasons.append("HTF structure aligned")
        elif trend < 0:
            reasons.append("Counter-trend vs HTF structure")
        if discount:
            score += 1
            reasons.append("Entry in discount of HTF range")
        if stage == "ARMED":
            score += 1
            reasons.append("IDM taken (HH validated)")
        if info.killzone(ltf.t[m]):
            score += 1
            reasons.append("Inside kill-zone")
        vol_ref = ltf.v[max(0, m - 20):m].mean() if m > 0 else 0
        if vol_ref > 0 and ltf.v[m] >= 1.5 * vol_ref:
            score += 1
            reasons.append("Volume expansion on MSS")
        if rr1 >= 2.5:
            score += 1
            reasons.append(f"RR {rr1:.1f}")
        if score < p.min_score:
            continue

        setups.append(Setup(
            side="BUY", pool_kind=pool.kind, pool_level=float(pool.level),
            sweep_time=ltf.t[ext], sweep_extreme=float(ext_low),
            mss_time=ltf.t[m], mss_level=float(mss_level), fvg=fvg, ob=ob,
            entry=float(entry), sl=float(sl), tp1=float(tp1), tp2=float(tp2), tp_kind=tp_kind,
            rr1=float(rr1), rr2=float(rr2), score=int(score), reasons=reasons, state=state,
            bias={1: "bullish", -1: "bearish", 0: "neutral"}[trend],
            zone_pd="discount" if discount else "premium",
            atr=float(atr_m), last_close=float(ltf.c[-1]), trigger_time=trig_time,
            stage=stage, idm_level=None if idm_level is None else float(idm_level),
            idm_time=ltf.t[taken_ev["idx"]] if taken_ev else None,
            hh_level=float(taken_ev["high"]) if taken_ev else None,
            bos_time=ltf.t[bos_ev["idx"]] if bos_ev else None,
        ))
    return setups


def _unflip(s: Setup) -> Setup:
    neg = lambda x: -x
    z = lambda t: None if t is None else (-t[1], -t[0])
    return replace(
        s, side="SELL", pool_level=neg(s.pool_level), sweep_extreme=neg(s.sweep_extreme),
        mss_level=neg(s.mss_level), fvg=z(s.fvg), ob=z(s.ob), entry=neg(s.entry), sl=neg(s.sl),
        tp1=neg(s.tp1), tp2=neg(s.tp2), last_close=neg(s.last_close),
        idm_level=None if s.idm_level is None else neg(s.idm_level),
        hh_level=None if s.hh_level is None else neg(s.hh_level),
        zone_pd="premium" if s.zone_pd == "discount" else "discount",
        bias={"bullish": "bearish", "bearish": "bullish"}.get(s.bias, "neutral"),
    )


def find_setups(ltf_df, htf_df, daily_df, ltf_tf: str, htf_tf: str, p: Params, info: Info) -> list:
    """Run the model for both directions on CLOSED candles. Returns Setup objects
    in real prices (SELL setups are un-inverted)."""
    ltf = Frame.from_df(ltf_df, ltf_tf, p.swing_n, p.atr_n)
    htf = Frame.from_df(htf_df, htf_tf, p.htf_swing_n, p.atr_n)
    daily = Frame.from_df(daily_df, "1d", 2, p.atr_n) if daily_df is not None and len(daily_df) >= 2 else None
    out = detect_long(ltf, htf, daily, p, info, (ltf.flip(), htf.flip(), daily.flip() if daily else None))
    fl, fh, fd = ltf.flip(), htf.flip(), (daily.flip() if daily else None)
    fi = Info(killzone=info.killzone, eod_flags=info.eod_flags)
    for s in detect_long(fl, fh, fd, p, fi, (ltf, htf, daily)):
        out.append(_unflip(s))
    return out
