import json

import numpy as np
import pandas as pd
import pytest

from smc import config as C
from smc.config import Market
from smc.engine import Params
from smc.notifier import Telegram, _split, event_message, fmt_price, setup_message
from smc.runner import scan_market
from smc.state import State
from smc.strategy import analyze
from smc.tracker import trade_from_setup, update_trade
from smc.utils import drop_unclosed, normalize, resample_ohlcv, staleness_minutes
from tests.synth import build


# ------------------------------------------------------------------ markets / candles
def test_nse_session_helpers():
    m = C.MARKETS["india"]
    ts = pd.Timestamp("2026-11-09 03:45", tz="UTC")                      # 09:15 IST Monday
    assert m.session_end(ts) == pd.Timestamp("2026-11-09 10:00", tz="UTC")   # 15:30 IST
    assert m.is_open(pd.Timestamp("2026-11-09 04:00", tz="UTC"))
    assert not m.is_open(pd.Timestamp("2026-11-09 11:00", tz="UTC"))             # after close
    assert m.is_open(pd.Timestamp("2026-11-09 10:05", tz="UTC"))                  # grace for last candle
    assert not m.is_open(pd.Timestamp("2026-11-08 05:00", tz="UTC"))             # Sunday
    assert m.in_killzone(pd.Timestamp("2026-11-09 04:30", tz="UTC"))             # 10:00 IST
    assert not m.in_killzone(pd.Timestamp("2026-11-09 07:30", tz="UTC"))         # 13:00 IST (lunch)


def test_eod_flags_mark_last_5m_candle_of_each_day():
    m = C.MARKETS["india"]
    idx = pd.date_range("2026-11-09 03:45", "2026-11-09 09:55", freq="5min", tz="UTC").append(
        pd.date_range("2026-11-10 03:45", "2026-11-10 04:00", freq="5min", tz="UTC"))
    f = m.eod_flags(idx, pd.Timedelta(minutes=5))
    assert f.sum() == 1 and idx[f][0] == pd.Timestamp("2026-11-09 09:55", tz="UTC")   # 15:25 IST candle


def test_forex_week_and_crypto_always_open():
    fx, cr = C.MARKETS["forex"], C.MARKETS["crypto"]
    assert fx.is_open(pd.Timestamp("2026-11-10 12:00", tz="UTC"))
    assert not fx.is_open(pd.Timestamp("2026-11-14 12:00", tz="UTC"))            # Saturday
    assert not fx.is_open(pd.Timestamp("2026-11-13 22:30", tz="UTC"))            # Friday after close
    assert fx.is_open(pd.Timestamp("2026-11-15 23:00", tz="UTC"))                # Sunday evening open
    assert cr.is_open(pd.Timestamp("2026-11-14 03:00", tz="UTC"))


def test_drop_unclosed_removes_forming_candle_but_keeps_last_nse_hour():
    m = C.MARKETS["india"]
    idx = pd.to_datetime(["2026-11-09 09:15", "2026-11-09 10:15", "2026-11-09 14:15", "2026-11-09 15:15"]) \
        .tz_localize("Asia/Kolkata").tz_convert("UTC")
    df = normalize(pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1}, index=idx))
    mid = pd.Timestamp("2026-11-09 15:20", tz="Asia/Kolkata").tz_convert("UTC")
    assert len(drop_unclosed(df, "1h", mid, m.session_end)) == 3          # 15:15 candle still forming
    after = pd.Timestamp("2026-11-09 15:31", tz="Asia/Kolkata").tz_convert("UTC")
    assert len(drop_unclosed(df, "1h", after, m.session_end)) == 4        # session over -> it is closed
    assert len(drop_unclosed(df, "1h", after)) == 3                        # without session info it would wrongly drop


def test_resample_nse_aligned_hours():
    idx = pd.date_range("2026-11-09 03:45", periods=24, freq="5min", tz="UTC")     # 09:15-11:15 IST
    df = normalize(pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx))
    out = resample_ohlcv(df, "1h", origin=idx[0])
    assert list(out.index) == [idx[0], idx[0] + pd.Timedelta(hours=1)] and out["volume"].iloc[0] == 12


