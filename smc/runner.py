"""Orchestration: fetch -> analyse -> alert -> track.  Used by run.py (cron/GitHub) and loop mode."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pandas as pd

from . import config as C
from .notifier import Telegram, event_message, health_message, setup_message
from .providers import AuthError, DataError, get_provider
from .state import State
from .strategy import analyze, params_for
from .tracker import trade_from_setup, update_trade

log = logging.getLogger("smc.run")


BATCH_FILE = C.CACHE_DIR / "batch_ptr.json"


def load_symbols_file(path: str) -> list:
    """One symbol per line (or comma separated). Dedupes, keeps order, ignores # comments."""
    out, seen = [], set()
    for line in open(path, encoding="utf-8"):
        for tok in line.split("#")[0].replace(",", " ").split():
            tok = tok.strip().upper()
            if tok and tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def select_batch(market: str, symbols: list, size: int, path=BATCH_FILE) -> tuple:
    """Next `size` symbols, wrapping around. Pointer is stored on disk, so every new run
    (even a separate manual command, even with --dry-run) continues where the last one stopped.
    Returns (batch, start_index, total)."""
    import json
    try:
        ptr = json.loads(open(path).read())
    except Exception:
        ptr = {}
    n = len(symbols)
    start = int(ptr.get(market, 0)) % n if n else 0
    batch = [symbols[(start + i) % n] for i in range(min(size, n))]
    ptr[market] = (start + len(batch)) % n if n else 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        open(path, "w").write(json.dumps(ptr))
    except OSError:
        pass
    return batch, start, n


def open_markets(now: pd.Timestamp, names=None) -> list:
    names = names or list(C.MARKETS)
    return [n for n in names if C.MARKETS[n].is_open(now)]


_PROVIDERS: dict = {}


def _provider_for(market):
    if market.name not in _PROVIDERS:
        _PROVIDERS[market.name] = get_provider(market)
    return _PROVIDERS[market.name]


def _fetch_one(provider, market, profile, symbol, spec, now):
    try:
        return symbol, provider.fetch_frames(spec, profile, now), None
    except AuthError:
        raise
    except DataError as e:
        return symbol, None, str(e)
    except Exception as e:                           # never let one symbol kill the scan
        return symbol, None, f"{type(e).__name__}: {e}"


