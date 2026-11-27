import gzip
import json

import pandas as pd

from smc import config as C
from smc.notifier import setup_message
from smc.options import plan, premium_at
from smc.providers.instruments import InstrumentResolver


def _ms(d):
    return int(pd.Timestamp(d, tz="Asia/Kolkata").timestamp() * 1000)


ROWS = [
    {"segment": "NSE_FO", "instrument_type": t, "underlying_symbol": "NIFTY", "strike_price": k,
     "expiry": _ms(e), "instrument_key": f"NSE_FO|{t}{k}{e}", "trading_symbol": f"NIFTY {k} {t}", "lot_size": 75}
    for t in ("CE", "PE") for k in (24450, 24500, 24550) for e in ("2026-11-26", "2026-12-03")
] + [{"segment": "BSE_FO", "instrument_type": "CE", "underlying_symbol": "SENSEX", "strike_price": 80000,
      "expiry": _ms("2026-12-01"), "instrument_key": "BSE_FO|S80000", "trading_symbol": "SENSEX 80000 CE", "lot_size": 20}]


class FakeHttp:
    def get(self, url, **kw):
        class R:
            status_code = 200
            content = gzip.compress(json.dumps(ROWS).encode())

            def raise_for_status(self):
                pass
        return R()


def _res(tmp_path):
    return InstrumentResolver(FakeHttp(), tmp_path)


def test_picks_atm_of_nearest_unexpired_expiry(tmp_path):
    now = pd.Timestamp("2026-11-27 05:00", tz="UTC")           # 26 Nov expiry already over
    o = _res(tmp_path).option("NIFTY", 24512, "CE", 50, now)
    assert o["strike"] == 24500 and o["expiry"] == "2026-12-03" and o["type"] == "CE"
    pe = _res(tmp_path).option("NIFTY", 24520, "PE", 50, now)
    assert pe["type"] == "PE" and pe["strike"] == 24500


def test_expiry_day_contract_is_still_usable(tmp_path):
    now = pd.Timestamp("2026-11-26 05:00", tz="UTC")
    assert _res(tmp_path).option("NIFTY", 24500, "CE", 50, now)["expiry"] == "2026-11-26"


def test_sensex_uses_bse_file(tmp_path):
    now = pd.Timestamp("2026-11-27 05:00", tz="UTC")
    assert _res(tmp_path).option("SENSEX", 80030, "CE", 100, now)["key"] == "BSE_FO|S80000"


def test_premium_math_buy_and_sell():
    assert premium_at(100, 24500, 24540, "BUY", 0.5) == 120          # CE gains when index rises
    assert premium_at(100, 24500, 24540, "SELL", 0.5) == 80          # PE loses when index rises
    assert premium_at(100, 24500, 24500 - 400, "BUY", 0.5) == 0.05   # floored


class FakeProv:
    def __init__(self, tmp_path, ltp=True):
        self.resolver = _res(tmp_path)
        self._ltp = ltp

    def ltp(self, keys):
        return {keys[0]: 120.0} if self._ltp else {}


def _trade(side="BUY"):
    return {"symbol": "NIFTY", "side": side, "entry": 24500.0, "sl": 24460.0, "tp1": 24580.0, "tp2": 24640.0,
            "last_close": 24520.0}


def test_plan_and_message(tmp_path):
    now = pd.Timestamp("2026-11-27 05:00", tz="UTC")
    t = _trade()
    t["opt"] = plan(t, FakeProv(tmp_path), now)
    assert t["opt"]["type"] == "CE" and abs(t["opt"]["entry_prem"] - 110) < 1e-6   # 120 + 0.5*(24500-24520)
    assert t["opt"]["sl_prem"] < t["opt"]["entry_prem"] < t["opt"]["tp1_prem"] < t["opt"]["tp2_prem"]
    s = _trade("SELL")
    s.update(sl=24540.0, tp1=24420.0, tp2=24360.0)
    s["opt"] = plan(s, FakeProv(tmp_path), now)
    assert s["opt"]["type"] == "PE" and s["opt"]["sl_prem"] < s["opt"]["entry_prem"] < s["opt"]["tp1_prem"]


def test_plan_survives_missing_ltp_and_errors(tmp_path):
    now = pd.Timestamp("2026-11-27 05:00", tz="UTC")
    o = plan(_trade(), FakeProv(tmp_path, ltp=False), now)
    assert o["ltp"] is None and "entry_prem" not in o
    assert plan(_trade(), object(), now) is None                       # provider without resolver -> no crash


def test_index_market_and_profiles():
    m = C.MARKETS["index"]
    assert m.symbols == ["NIFTY", "BANKNIFTY", "SENSEX"] and "NIFTY" not in C.MARKETS["india"].symbols
    assert {C.PROFILES[p].ltf for p in C.DEFAULT_PROFILES["index"]} == {"15m", "1m"}
    assert {C.PROFILES[p].htf for p in C.DEFAULT_PROFILES["index"]} == {"1d", "4h", "1h"}
