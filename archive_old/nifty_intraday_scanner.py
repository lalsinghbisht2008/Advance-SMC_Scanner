import requests
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
import time as sleep_time
import warnings

warnings.filterwarnings("ignore")

UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

INDICES_CONFIG = {
    "NIFTY": {
        "index_key": "NSE_INDEX|Nifty 50",
        "step": 50,
        "default_spot": 24500.0,
        "symbol_prefix": "NIFTY"
    },
    "BANKNIFTY": {
        "index_key": "NSE_INDEX|Nifty Bank",
        "step": 100,
        "default_spot": 52000.0,
        "symbol_prefix": "BANKNIFTY"
    },
    "SENSEX": {
        "index_key": "BSE_INDEX|SENSEX",
        "step": 100,
        "default_spot": 80000.0,
        "symbol_prefix": "SENSEX"
    }
}

def send_telegram_msg(msg):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception:
        pass

def fetch_candles(instrument_key, interval, days_back=5):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}"}
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{end_date}/{start_date}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and data["data"] and "candles" in data["data"]:
                candles = data["data"]["candles"]
                df = pd.DataFrame(candles, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume", "OI"])
                df = df[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]
                df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                return df.sort_values("Timestamp").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()

def check_higher_timeframe_sweep(index_key):
    # 1. Check Daily (1D) PDH / PDL Sweep
    df_1d = fetch_candles(index_key, "day", days_back=5)
    if len(df_1d) >= 2:
        prev_high = float(df_1d['High'].iloc[-2])
        prev_low = float(df_1d['Low'].iloc[-2])
        curr_high = float(df_1d['High'].iloc[-1])
        curr_low = float(df_1d['Low'].iloc[-1])
        curr_close = float(df_1d['Close'].iloc[-1])

        if curr_high > prev_high and curr_close < prev_high:
            return "BEARISH_SWEEP", prev_high  # PDH Swept & Rejected -> Look for PE
        if curr_low < prev_low and curr_close > prev_low:
            return "BULLISH_SWEEP", prev_low   # PDL Swept & Rejected -> Look for CE

    # 2. Check 1-Hour BSL / SSL Sweep
    df_1h = fetch_candles(index_key, "60minute", days_back=3)
    if len(df_1h) >= 15:
        highs = df_1h['High'].values
        lows = df_1h['Low'].values
        closes = df_1h['Close'].values
        
        recent_high = max(highs[-15:-2])
        recent_low = min(lows[-15:-2])
        curr_h = float(highs[-1])
        curr_l = float(lows[-1])
        curr_c = float(closes[-1])

        if curr_h > recent_high and curr_c < recent_high:
            return "BEARISH_SWEEP", recent_high
        if curr_l < recent_low and curr_c > recent_low:
            return "BULLISH_SWEEP", recent_low

    return None, 0.0

def get_option_instrument_key(prefix, strike, opt_type):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}"}
    query = f"{prefix} {int(strike)} {opt_type}"
    url = f"https://api.upstox.com/v2/search/instruments?symbol={query}"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and data["data"]:
                for item in data["data"]:
                    if item.get("instrument_type") == opt_type:
                        return item.get("instrument_key"), item.get("trading_symbol")
    except Exception:
        pass
    return None, None

def confirm_1m_options_smc(key, tradingsymbol, opt_type):
    """
    1M Option Chart True SMC Execution:
    Checks 1M option chart for MSS (Displacement), FVG (Imbalance), and Order Block (OB) mitigation.
    """
    df_1m = fetch_candles(key, "1minute", days_back=2)
    if df_1m.empty or len(df_1m) < 25:
        return None

    opens = df_1m['Open'].values
    closes = df_1m['Close'].values
    highs = df_1m['High'].values
    lows = df_1m['Low'].values
    n = len(df_1m)

    for i in range(n - 10, 2, -1):
        body_prev = abs(closes[i-1] - opens[i-1])
        body_curr = abs(closes[i] - opens[i])
        
        # Displacement candle confirming option expansion
        if closes[i] > opens[i] and body_curr > (body_prev * 1.5):
            # Check FVG (Imbalance)
            if lows[i+1] > highs[i-1]:
                # Find Bullish Order Block
                ob_idx = i - 1
                while ob_idx > 0 and closes[ob_idx] > opens[ob_idx]:
                    ob_idx -= 1
                
                if ob_idx > 0:
                    ob_low = lows[ob_idx]
                    ob_high = highs[ob_idx]
                    
                    # Check price pullback into OB zone
                    for j in range(n - 4, n):
                        if lows[j] <= ob_high and closes[j] > opens[j]:
                            entry = round(float(closes[j]), 2)
                            sl = round(max(1.0, float(ob_low * 0.99)), 2)
                            risk = entry - sl
                            if risk <= 0:
                                continue
                            tp = round(entry + (risk * 2.5), 2)
                            return {
                                "Entry": entry,
                                "SL": sl,
                                "TP": tp,
                                "Trigger": "1M MSS Displacement + FVG + OB Retracement"
                            }
    return None

def scan_1m_options_smc(prefix, strike, opt_type, htf_bias):
    key, tradingsymbol = get_option_instrument_key(prefix, strike, opt_type)
    if not key:
        return

    execution = confirm_1m_options_smc(key, tradingsymbol, opt_type)
    if execution:
        signal_type = "OPTION BUY (CE) 🟢" if opt_type == "CE" else "OPTION BUY (PE) 🔴"
        bias_desc = "BULLISH (PDL/SSL Sweep)" if htf_bias == "BULLISH_SWEEP" else "BEARISH (PDH/BSL Sweep)"
        
        send_telegram_msg(
            f"🎯 *TRUE SMC OPTIONS SETUP!*\n\n"
            f"📌 Index HTF Bias: `{bias_desc}`\n"
            f"📌 Option Contract: `{tradingsymbol}`\n"
            f"⚡ Signal: `{signal_type}`\n"
            f"⚙️ Execution: `{execution['Trigger']}`\n\n"
            f"📍 *Entry:* `{execution['Entry']}`\n"
            f"🛑 *Stop Loss (SL):* `{execution['SL']}`\n"
            f"🎯 *Target (TP):* `{execution['TP']}`\n\n"
            f"🚀 Status: Index Sweep Confirmed -> 1M True SMC OB Retracement!"
        )

def run_top_down_scanner():
    print("==================================================")
    print(f"🚀 TRUE SMC NIFTY / INDEX OPTIONS SCANNER")
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("==================================================")

    for name, cfg in INDICES_CONFIG.items():
        bias, level = check_higher_timeframe_sweep(cfg["index_key"])
        if not bias:
            print(f"[INFO] {name}: No HTF Sweep detected yet.")
            continue

        print(f"🔥 {name} HTF Sweep Detected: {bias} at level {level}")
        
        df_spot = fetch_candles(cfg["index_key"], "day", days_back=2)
        spot = float(df_spot['Close'].iloc[-1]) if not df_spot.empty else cfg["default_spot"]
        
        step = cfg["step"]
        atm_strike = round(spot / step) * step

        opt_type = "CE" if bias == "BULLISH_SWEEP" else "PE"
        strikes = [atm_strike - step, atm_strike, atm_strike + step]
        
        for strike in strikes:
            scan_1m_options_smc(cfg["symbol_prefix"], strike, opt_type, bias)
            sleep_time.sleep(0.4)

if __name__ == "__main__":
    run_top_down_scanner()