def scan_market(market: C.Market, profile_names: list, state: State, tg: Telegram, now: pd.Timestamp,
                dry_run: bool = False, only: Optional[list] = None, provider=None) -> dict:
    stats = dict(market=market.name, symbols=0, setups=0, alerts=0, events=0, errors=0, stale=0)
    provider = provider or _provider_for(market)
    symbols = [s for s in (only or market.symbols)]
    for t in state.active.values():                  # always keep tracking open trades
        if t["market"] == market.name and t["symbol"] not in symbols:
            symbols.append(t["symbol"])

    specs = {}
    for s in symbols:
        try:
            spec = provider.resolve(s)
        except Exception as e:
            log.warning("%s: resolve failed (%s)", s, e)
            spec = None
        if spec is None:
            log.warning("%s: symbol not found on %s - skipped", s, market.provider)
            stats["errors"] += 1
            continue
        specs[s] = spec
    stats["symbols"] = len(specs)

    for pname in profile_names:
        profile = C.PROFILES[pname]
        p = params_for(market, profile)
        try:
            with ThreadPoolExecutor(max_workers=C.SCAN_WORKERS) as ex:
                results = list(ex.map(lambda kv: _fetch_one(provider, market, profile, kv[0], kv[1], now),
                                      specs.items()))
        except AuthError as e:
            msg = f"{market.label}: {e}. Naya token generate karke secret update karein."
            log.error(msg)
            if not dry_run and state.throttle(f"auth_{market.name}", 6 * 3600, time.time()):
                tg.send(health_message("Data token problem", msg))
            stats["errors"] += 1
            return stats

        for symbol, raw, err in results:
            if err or raw is None:
                stats["errors"] += 1
                log.warning("%s/%s: %s", market.name, symbol, err)
                continue
            setups, ltf_closed, note = analyze(market, profile, symbol, raw, now, p)
            if note == "stale data":
                stats["stale"] += 1
            # 1) update already-tracked trades of this symbol/profile
            for t in list(state.active_for(market.name, symbol, pname)):
                new, closed = update_trade(t, ltf_closed, market, p)
                state.touch()
                for kind, ts, price in new:
                    stats["events"] += 1
                    if not dry_run:
                        tg.send(event_message(t, kind, price, ts, t["r"] if closed else None))
                    else:
                        log.info("[dry] %s %s %s @ %s", t["symbol"], t["side"], kind, price)
                if closed:
                    state.close(t["id"], {})
            # 2) brand-new setups
            for s in setups:
                stats["setups"] += 1
                if state.seen(s.id):
                    continue
                if len(state.active_for(market.name, symbol, pname)) >= C.MAX_ACTIVE_PER_SYMBOL:
                    continue
                if s.state == "PENDING" and not C.ALERT_PENDING:
                    continue
                trade = trade_from_setup(s, market, now)
                update_trade(trade, ltf_closed, market, p)   # silently sync events already in the past
                state.add(trade)
                stats["alerts"] += 1
                msg = setup_message(trade)
                if dry_run:
                    log.info("[dry] NEW SETUP\n%s", msg)
                else:
                    tg.send(msg)

        # health: most symbols stale while market is open
        if results and stats["stale"] >= max(3, len(results) // 2) and not dry_run:
            if state.throttle(f"stale_{market.name}", 6 * 3600, time.time()):
                tg.send(health_message(
                    "Stale data", f"{market.label}: {stats['stale']}/{len(results)} symbols ka data purana hai "
                                  f"(market open). API/token/holiday check karein."))

    stats["api_calls"] = getattr(provider, "calls", None)
    if market.provider == "upstox":
        from .providers.upstox import token_days_left
        left = token_days_left(provider.token)
        if left is not None and left < 14 and not dry_run and state.throttle("token_expiry", 24 * 3600, time.time()):
            tg.send(health_message("Upstox token expiring", f"Sirf {left:.0f} din bache hain - naya Analytics Token banayein."))
    return stats


def run_once(market_names: list, profile_names: Optional[list] = None, dry_run: bool = False,
             only: Optional[list] = None, now: Optional[pd.Timestamp] = None,
             state: Optional[State] = None, tg: Optional[Telegram] = None,
             batch_size: int = 0) -> list:
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    state = state or State()
    tg = tg or Telegram()
    out = []
    for name in market_names:
        m = C.MARKETS[name]
        profiles = profile_names or C.DEFAULT_PROFILES[name]
        t0 = time.time()
        scan_only = only
        if batch_size:
            universe = only or m.symbols
            scan_only, start, total = select_batch(name, universe, batch_size)
            log.info("%s batch: symbols %d-%d of %d", name, start + 1, start + len(scan_only), total)
        try:
            st = scan_market(m, profiles, state, tg, now, dry_run=dry_run, only=scan_only)
        except Exception as e:
            log.exception("scan of %s crashed", name)
            st = dict(market=name, error=f"{type(e).__name__}: {e}")
            if not dry_run and state.throttle(f"crash_{name}", 3600, time.time()):
                tg.send(health_message("Scanner error", f"{name}: {type(e).__name__}: {e}"))
        st["secs"] = round(time.time() - t0, 1)
        out.append(st)
        log.info("scan %s", st)
    if not dry_run:
        state.save()
    return out


def loop(market_names: list, profile_names=None, dry_run=False, every_min: int = 5,
         only=None, batch_size: int = 0):
    """Long-running mode for your local server: wakes up a few seconds after every
    `every_min` boundary (so the just-closed candle is available)."""
    state, tg = State(), Telegram()
    log.info("loop started: markets=%s every %d min", market_names, every_min)
    while True:
        now = pd.Timestamp.now(tz="UTC")
        active = open_markets(now, market_names)
        if active:
            run_once(active, profile_names, dry_run, only=only, now=now, state=state, tg=tg, batch_size=batch_size)
        else:
            log.info("all selected markets closed")
        nxt = (now.floor(f"{every_min}min") + pd.Timedelta(minutes=every_min, seconds=6))
        time.sleep(max(5, (nxt - pd.Timestamp.now(tz="UTC")).total_seconds()))
