import numpy as np
import pandas as pd
import pytest

from smc.engine import Frame, Info, Params, find_setups, _pivots
from smc.utils import drop_unclosed, resample_ohlcv
from tests.synth import build, mirror

P = Params(min_score=5)


def run(ltf, htf, p=P, info=None):
    return find_setups(ltf, htf, None, "5m", "1h", p, info or Info())


def best(res, side):
    r = [s for s in res if s.side == side]
    return max(r, key=lambda s: s.score) if r else None


def test_bullish_sweep_mss_setup_pending():
    ltf, htf = build("pending")
    s = best(run(ltf, htf), "BUY")
    assert s is not None and s.state == "PENDING"
    assert s.sweep_extreme < s.pool_level < s.mss_level          # wick below pool, MSS above
    assert s.sl < s.sweep_extreme                                # SL beyond sweep extreme
    assert s.sl < s.entry < s.tp1 < s.tp2
    assert s.ob is not None and s.fvg is not None
    assert s.ob[0] <= s.entry <= s.ob[1]                         # entry inside the order block
    assert s.rr1 >= P.min_rr


def test_bullish_triggered_when_price_trades_into_zone():
    ltf, htf = build("trigger")
    s = best(run(ltf, htf), "BUY")
    assert s is not None and s.state == "TRIGGERED" and s.trigger_time is not None


@pytest.mark.parametrize("mode", ["pending", "trigger"])
def test_bearish_is_exact_mirror_of_bullish(mode):
    ltf, htf = build(mode)
    a = best(run(ltf, htf), "BUY")
    b = best(run(mirror(ltf), mirror(htf)), "SELL")
    assert b is not None and a.state == b.state
    for f in ("entry", "sl", "tp1", "tp2", "pool_level", "sweep_extreme", "mss_level"):
        assert 210 - getattr(b, f) == pytest.approx(getattr(a, f), abs=1e-9), f
    assert b.sl > b.entry > b.tp1 > b.tp2                         # short geometry
    assert b.zone_pd == "premium"


def test_breakdown_without_reclaim_is_not_a_sweep():
    ltf, htf = build("pending", reclaim=False)
    assert best(run(ltf, htf, Params(min_score=0)), "BUY") is None


def test_no_mss_no_setup():
    ltf, htf = build("pending")
    cut = ltf.iloc[:-5]                                           # remove displacement + MSS candles
    h = htf[(htf.index + pd.Timedelta(hours=1)) <= cut.index[-1] + pd.Timedelta(minutes=5)]
    assert best(run(cut, h, Params(min_score=0)), "BUY") is None


def test_setup_dies_if_sl_is_hit_before_entry_fill():
    ltf, htf = build("pending")
    n = len(ltf)
    extra = ltf.iloc[-1:].copy()
    ts = ltf.index[-1] + pd.Timedelta(minutes=5)
    ltf2 = pd.concat([ltf, pd.DataFrame({"open": [104.1], "high": [104.2], "low": [97.5], "close": [97.9],
                                         "volume": [1000.0]}, index=[ts])])
    h = htf[(htf.index + pd.Timedelta(hours=1)) <= ltf2.index[-1] + pd.Timedelta(minutes=5)]
    assert best(run(ltf2, h, Params(min_score=0)), "BUY") is None


def test_old_pending_setup_expires():
    ltf, htf = build("pending")
    p = Params(min_score=0, max_age_bars=10)
    rows = []
    ts = ltf.index[-1]
    for i in range(1, 14):                                        # 13 quiet candles far above the zone
        rows.append((ts + pd.Timedelta(minutes=5 * i), 104.1, 104.3, 103.9, 104.1, 1000.0))
    ext = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    ltf2 = pd.concat([ltf, ext])
    h = htf[(htf.index + pd.Timedelta(hours=1)) <= ltf2.index[-1] + pd.Timedelta(minutes=5)]
    assert best(run(ltf2, h, p), "BUY") is None


