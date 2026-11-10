#!/usr/bin/env python3
"""SMC Scanner v2 - single entry point.

  python run.py scan --market auto               # one pass over every market that is open now
  python run.py scan --market india --dry-run    # print only, no Telegram, no state changes
  python run.py loop --market india,crypto       # run forever (local server)
  python run.py selftest                         # check tokens / data / Telegram
  python run.py test-telegram
  python run.py summary                          # send trade-result summary to Telegram
  python backtest.py --help
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from smc import config as C
from smc.notifier import Telegram
from smc.runner import loop, open_markets, run_once
from smc.state import State


def _markets(arg: str, now: pd.Timestamp) -> list:
    if arg == "auto":
        return open_markets(now)
    names = [x.strip() for x in arg.split(",") if x.strip()]
    bad = [n for n in names if n not in C.MARKETS]
    if bad:
        sys.exit(f"Unknown market(s) {bad}. Choose from {list(C.MARKETS)} or 'auto'.")
    return names


def _profiles(arg):
    if not arg:
        return None
    names = [x.strip() for x in arg.split(",")]
    bad = [n for n in names if n not in C.PROFILES]
    if bad:
        sys.exit(f"Unknown profile(s) {bad}. Choose from {list(C.PROFILES)}.")
    return names


def cmd_selftest(args) -> int:
    from smc.providers import get_provider
    from smc.utils import drop_unclosed, staleness_minutes
    now = pd.Timestamp.now(tz="UTC")
    ok = True
    tg = Telegram()
    print(f"Telegram configured : {tg.enabled}")
    if tg.enabled and args.telegram:
        print(f"Telegram test send  : {'OK' if tg.send('✅ SMC scanner v2 selftest') else 'FAILED'}")
    for name in _markets(args.market, now) if args.market != "auto" else list(C.MARKETS):
        m = C.MARKETS[name]
        prof = C.PROFILES[C.DEFAULT_PROFILES[name][0]]
        print(f"\n== {name} ({m.provider}) open_now={m.is_open(now)}")
        try:
            prov = get_provider(m)
            if m.provider == "upstox":
                from smc.providers.upstox import token_days_left
                left = token_days_left(prov.token)
                print(f"  token set: {bool(prov.token)}  days left: {None if left is None else round(left, 1)}")
            sym = args.symbol or m.symbols[0]
            spec = prov.resolve(sym)
            print(f"  symbol {sym} -> {spec}")
            if spec is None:
                ok = False
                continue
            raw = prov.fetch_frames(spec, prof, now)
            for k, tf in (("ltf", prof.ltf), ("htf", prof.htf)):
                df = raw[k]
                closed = drop_unclosed(df, tf, now, m.session_end)
                age = staleness_minutes(closed, tf, now)
                print(f"  {k} {tf}: {len(df)} candles, {len(closed)} closed, last closed "
                      f"{closed.index[-1] if len(closed) else '-'}  age={age:.0f} min")
        except Exception as e:
            ok = False
            print(f"  FAILED: {type(e).__name__}: {e}")
    return 0 if ok else 1


def cmd_summary(args) -> int:
    st = State()
    today = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    rows = [h for h in st.history if (h.get("exit_time") or "")[:10] == today or
            pd.Timestamp(h.get("exit_time", "1970-01-01")).tz_convert("Asia/Kolkata").strftime("%Y-%m-%d") == today]
    rs = [h["r"] for h in rows if h.get("r") is not None]
    txt = (f"📊 <b>Daily summary</b> {today}\nClosed: {len(rs)} · Wins: {sum(r > 0 for r in rs)} · "
           f"Net: <b>{sum(rs):+.2f}R</b>\nStill open/pending: {len(st.active)}")
    print(txt)
    if args.send:
        Telegram().send(txt)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "loop"):
        s = sub.add_parser(name)
        s.add_argument("--market", default="auto", help="auto | india,mcx,crypto,forex")
        s.add_argument("--profile", help="5m,15m,swing (default per market)")
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--symbols", help="comma list, to scan only these")
        if name == "loop":
            s.add_argument("--every", type=int, default=5, help="minutes between scans")
    t = sub.add_parser("selftest")
    t.add_argument("--market", default="auto")
    t.add_argument("--symbol")
    t.add_argument("--telegram", action="store_true", help="also send a Telegram test message")
    sub.add_parser("test-telegram")
    sm = sub.add_parser("summary")
    sm.add_argument("--send", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    now = pd.Timestamp.now(tz="UTC")

    if args.cmd == "scan":
        mk = _markets(args.market, now)
        if not mk:
            logging.info("No selected market is open right now - nothing to do.")
            return 0
        only = [x.strip() for x in args.symbols.split(",")] if args.symbols else None
        run_once(mk, _profiles(args.profile), args.dry_run, only, now)
        return 0
    if args.cmd == "loop":
        names = list(C.MARKETS) if args.market == "auto" else _markets(args.market, now)
        loop(names, _profiles(args.profile), args.dry_run, args.every)
        return 0
    if args.cmd == "selftest":
        return cmd_selftest(args)
    if args.cmd == "test-telegram":
        tg = Telegram()
        ok = tg.send("✅ <b>SMC scanner v2</b> - Telegram connection OK")
        print("sent" if ok else "FAILED (check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return 0 if ok else 1
    if args.cmd == "summary":
        return cmd_summary(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
