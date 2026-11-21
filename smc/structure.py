"""HTF structure map (HH/HL/LH/LL, IDM sweep, BOS, CHoCH) built from the same IDM walker the scanner uses.

Rules (bullish; bearish = mirror):
  swing high -> retrace -> IDM (start of the last real impulse up) -> price sweeps the IDM -> that swing high is a
  confirmed HH -> a candle CLOSE above the HH = BOS.  The retrace low made by the sweep = HL (protected)."""
from __future__ import annotations

from .engine import Frame, htf_idm_state, walk_up

ZZ = 2.0


def _ray_end(f: Frame, idx: int, price: float, bear_high: bool):
    """First bar after idx where the level is broken (None = still intact)."""
    for t in range(idx + 1, len(f)):
        if (bear_high and f.h[t] > price) or (not bear_high and f.l[t] < price):
            return t
    return None


def build_map(f: Frame, max_age: int = 24, zz: float = ZZ) -> dict:
    """{'lines': [(x0, x1, price, label, side)], 'pts': [(idx, price, label, side)],
        'rays': [(x0, x_end|None, price, label, side)], 'log': [str], 'state': {...}}  (real prices)."""
    lines, pts, rays, log = [], [], [], []
    for flipped, sgn in ((False, 1.0), (True, -1.0)):
        g = f.flip() if flipped else f
        ev = walk_up(g.h, g.l, g.c, g.ph, g.pl, g.n, atr=g.atr, zz=zz)["events"]
        side = "bear" if flipped else "bull"
        hi_lbl, lo_lbl = ("LL", "LH") if flipped else ("HH", "HL")
        sweep_pt = None
        for k, e in enumerate(ev):
            when = f.t[e["idx"]].strftime("%d %b %H:%M")
            if e["kind"] == "IDM_TAKEN":
                lines.append((e["idm_idx"], e["idx"], sgn * e["level"], "IDM Sweep", side))
                pts.append((e["high_idx"], sgn * e["high"], hi_lbl, side))
                sweep_pt = (e["idx"], sgn * g.l[e["idx"]], lo_lbl, side)
                pts.append(sweep_pt)
                nxt = next((x["idx"] for x in ev[k + 1:] if x["kind"] in ("BOS_UP", "CHOCH_DOWN")), None)
                rays.append((e["high_idx"], nxt, sgn * e["high"], hi_lbl, side))
                rays.append((e["idx"], _ray_end(f, e["idx"], sweep_pt[1], flipped), sweep_pt[1], lo_lbl, side))
                log.append(f"{side}: IDM {sgn * e['level']:.2f} swept {when} -> {hi_lbl} {sgn * e['high']:.2f} confirmed, "
                           f"{lo_lbl} {sweep_pt[1]:.2f}")
            elif e["kind"] == "BOS_UP":
                lines.append((e["level_idx"], e["idx"], sgn * e["level"], "BOS", side))
                if sweep_pt in pts:
                    pts.remove(sweep_pt)
                if e.get("hl_idx") is not None:
                    pts.append((e["hl_idx"], sgn * e["hl"], lo_lbl, side))
                sweep_pt = None
                log.append(f"{side}: BOS {when} (close beyond {sgn * e['level']:.2f})")
            elif e["kind"] == "CHOCH_DOWN" and e.get("level_idx") is not None:
                lines.append((e["level_idx"], e["idx"], sgn * e["level"], "CHoCH", side))
                log.append(f"{side}: CHoCH {when} (close beyond {sgn * e['level']:.2f})")
    return {"lines": lines, "pts": pts, "rays": rays, "log": log, "state": state_for(f, max_age, zz)}


def state_for(f: Frame, max_age: int = 24, zz: float = ZZ) -> dict:
    """IDM state for BOTH directions in real prices.
    buy  = bullish leg (IDM = low below price);  sell = bearish leg (IDM = high above price)."""
    b = htf_idm_state(f, max_age, zz)
    s = htf_idm_state(f.flip(), max_age, zz)
    for d, sg in ((b, 1.0), (s, -1.0)):
        for k in ("level", "high"):
            if d[k] is not None:
                d[k] = sg * d[k]
    return {"buy": b, "sell": s}
