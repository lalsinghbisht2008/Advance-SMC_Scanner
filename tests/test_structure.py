import numpy as np
import pandas as pd

from smc.engine import Frame, Params, htf_idm_state, find_setups, Info
from smc.structure import build_map, state_for
from tests import synth


def _df(h, l, c):
    n = len(c)
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=1.0), index=idx)


def _leg():
    # prefix low (origin) -> up leg with a minor pull-back (IDM) -> high -> retrace sweeps IDM
    c = [10, 8, 9, 11, 12, 11.2, 10.4, 11.5, 13, 12, 11, 9.5, 9.8, 10.5]
    h = [x + .2 for x in c]
    l = [x - .2 for x in c]
    return np.array(h), np.array(l), np.array(c)


def test_state_wait_then_swept():
    h, l, c = _leg()
    full = Frame.from_df(_df(h, l, c), "4h", 1)
    assert htf_idm_state(full)["state"] == "SWEPT"
    early = Frame.from_df(_df(h[:10], l[:10], c[:10]), "4h", 1)
    assert htf_idm_state(early)["state"] in ("WAIT", "NONE")


def test_map_labels_both_sides_real_prices():
    h, l, c = _leg()
    m = build_map(Frame.from_df(_df(h, l, c), "4h", 1), zz=0.0)
    assert any(x[3] == "IDM Sweep" for x in m["lines"])
    assert all(p[1] > 0 for p in m["pts"])
    assert set(state_for(Frame.from_df(_df(h, l, c), "4h", 1))) == {"buy", "sell"}


def test_gate_blocks_ltf_model_until_htf_idm_swept():
    ltf, htf = synth.build("trigger")
    on = find_setups(ltf, htf, None, "5m", "1h", Params(min_score=0, require_htf_idm=False), Info())
    gated = find_setups(ltf, htf, None, "5m", "1h", Params(min_score=0, require_htf_idm=True), Info())
    assert len(gated) <= len(on)
    for s in gated:
        assert s.htf_idm_level is not None and s.htf_idm_time is not None


def test_stale_htf_sweep_expires():
    h, l, c = _leg()
    f = Frame.from_df(_df(h, l, c), "4h", 1)
    assert htf_idm_state(f)["state"] == "SWEPT"
    assert htf_idm_state(f, max_age=0)["state"] != "SWEPT" or htf_idm_state(f)["taken_idx"] == len(f) - 1
    assert htf_idm_state(f, max_age=-1)["state"] != "SWEPT"


def test_zigzag_idm_ignores_small_wiggle():
    from smc.engine import _pivots, walk_up
    # up leg 10->20 with a big pull-back (IDM=14) and a tiny wiggle (IDM-like 18.6) right before the high
    c = [10, 8, 9, 12, 14.5, 13, 14, 16, 17.5, 18.6, 18.2, 19, 20, 19, 17, 13.2, 14, 21]
    h = np.array(c) + .2
    l = np.array(c) - .2
    cc = np.array(c)
    ph, pl = _pivots(h, l, 1)
    f = Frame.from_df(_df(h, l, cc), "4h", 1)
    plain = walk_up(h, l, cc, ph, pl, 1)
    strict = walk_up(h, l, cc, ph, pl, 1, atr=f.atr, zz=1.0)
    p_idm, s_idm = plain["events"], strict["events"]
    assert any(e["kind"] == "IDM_TAKEN" for e in p_idm)
    # strict mode must never pick a level that is a smaller wiggle than the plain one
    if any(e["kind"] == "IDM_TAKEN" for e in s_idm):
        sl = next(e for e in s_idm if e["kind"] == "IDM_TAKEN")["level"]
        pl_ = next(e for e in p_idm if e["kind"] == "IDM_TAKEN")["level"]
        assert sl <= pl_
