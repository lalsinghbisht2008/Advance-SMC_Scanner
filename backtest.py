#!/usr/bin/env python3
"""Walk-forward backtest of the SAME engine the live scanner uses.

  python backtest.py --market crypto --symbol BTCUSDT --profile 5m --days 30
  python backtest.py --market india  --symbol RELIANCE --profile 5m --days 25     (needs UPSTOX_ACCESS_TOKEN)
  python backtest.py --market crypto --symbol BTCUSDT --ltf-csv ltf.csv --htf-csv htf.csv

CSV columns: ts,open,high,low,close,volume  (ts parseable, UTC preferred)

How it avoids hindsight: at every candle it only sees candles up to that point; a setup counts only
if its entry fill happens AFTER the candle on which the setup was first visible. Conservative fills
(SL first when SL and TP are in the same candle, no TP on the fill candle).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from smc import config as C
from smc.strategy import analyze, params_for
from smc.tracker import trade_from_setup, update_trade
from smc.utils import normalize, tf_delta


def run_backtest(ltf: pd.DataFrame, htf: pd.DataFrame, daily, market, profile, symbol="TEST",
                 warmup=300, step=1, params=None, progress=False):
    p = params or params_for(market, profile)
    seen = {}
    n = len(ltf)
    for end in range(warmup, n + 1, step):
        l = ltf.iloc[:end]
        now = l.index[-1] + tf_delta(profile.ltf) + pd.Timedelta(seconds=3)
        h = htf[(htf.index + tf_delta(profile.htf)) <= now]
        d = None if daily is None else daily[(daily.index + pd.Timedelta(days=1)) <= now]
        setups, _, _ = analyze(market, profile, symbol, {"ltf": l, "htf": h, "daily": d}, now, p)
        for s in setups:
            if s.id not in seen:
                seen[s.id] = (s, l.index[-1])
        if progress and (end - warmup) % 500 == 0:
            print(f"  {end}/{n} candles, {len(seen)} setups", file=sys.stderr)
    rows, skipped = [], 0
    for sid, (s, seen_at) in seen.items():
        t = trade_from_setup(s, market, seen_at)
        update_trade(t, ltf, market, p)
        fill = pd.Timestamp(t["fill_time"]) if t.get("fill_time") else None
        if fill is not None and fill <= seen_at:
            skipped += 1                                       # already filled when first visible
            continue
        rows.append({"id": sid, "side": s.side, "seen": seen_at, "score": s.score, "stage": s.stage,
                     "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "rr1": round(s.rr1, 2),
                     "status": t["status"], "fill": t.get("fill_time"), "exit": t.get("exit_time"),
                     "r": t["r"], "reasons": "; ".join(s.reasons)})
    return pd.DataFrame(rows), skipped


def summarize(df: pd.DataFrame, skipped: int = 0) -> str:
    if df.empty:
        return "No setups found."
    done = df[df["r"].notna() & df["fill"].notna()]
    nofill = df[df["fill"].isna()]
    lines = [f"setups seen: {len(df) + skipped}  | skipped (already filled when visible): {skipped}  "
             f"| never filled / cancelled: {len(nofill)}  | filled & closed: {len(done)}"]
    if done.empty:
        return "\n".join(lines)
    r = done["r"].astype(float)
    eq = r.cumsum()
    dd = (eq.cummax() - eq).max()
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    lines += [f"win rate: {100 * (r > 0).mean():.1f}%   avg R: {r.mean():+.2f}   expectancy total: {r.sum():+.1f}R",
              f"profit factor: {gp / gl if gl else float('inf'):.2f}   max drawdown: {dd:.1f}R   trades: {len(r)}"]
    for side, g in done.groupby("side"):
        lines.append(f"  {side}: n={len(g)} avg R {g['r'].astype(float).mean():+.2f}")
    if len(r) < 30:
        lines.append("WARNING: fewer than 30 trades - result is NOT statistically meaningful.")
    return "\n".join(lines)


def _csv(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return normalize(df)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", default="crypto", choices=list(C.MARKETS))
    ap.add_argument("--symbol")
    ap.add_argument("--profile", default="5m", choices=list(C.PROFILES))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--ltf-csv")
    ap.add_argument("--htf-csv")
    ap.add_argument("--step", type=int, default=1, help="evaluate every N candles (speed)")
    ap.add_argument("--out", default="backtest_trades.csv")
    a = ap.parse_args()
    market, profile = C.MARKETS[a.market], C.PROFILES[a.profile]
    sym = a.symbol or market.symbols[0]
    now = pd.Timestamp.now(tz="UTC")
    if a.ltf_csv and a.htf_csv:
        ltf, htf, daily = _csv(a.ltf_csv), _csv(a.htf_csv), None
    else:
        from smc.providers import get_provider
        prov = get_provider(market)
        if hasattr(prov, "max_bars"):
            prov.max_bars = 50000
        spec = prov.resolve(sym)
        if spec is None:
            sys.exit(f"symbol {sym} not found")
        ltf = prov.candles(spec, profile.ltf, a.days, now)
        htf = prov.candles(spec, profile.htf, max(a.days + 20, profile.htf_days), now)
        daily = prov.candles(spec, "1d", a.days + 10, now) if profile.use_daily else None
    print(f"{sym}: {len(ltf)} {profile.ltf} candles, {len(htf)} {profile.htf} candles", file=sys.stderr)
    df, skipped = run_backtest(ltf, htf, daily, market, profile, sym, step=a.step, progress=True)
    print(summarize(df, skipped))
    if not df.empty:
        df.to_csv(a.out, index=False)
        print(f"trades saved to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