def test_premium_discount_filter(monkeypatch):
    import smc.engine as E
    ltf, htf = build("pending")
    monkeypatch.setattr(E, "dealing_range", lambda f: (101.0, 99.0))   # equilibrium 100 < entry 100.13
    assert best(run(ltf, htf, Params(min_score=0, require_discount=True)), "BUY") is None
    s = best(run(ltf, htf, Params(min_score=0, require_discount=False)), "BUY")
    assert s is not None and s.zone_pd == "premium"


def test_min_score_filters():
    ltf, htf = build("pending")
    assert best(run(ltf, htf, Params(min_score=9)), "BUY") is None


def test_no_repaint_signals_do_not_change_when_more_candles_arrive():
    """Causality: a setup seen at time t keeps the same levels at every later time."""
    ltf, htf_full = build("trigger")
    seen = {}
    for cut in range(len(ltf) - 12, len(ltf) + 1):
        l = ltf.iloc[:cut]
        h = htf_full[(htf_full.index + pd.Timedelta(hours=1)) <= l.index[-1] + pd.Timedelta(minutes=5)]
        for s in run(l, h, Params(min_score=0)):
            key = (s.side, s.mss_time)
            sig = (round(s.entry, 6), round(s.sl, 6), round(s.sweep_extreme, 6), round(s.mss_level, 6))
            if key in seen:
                assert seen[key] == sig, f"setup {key} repainted: {seen[key]} -> {sig}"
            seen[key] = sig
    assert seen, "pattern never detected"


def test_pivots_are_confirmed_only_after_n_bars():
    h = np.array([1, 2, 3, 2, 1, 2, 3, 4, 3, 2.0])
    l = h - 0.5
    ph, pl = _pivots(h, l, 2)
    assert ph == [2, 7] or ph == [2]           # pivot at 2 needs bars 3,4 -> last bar 9 allows index 7 (needs 8,9)
    assert all(i + 2 < len(h) for i in ph)


def _walk(h, l, c, n=1, **kw):
    from smc.engine import _pivots, walk_up
    h, l, c = (np.array(v, float) for v in (h, l, c))
    ph, pl = _pivots(h, l, n)
    return walk_up(h, l, c, ph, pl, n, **kw)


def test_bos_needs_idm_taken_first():
    # leg: low 10 -> pull-back low 11 (IDM) -> high 15; then price CLOSES above 15 WITHOUT first sweeping the 11 low
    h = [11.5, 10.5, 12, 11.6, 11.4, 13, 15, 14.5, 14.8, 16.5, 17]
    l = [11.0, 10.0, 11.5, 11.0, 11.1, 11.8, 14, 13.5, 14.0, 15.0, 16.0]
    c = [11.2, 10.4, 11.9, 11.2, 11.3, 12.9, 14.9, 14.0, 14.7, 16.4, 16.9]
    ev = _walk(h, l, c)["events"]
    assert not any(e["kind"] == "BOS_UP" for e in ev)             # break of 15 without IDM taken is NOT a BOS


def test_idm_taken_then_close_above_hh_is_bos():
    h = [11.5, 10.5, 12, 11.6, 11.4, 13, 15, 14.0, 13.0, 12.5, 14.0, 15.5, 16.5, 16.2]
    l = [11.0, 10.0, 11.5, 11.0, 11.1, 11.8, 14, 12.8, 10.8, 11.5, 12.0, 14.0, 15.5, 15.4]
    c = [11.2, 10.4, 11.9, 11.2, 11.3, 12.9, 14.9, 13.0, 11.2, 12.4, 13.9, 15.4, 16.4, 15.8]
    ev = _walk(h, l, c)["events"]
    kinds = [e["kind"] for e in ev]
    assert kinds[:2] == ["IDM_TAKEN", "BOS_UP"], kinds
    assert ev[0]["level"] == 11.0 and ev[0]["high"] == 15 and ev[1]["level"] == 15


def test_close_below_protected_low_is_choch_down():
    h = [11.5, 10.5, 12, 11.6, 11.4, 13, 15, 14.0, 13.0, 12.5, 14.0, 15.5, 16.5, 16.2, 12, 9]
    l = [11.0, 10.0, 11.5, 11.0, 11.1, 11.8, 14, 12.8, 10.8, 11.5, 12.0, 14.0, 15.5, 15.4, 9, 7]
    c = [11.2, 10.4, 11.9, 11.2, 11.3, 12.9, 14.9, 13.0, 11.2, 12.4, 13.9, 15.4, 16.4, 15.8, 9.5, 7.5]
    ev = _walk(h, l, c)["events"]
    assert [e["kind"] for e in ev][-1] == "CHOCH_DOWN"


