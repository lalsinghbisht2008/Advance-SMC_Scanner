"""Index setup -> option trade plan.  Signal and levels come from the INDEX chart; the option is the instrument.
BUY setup -> ATM CE, SELL setup -> ATM PE (we only ever BUY options).  Premium levels are a delta estimate."""
from __future__ import annotations

import logging

from .config import OPTION_DELTA, OPTION_STEP

log = logging.getLogger("smc.options")


def premium_at(p0: float, spot0: float, level: float, side: str, delta: float = OPTION_DELTA) -> float:
    move = (level - spot0) if side == "BUY" else (spot0 - level)
    return max(0.05, p0 + delta * move)


def plan(trade: dict, provider, now=None, delta: float = OPTION_DELTA):
    """Returns the option dict stored in trade['opt'] (never raises; None if the contract is not found)."""
    try:
        step = OPTION_STEP.get(trade["symbol"])
        if not step:
            return None
        typ = "CE" if trade["side"] == "BUY" else "PE"
        spot = trade.get("last_close") or trade["entry"]
        c = provider.resolver.option(trade["symbol"], trade["entry"], typ, step, now)
        if c is None:
            return None
        c["delta"] = delta
        ltp = provider.ltp([c["key"]]).get(c["key"])
        c["ltp"] = ltp
        if ltp:
            s0 = spot
            c["entry_prem"] = premium_at(ltp, s0, trade["entry"], trade["side"], delta)
            c["sl_prem"] = premium_at(ltp, s0, trade["sl"], trade["side"], delta)
            c["tp1_prem"] = premium_at(ltp, s0, trade["tp1"], trade["side"], delta)
            c["tp2_prem"] = premium_at(ltp, s0, trade["tp2"], trade["side"], delta)
        return c
    except Exception as e:                      # an option lookup problem must not block the index alert
        log.warning("option plan failed for %s: %s: %s", trade.get("symbol"), type(e).__name__, e)
        return None
