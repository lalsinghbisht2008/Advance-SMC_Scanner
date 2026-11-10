import gzip
import json

import pandas as pd
import pytest

from smc.config import MARKETS, PROFILES
from smc.providers.base import AuthError, DataError, RateLimiter
from smc.providers.binance import BinanceProvider, parse_klines
from smc.providers.instruments import InstrumentResolver
from smc.providers.upstox import UpstoxProvider, parse_candles, token_days_left
from smc.providers.yahoo import YahooProvider, parse_chart


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._d, self.text = status, data, text or json.dumps(data)
        self.content = b""

    def json(self):
        return self._d


class FakeHttp:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responder(url, kw)


UP = {"status": "success", "data": {"candles": [
    ["2026-11-09T09:20:00+05:30", 100, 101, 99, 100.5, 1500, 0],
    ["2026-11-09T09:15:00+05:30", 99, 100.2, 98.5, 100, 1000, 0]]}}


def test_upstox_parse_string_timestamps_sorted_utc():
    df = parse_candles(UP)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing and str(df.index.tz) == "UTC"
    assert df.index[0] == pd.Timestamp("2026-11-09 03:45:00", tz="UTC")     # 09:15 IST


def test_upstox_parse_numeric_ms_and_empty():
    d = {"data": {"candles": [[1762661100000, 1, 2, 0.5, 1.5, 10, 0]]}}
    assert parse_candles(d).index[0] == pd.Timestamp(1762661100000, unit="ms", tz="UTC")
    assert parse_candles({"data": {"candles": []}}).empty
    assert parse_candles({}).empty


def test_upstox_urls_history_and_intraday(tmp_path):
    http = FakeHttp(lambda u, k: Resp(200, UP))
    up = UpstoxProvider(token="tok", http=http, limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    now = pd.Timestamp("2026-11-09 06:00", tz="UTC")
    df = up.candles("NSE_EQ|INE002A01018", "5m", 3, now)
    urls = [c[0] for c in http.calls]
    assert any("/v3/historical-candle/NSE_EQ%7CINE002A01018/minutes/5/2026-11-08/2026-11-06" in u for u in urls)
    assert any(u.endswith("/v3/historical-candle/intraday/NSE_EQ%7CINE002A01018/minutes/5") for u in urls)
    assert http.calls[0][1]["headers"]["Authorization"] == "Bearer tok"
    assert not df.empty


def test_upstox_hours_and_days_units(tmp_path):
    http = FakeHttp(lambda u, k: Resp(200, UP))
    up = UpstoxProvider(token="t", http=http, limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    now = pd.Timestamp("2026-11-09 06:00", tz="UTC")
    up.candles("NSE_INDEX|Nifty 50", "4h", 10, now)
    up.candles("NSE_INDEX|Nifty 50", "1d", 10, now)
    urls = " ".join(c[0] for c in http.calls)
    assert "NSE_INDEX%7CNifty%2050/hours/4/" in urls and "/days/1/2026-11-09/2026-10-30" in urls


def test_upstox_history_chunking_for_minutes_over_one_month(tmp_path):
    http = FakeHttp(lambda u, k: Resp(200, UP))
    up = UpstoxProvider(token="t", http=http, limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    up._history("K", "5m", pd.Timestamp("2026-09-01").date(), pd.Timestamp("2026-11-08").date())
    assert len(http.calls) == 3                       # 68 days / 28-day windows


def test_upstox_past_history_is_cached(tmp_path):
    http = FakeHttp(lambda u, k: Resp(200, UP))
    up = UpstoxProvider(token="t", http=http, limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    a = pd.Timestamp("2020-01-01").date()
    b = pd.Timestamp("2020-01-05").date()
    up._history("K", "5m", a, b)
    up._history("K", "5m", a, b)
    assert len(http.calls) == 1


def test_upstox_auth_error_and_bad_request(tmp_path):
    up = UpstoxProvider(token="t", http=FakeHttp(lambda u, k: Resp(401, {})), limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    with pytest.raises(AuthError):
        up._get("http://x")
    bad = Resp(400, {"errors": [{"message": "Invalid instrument key"}]})
    up2 = UpstoxProvider(token="t", http=FakeHttp(lambda u, k: bad), limiter=RateLimiter(100, 1000), cache_dir=tmp_path)
    with pytest.raises(DataError, match="Invalid instrument key"):
        up2._get("http://x")


def test_upstox_missing_token_raises_auth_error(tmp_path, monkeypatch):
    for k in ("UPSTOX_ACCESS_TOKEN", "UPSTOX_ANALYTICS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    up = UpstoxProvider(token="", http=FakeHttp(lambda u, k: Resp(200, UP)), cache_dir=tmp_path)
    with pytest.raises(AuthError):
        up._get("http://x")


def test_token_expiry_reader():
    import base64, time
    payload = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 10 * 86400}).encode()).decode().rstrip("=")
    assert 9.9 < token_days_left(f"h.{payload}.s") < 10.1
    assert token_days_left("not-a-jwt") is None


def test_instrument_resolver(tmp_path):
    rows = [
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE", "instrument_key": "NSE_EQ|INE002A01018"},
        {"segment": "NSE_EQ", "instrument_type": "BE", "trading_symbol": "JUNK", "instrument_key": "NSE_EQ|X"},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLD", "instrument_key": "MCX_FO|1",
         "expiry": int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000)},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLD", "instrument_key": "MCX_FO|2",
         "expiry": int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=20)).timestamp() * 1000)},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLD", "instrument_key": "MCX_FO|3",
         "expiry": int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=50)).timestamp() * 1000)},
        {"segment": "MCX_FO", "instrument_type": "FUT", "underlying_symbol": "GOLDM", "instrument_key": "MCX_FO|9",
         "expiry": int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=20)).timestamp() * 1000)},
    ]
    r = Resp(200, None)
    r.content = gzip.compress(json.dumps(rows).encode())
    r.raise_for_status = lambda: None
    http = FakeHttp(lambda u, k: r)
    res = InstrumentResolver(http, tmp_path)
    assert res.equity("RELIANCE") == "NSE_EQ|INE002A01018"
    assert res.equity("JUNK") is None and res.equity("NOPE") is None
    assert res.resolve("NIFTY", "india") == "NSE_INDEX|Nifty 50"
    assert res.future("GOLD", "MCX") == "MCX_FO|2"          # skips the contract expiring tomorrow, not GOLDM
    assert len(http.calls) == 2                              # NSE + MCX downloaded once each (then cached)


