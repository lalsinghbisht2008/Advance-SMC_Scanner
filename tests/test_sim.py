import numpy as np
import pytest

from smc.sim import simulate_trade

# long trade: entry 100, sl 98 (risk 2), tp1 104 (2R), tp2 108 (4R)
E, SL, T1, T2 = 100.0, 98.0, 104.0, 108.0


def sim(h, l, c=None, side="BUY", **kw):
    c = c if c is not None else [(a + b) / 2 for a, b in zip(h, l)]
    return simulate_trade(h, l, c, side, E, SL, T1, T2, 0, **kw)


def test_pending_until_price_reaches_entry():
    r = sim([103, 102.5], [101, 100.5])
    assert r["status"] == "PENDING" and r["fill_idx"] is None and r["r"] is None


def test_fill_then_sl():
    r = sim([103, 101, 100.5], [100.5, 99.5, 97.9])
    assert r["status"] == "CLOSED_SL" and r["r"] == -1.0
    assert [e[0] for e in r["events"]] == ["FILLED", "SL"]


def test_same_candle_fill_and_sl_is_a_loss():
    r = sim([103, 101], [99.0, 97.0][:1] + [97.0])  # candle0 low 99 fills, candle1 low 97 stops
    assert r["status"] == "CLOSED_SL"
    r2 = sim([101], [97.5])                          # one candle trades through entry AND sl
    assert r2["status"] == "CLOSED_SL" and r2["fill_idx"] == 0


def test_fill_candle_cannot_take_profit():
    r = sim([105], [99.5])                           # fills (low<=100) and high>=tp1 in the same candle
    assert r["status"] == "OPEN" and r["fill_idx"] == 0


def test_tp1_then_tp2():
    h = [101, 103, 104.5, 106, 108.5]
    l = [99.5, 100.5, 102.0, 104.0, 105.0]
    r = sim(h, l)
    assert r["status"] == "CLOSED_TP2"
    assert [e[0] for e in r["events"]] == ["FILLED", "TP1", "TP2"]
    assert r["r"] == pytest.approx(0.5 * 2 + 0.5 * 4)


def test_tp1_then_break_even():
    h = [101, 104.5, 103, 102]
    l = [99.5, 101.0, 99.0, 99.0]                    # after TP1 the stop is at entry (100)
    r = sim(h, l)
    assert r["status"] == "CLOSED_BE" and r["r"] == pytest.approx(0.5 * 2)
    assert r["events"][-1][0] == "BE"


def test_open_after_tp1_reports_tp1_status():
    r = sim([101, 104.5, 105], [99.5, 101.0, 102.0])
    assert r["status"] == "TP1" and r["r"] is None


def test_cancelled_if_target_reached_without_fill():
    r = sim([103, 104.2], [101, 101.5])
    assert r["status"] == "CANCELLED"


def test_expiry():
    r = sim([103] * 6, [101] * 6, expire_bars=5)
    assert r["status"] == "EXPIRED"


def test_eod_exit_open_position_and_pending():
    eod = np.array([False, False, True])
    r = sim([101, 102, 102], [99.5, 100.5, 100.5], c=[100.5, 101, 101], eod=eod)
    assert r["status"] == "CLOSED_EOD" and r["r"] == pytest.approx(0.5)
    r2 = sim([103, 103, 103], [101, 101, 101], eod=eod)
    assert r2["status"] == "EXPIRED"


def test_short_side_mirrors_long():
    # short: entry 100, sl 102, tp1 96, tp2 92
    r = simulate_trade([100.5, 99, 97, 95.5, 91], [99.0, 97.5, 95.0, 93.0, 90.5],
                       [99.5, 98, 96, 94, 91], "SELL", 100, 102, 96, 92, 0)
    assert r["status"] == "CLOSED_TP2"
    assert [e[0] for e in r["events"]] == ["FILLED", "TP1", "TP2"]
    assert r["events"][0][2] == 100 and r["events"][1][2] == 96          # prices reported un-inverted
    assert r["r"] == pytest.approx(0.5 * 2 + 0.5 * 4)


def test_bad_levels_raise():
    with pytest.raises(ValueError):
        simulate_trade([1], [1], [1], "BUY", 100, 101, 105, 110, 0)
