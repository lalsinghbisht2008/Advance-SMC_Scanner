import pandas as pd

from backtest import run_backtest, summarize
from smc import config as C
from smc.config import Market
from tests.synth import build, random_walk

M = Market(name="test", provider="binance", tz="UTC", symbols=["A"], kind="24x7", label="T")


def test_backtest_finds_the_planted_trade_and_is_hindsight_free():
    ltf, htf = build("trigger")
    # extend with a rally so the trade resolves
    ts = ltf.index[-1]
    rows = [(ts + pd.Timedelta(minutes=5 * i), 101, hi, lo, hi - 0.2, 1000.0)
            for i, (hi, lo) in enumerate([(106.0, 100.5), (109.0, 105.0), (111.0, 108.0)], 1)]
    ltf = pd.concat([ltf, pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")])
    df, skipped = run_backtest(ltf, htf, None, M, C.PROFILES["5m"], "A", warmup=700)
    assert len(df) == 1 and df.iloc[0]["side"] == "BUY" and df.iloc[0]["status"] == "CLOSED_TP2"
    assert df.iloc[0]["stage"] in ("WAIT_IDM", "ARMED") and df.iloc[0]["r"] > 2
    assert pd.Timestamp(df.iloc[0]["fill"]) > df.iloc[0]["seen"]            # fill came after the alert candle
    assert "filled & closed: 1" in summarize(df, skipped)


def test_backtest_runs_on_noise_without_crashing():
    from smc.utils import resample_ohlcv
    ltf = random_walk(1500)
    htf = resample_ohlcv(ltf, "1h", origin=ltf.index[0].floor("1h"))
    df, skipped = run_backtest(ltf, htf, None, M, C.PROFILES["5m"], "N", warmup=400, step=5)
    assert isinstance(summarize(df, skipped), str)