def test_binance_parse_and_host_fallback():
    rows = [[1762661100000, "1", "2", "0.5", "1.5", "10", 0, 0, 0, 0, 0, 0],
            [1762661400000, "1.5", "2.5", "1", "2", "11", 0, 0, 0, 0, 0, 0]]
    df = parse_klines(rows)
    assert len(df) == 2 and df["close"].iloc[-1] == 2.0 and str(df.index.tz) == "UTC"

    seq = iter([Resp(451, {}, "restricted"), Resp(200, rows)])
    http = FakeHttp(lambda u, k: next(seq))
    out = BinanceProvider(http).candles("BTCUSDT", "5m", 1, pd.Timestamp.now(tz="UTC"))
    assert len(out) == 2 and http.calls[0][0].startswith("https://data-api.binance.vision")
    assert http.calls[1][0].startswith("https://api.binance.com")
    with pytest.raises(DataError):
        BinanceProvider(FakeHttp(lambda u, k: Resp(400, {}, "bad symbol"))).candles("XXX", "5m", 1, None)


def test_yahoo_parse_with_nulls_and_4h_resample():
    payload = {"chart": {"result": [{"timestamp": [1762650000 + 3600 * i for i in range(8)],
                                      "indicators": {"quote": [{"open": [1, 2, None, 4, 5, 6, 7, 8],
                                                                "high": [2, 3, None, 5, 6, 7, 8, 9],
                                                                "low": [0, 1, None, 3, 4, 5, 6, 7],
                                                                "close": [1.5, 2.5, None, 4.5, 5.5, 6.5, 7.5, 8.5],
                                                                "volume": [1] * 8}]}}]}}
    df = parse_chart(payload)
    assert len(df) == 7                                       # null candle dropped
    prov = YahooProvider(FakeHttp(lambda u, k: Resp(200, payload)))
    h4 = prov.candles("EURUSD=X", "4h", 5, None)
    assert len(h4) >= 2
    with pytest.raises(DataError):
        parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})
    assert prov.resolve("EURUSD") == "EURUSD=X" and prov.resolve("XXX") is None


def test_rate_limiter_blocks_when_per_second_exhausted():
    import time
    rl = RateLimiter(per_sec=3, per_min=100)
    t0 = time.monotonic()
    for _ in range(4):
        rl.acquire()
    assert time.monotonic() - t0 >= 0.9                       # 4th call had to wait for the window


def test_profiles_and_markets_are_consistent():
    from smc.utils import TF_MIN
    for p in PROFILES.values():
        assert p.htf in TF_MIN and p.ltf in TF_MIN and TF_MIN[p.htf] > TF_MIN[p.ltf]
    for m in MARKETS.values():
        assert m.symbols and m.provider in ("upstox", "binance", "yahoo")
    assert len(set(MARKETS["india"].symbols)) == len(MARKETS["india"].symbols)   # no duplicate symbols