# ------------------------------------------------------------------ telegram
class TgHttp:
    def __init__(self, replies):
        self.replies, self.posts = list(replies), []

    def post(self, url, json=None, timeout=0):
        self.posts.append((url, json))
        r = self.replies.pop(0)
        return r


class R:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)

    def json(self):
        return self._b


def test_telegram_ok_and_html_mode():
    http = TgHttp([R(200, {"ok": True})])
    tg = Telegram("TOKEN", "123", session=http)
    assert tg.send("hi <b>x</b>") and http.posts[0][1]["parse_mode"] == "HTML"


def test_telegram_failure_is_reported_not_swallowed(caplog):
    tg = Telegram("TOKEN", "123", session=TgHttp([R(400, {"ok": False, "description": "can't parse entities"})]))
    assert tg.send("x") is False and tg.failed == 1
    assert "TOKEN" not in caplog.text                                   # token never logged


def test_telegram_retries_on_429(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    tg = Telegram("T", "1", session=TgHttp([R(429, {"parameters": {"retry_after": 1}}), R(200, {"ok": True})]))
    assert tg.send("x") is True


def test_telegram_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert Telegram().send("x") is False


def test_message_split_limit():
    parts = _split("\n".join(["line"] * 3000))
    assert len(parts) > 1 and all(len(p) <= 4100 for p in parts)


def _first_trade(mode="pending", **kw):
    ltf, htf = build(mode)
    m = C.MARKETS["crypto"]
    now = ltf.index[-1] + pd.Timedelta(minutes=5, seconds=3)
    setups, closed, note = analyze(m, C.PROFILES["5m"], "M&M", {"ltf": ltf, "htf": htf}, now)
    assert setups, note
    return trade_from_setup(setups[0], m, now), ltf, htf, now


def test_setup_message_escapes_html_and_has_levels():
    t, *_ = _first_trade()
    t["symbol"] = "M&M <test>"
    msg = setup_message(t)
    assert "M&amp;M &lt;test&gt;" in msg and "<test>" not in msg
    assert "Entry" in msg and "SL" in msg and "TP1" in msg and "BUY" in msg


def test_index_alert_has_option_hint():
    t, *_ = _first_trade()
    t["symbol"] = "NIFTY"
    t["entry"] = 24512.0
    assert "ATM ~24500 CE" in setup_message(t)


def test_fmt_price_ranges():
    assert fmt_price(83072.4687) == "83,072.47" and fmt_price(1.08512) == "1.08512" and fmt_price(0.000123) == "0.000123"


# ------------------------------------------------------------------ state
def test_state_roundtrip_and_atomic_files(tmp_path):
    st = State(tmp_path)
    st.add({"id": "a", "market": "m", "symbol": "S", "profile": "5m"})
    st.close("a", {"r": 1.5})
    st.save()
    st2 = State(tmp_path)
    assert st2.active == {} and st2.history[0]["r"] == 1.5 and st2.seen("a")
    assert not list(tmp_path.glob("*.tmp"))
    (tmp_path / "active.json").write_text("{broken")                        # corrupt file must not crash
    assert State(tmp_path).active == {}


def test_throttle(tmp_path):
    st = State(tmp_path)
    assert st.throttle("k", 100, 1000.0) and not st.throttle("k", 100, 1050.0) and st.throttle("k", 100, 1101.0)


# ------------------------------------------------------------------ tracker + end-to-end
def test_tracker_events_are_reported_once_and_in_order():
    t, ltf, htf, now = _first_trade("trigger")
    p = Params()
    m = C.MARKETS["crypto"]
    new, closed = update_trade(t, ltf, m, p)                                   # silent sync (as runner does on create)
    assert [e[0] for e in new] == ["FILLED"] and not closed
    # price rallies through TP1 then TP2
    ts = ltf.index[-1]
    rows = []
    for i, (hi, lo) in enumerate([(102.0, 100.2), (106.0, 101.5), (109.0, 105.0), (111.0, 108.0)], 1):
        rows.append((ts + pd.Timedelta(minutes=5 * i), 101, hi, lo, hi - 0.2, 1000.0))
    more = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    ltf2 = pd.concat([ltf, more])
    new, closed = update_trade(t, ltf2, m, p)
    assert [e[0] for e in new] == ["TP1", "TP2"] and closed and t["status"] == "CLOSED_TP2"
    assert t["r"] == pytest.approx(0.5 * t["rr1"] + 0.5 * t["rr2"])
    new, closed = update_trade(t, ltf2, m, p)                                  # idempotent
    assert new == []


class FakeProvider:
    def __init__(self, ltf, htf):
        self.ltf, self.htf = ltf, htf

    def resolve(self, s):
        return s

    def fetch_frames(self, spec, profile, now):
        return {"ltf": self.ltf, "htf": self.htf}


class Capture(Telegram):
    def __init__(self):
        super().__init__("t", "c")
        self.msgs = []

    def send(self, text):
        self.msgs.append(text)
        return True


def test_end_to_end_alert_once_then_lifecycle(tmp_path):
    ltf, htf = build("trigger")
    m = Market(name="test", provider="binance", tz="UTC", symbols=["AAA"], kind="24x7", label="Test")
    st, tg = State(tmp_path), Capture()
    cut = ltf.iloc[:-4]                                                        # MSS + 2 shallow retrace candles (IDM not taken)
    now1 = cut.index[-1] + pd.Timedelta(minutes=5, seconds=5)
    h1 = htf[(htf.index + pd.Timedelta(hours=1)) <= now1]
    s1 = scan_market(m, ["5m"], st, tg, now1, provider=FakeProvider(cut, h1))
    assert s1["alerts"] == 1 and len(tg.msgs) == 1 and "WATCH" in tg.msgs[0] and "IDM" in tg.msgs[0]
    scan_market(m, ["5m"], st, tg, now1, provider=FakeProvider(cut, h1))      # same candles -> no duplicate
    assert len(tg.msgs) == 1
    now2 = ltf.index[-1] + pd.Timedelta(minutes=5, seconds=5)                  # price retraced into the zone
    scan_market(m, ["5m"], st, tg, now2, provider=FakeProvider(ltf, htf))
    assert [("IDM TAKEN" in m) or ("ENTRY FILLED" in m) for m in tg.msgs[1:]] == [True, True]
    assert "IDM TAKEN" in tg.msgs[1] and "ENTRY FILLED" in tg.msgs[2]
    t = list(st.active.values())[0]
    assert t["status"] == "OPEN"
    rows = [(ltf.index[-1] + pd.Timedelta(minutes=5 * i), 101, hi, lo, hi - 0.2, 1000.0)
            for i, (hi, lo) in enumerate([(106.0, 100.5), (109.0, 105.0), (111.0, 108.0)], 1)]
    ltf3 = pd.concat([ltf, pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")])
    now3 = ltf3.index[-1] + pd.Timedelta(minutes=5, seconds=5)
    scan_market(m, ["5m"], st, tg, now3, provider=FakeProvider(ltf3, htf))
    kinds = [x for x in tg.msgs[3:]]
    assert any("TP1 HIT" in x for x in kinds) and any("TP2 HIT" in x for x in kinds)
    assert st.active == {} and st.history[-1]["status"] == "CLOSED_TP2"
    n = len(tg.msgs)
    scan_market(m, ["5m"], st, tg, now3, provider=FakeProvider(ltf3, htf))
    assert len(tg.msgs) == n                                                   # nothing re-sent


def test_stale_data_is_detected_and_blocks_signals():
    ltf, htf = build("pending")
    m = C.MARKETS["crypto"]
    late = ltf.index[-1] + pd.Timedelta(hours=3)
    setups, _, note = analyze(m, C.PROFILES["5m"], "X", {"ltf": ltf, "htf": htf}, late)
    assert setups == [] and note == "stale data"
    assert staleness_minutes(ltf, "5m", late) > 100


def test_dry_run_changes_nothing(tmp_path):
    ltf, htf = build("pending")
    m = Market(name="test", provider="binance", tz="UTC", symbols=["AAA"], kind="24x7", label="Test")
    st, tg = State(tmp_path), Capture()
    now = ltf.index[-1] + pd.Timedelta(minutes=5, seconds=5)
    from smc.runner import run_once
    scan_market(m, ["5m"], st, tg, now, dry_run=True, provider=FakeProvider(ltf, htf))
    assert tg.msgs == []                              # nothing sent
