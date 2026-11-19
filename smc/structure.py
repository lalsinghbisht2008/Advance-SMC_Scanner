"""HTF structure map (HH/HL/LH/LL, IDM sweep, BOS, CHoCH) built from the same IDM walker the scanner uses."""
from __future__ import annotations

from .engine import Frame, htf_idm_state, walk_up


def build_map(f: Frame) -> dict:
    """Returns {'lines': [(x0, x1, price, label, side)], 'pts': [(idx, price, label, side)], 'state': {...}}
    in REAL prices.  side = 'bull'|'bear' (colour)."""
    lines, pts = [], []
    for flipped, sgn in ((False, 1.0), (True, -1.0)):
        g = f.flip() if flipped else f
        ev = walk_up(g.h, g.l, g.c, g.ph, g.pl, g.n)["events"]
        side = "bear" if flipped else "bull"
        hi_lbl, lo_lbl = ("LL", "LH") if flipped else ("HH", "HL")
        for e in ev:
            if e["kind"] == "IDM_TAKEN":
                lines.append((e["idm_idx"], e["idx"], sgn * e["level"], "IDM Sweep", side))
                pts.append((e["high_idx"], sgn * e["high"], hi_lbl, side))
            elif e["kind"] == "BOS_UP":
                lines.append((e["level_idx"], e["idx"], sgn * e["level"], "BOS", side))
                if e.get("hl_idx") is not None:
                    pts.append((e["hl_idx"], sgn * e["hl"], lo_lbl, side))
            elif e["kind"] == "CHOCH_DOWN" and e.get("level_idx") is not None:
                lines.append((e["level_idx"], e["idx"], sgn * e["level"], "CHoCH", side))
    return {"lines": lines, "pts": pts, "state": state_for(f)}


def state_for(f: Frame) -> dict:
    """Bull-frame IDM state for BOTH directions in real prices.
    buy  = bullish leg (IDM = low below price);  sell = bearish leg (IDM = high above price)."""
    b = htf_idm_state(f)
    s = htf_idm_state(f.flip())
    for d, sg in ((b, 1.0), (s, -1.0)):
        for k in ("level", "high"):
            if d[k] is not None:
                d[k] = sg * d[k]
    return {"buy": b, "sell": s}