def _frame_from(h, l, c, n=1):
    h, l, c = (np.array(v, float) for v in (h, l, c))
    df = pd.DataFrame({"open": c, "high": h, "low": l, "close": c, "volume": 1.0},
                      index=pd.date_range("2026-01-01", periods=len(c), freq="1h", tz="UTC"))
    return df


def test_htf_bias_follows_idm_validated_bos_and_choch():
    from smc.engine import htf_bias
    h = [11.5, 10.5, 12, 11.6, 11.4, 13, 15, 14.0, 13.0, 12.5, 14.0, 15.5, 16.5, 16.2]
    l = [11.0, 10.0, 11.5, 11.0, 11.1, 11.8, 14, 12.8, 10.8, 11.5, 12.0, 14.0, 15.5, 15.4]
    c = [11.2, 10.4, 11.9, 11.2, 11.3, 12.9, 14.9, 13.0, 11.2, 12.4, 13.9, 15.4, 16.4, 15.8]
    up = htf_bias(Frame.from_df(_frame_from(h, l, c), "1h", 1))
    mir = lambda v: [40 - x for x in v]
    dn = htf_bias(Frame.from_df(_frame_from(mir(l), mir(h), mir(c)), "1h", 1))
    # same legs plus the collapse below the protected low -> bias flips bearish
    h2, l2, c2 = h + [12, 9], l + [9, 7], c + [9.5, 7.5]
    flipped = htf_bias(Frame.from_df(_frame_from(h2, l2, c2), "1h", 1))
    assert (up, dn, flipped) == (1, -1, -1)


def test_smooth_wave_without_inducement_gives_no_structure():
    from smc.engine import htf_bias
    t = np.arange(120)
    path = 100 + t * 0.15 + 2.0 * np.sin(t / 3.0)        # higher highs / higher lows but no IDM is ever swept
    df = _frame_from(path + 0.3, path - 0.3, path)
    assert htf_bias(Frame.from_df(df, "1h", 2)) == 0


def test_idm_stage_flags_on_setups():
    ltf, htf = build("pending")
    s = best(run(ltf, htf), "BUY")
    assert s.stage == "WAIT_IDM" and s.idm_level == pytest.approx(101.8) and s.state == "PENDING"
    ltf, htf = build("trigger")
    s = best(run(ltf, htf), "BUY")
    assert s.stage == "ARMED" and s.idm_time is not None and s.hh_level == pytest.approx(105.6)
    assert s.state == "TRIGGERED" and "IDM taken (HH validated)" in s.reasons


def test_setup_without_any_idm_is_rejected_unless_allowed():
    ltf, htf = build("pending")
    n = len(ltf)
    base = ltf.iloc[:n - 8]                                     # everything up to and including the sweep candle
    leg = [(100.35, 102.1, 100.3, 102.0), (102.0, 103.5, 101.95, 103.4), (103.4, 105.0, 103.3, 104.9),
           (104.9, 106.2, 104.8, 106.0), (106.0, 106.1, 105.2, 105.4), (105.4, 105.5, 104.8, 105.0)]
    idx = pd.date_range(base.index[-1] + pd.Timedelta(minutes=5), periods=len(leg), freq="5min", tz="UTC")
    imp = pd.DataFrame([(*r, 4000.0) for r in leg], index=idx, columns=["open", "high", "low", "close", "volume"])
    ltf2 = pd.concat([base, imp])                               # pure impulse: lows only ever rise -> no IDM
    h2 = htf[(htf.index + pd.Timedelta(hours=1)) <= ltf2.index[-1] + pd.Timedelta(minutes=5)]
    assert best(run(ltf2, h2, Params(min_score=0, require_idm=True)), "BUY") is None
    s = best(run(ltf2, h2, Params(min_score=0, require_idm=False)), "BUY")
    assert s is not None and s.stage == "NO_IDM"
