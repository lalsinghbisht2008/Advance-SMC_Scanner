import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time as sleep_time
import pytz
import warnings

warnings.filterwarnings("ignore")

ACTIVE_TRADES_FILE = "active_global_trades.json"
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

# Global Assets Master Universe
GLOBAL_ASSETS = {
    "EURUSD": "NSE_FX|EURUSD", "GBPUSD": "NSE_FX|GBPUSD", "USDJPY": "NSE_FX|USDJPY",
    "GOLD": "MCX_COMM|GOLD", "SILVER": "MCX_COMM|SILVER", "CRUDEOIL": "MCX_COMM|CRUDEOIL",
    "NASDAQ": "NSE_EQ|NASDAQ", "S&P500": "NSE_EQ|SP500", "DOWJONES": "NSE_EQ|DOWJONES",
    "BITCOIN": "NSE_EQ|BTC", "ETHEREUM": "NSE_EQ|ETH"
}

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)

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

def fetch_candles(instrument_key, interval, days_back=10):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}"}
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    api_interval = "1minute" if interval == "5minute" else ("30minute" if interval in ["60minute", "4hour"] else interval)
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{api_interval}/{end_date}/{start_date}"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and data["data"] and "candles" in data["data"]:
                candles = data["data"]["candles"]
                df = pd.DataFrame(candles, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume", "OI"])
                df = df[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]
                df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                df = df.sort_values("Timestamp").reset_index(drop=True)
                
                if interval == "5minute" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('5min').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                elif interval == "60minute" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('1h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                elif interval == "4hour" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                return df
    except Exception:
        pass
    return pd.DataFrame()

def analyze_strict_global_execution(instrument_key, symbol):
    df_1h = fetch_candles(instrument_key, "60minute", days_back=15)
    df_5m = fetch_candles(instrument_key, "5minute", days_back=3)
    
    if df_1h.empty or len(df_1h) < 15 or df_5m.empty or len(df_5m) < 30:
        return None

    highs_1h = df_1h['High'].values
    lows_1h = df_1h['Low'].values
    htf_ssl = min(lows_1h[-20:-1])
    
    lows_5m = df_5m['Low'].values
    highs_5m = df_5m['High'].values
    closes_5m = df_5m['Close'].values
    opens_5m = df_5m['Open'].values
    timestamps_5m = df_5m['Timestamp'].values
    
    sweep_indices = np.where(lows_5m < htf_ssl)[0]
    if len(sweep_indices) == 0:
        return None
        
    sweep_idx = sweep_indices[-1]
    if sweep_idx >= len(df_5m) - 3:
        return None
        
    post_sweep_highs = highs_5m[max(0, sweep_idx-10):sweep_idx]
    if len(post_sweep_highs) == 0:
        return None
    ltf_swing_high = max(post_sweep_highs)
    
    mss_confirmed = False
    mss_idx = -1
    for j in range(sweep_idx + 1, len(df_5m)):
        if closes_5m[j] > ltf_swing_high:
            mss_confirmed = True
            mss_idx = j
            break
            
    if not mss_confirmed:
        return None
        
    body_size = abs(closes_5m[mss_idx] - opens_5m[mss_idx])
    avg_body = np.mean(np.abs(closes_5m[max(0, mss_idx-10):mss_idx] - opens_5m[max(0, mss_idx-10):mss_idx]))
    if not (body_size > (1.5 * avg_body)):
        return None

    highest_after_mss = np.argmax(highs_5m[mss_idx:]) + mss_idx
    if highest_after_mss <= mss_idx or highest_after_mss >= len(df_5m) - 1:
        return None
    ltf_idm_price = lows_5m[highest_after_mss - 1]
    
    if not any(lows_5m[k] < ltf_idm_price for k in range(highest_after_mss, len(df_5m))):
        return None

    ltf_fvg_entry, ltf_ob_entry = None, None
    for m in range(sweep_idx, highest_after_mss):
        if m + 2 < len(df_5m) and lows_5m[m+2] > highs_5m[m]:
            ltf_fvg_entry = (highs_5m[m], lows_5m[m+2])
        if closes_5m[m] < opens_5m[m]:
            ltf_ob_entry = (lows_5m[m], max(opens_5m[m], closes_5m[m]))

    current_price = closes_5m[-1]
    entry_zone_hit = False
    if ltf_fvg_entry and ltf_fvg_entry[0] <= current_price <= ltf_fvg_entry[1]:
        entry_zone_hit = True
    elif ltf_ob_entry and ltf_ob_entry[0] <= current_price <= ltf_ob_entry[1]:
        entry_zone_hit = True
    elif current_price <= (htf_ssl * 1.002):
        entry_zone_hit = True

    if entry_zone_hit:
        entry = round(float(current_price), 2)
        sl = round(float(min(lows_5m[sweep_idx:]) * 0.998), 2)
        risk = entry - sl
        if risk > 0:
            tp = round(float(entry + (risk * 3.0)), 2)
            time_str = pd.to_datetime(timestamps_5m[-1]).strftime('%d-%m-%Y %I:%M %p')
            return {
                "Symbol": symbol,
                "Signal": "BUY 🟢 (Strict Global SMC)",
                "Model": "1H Sweep ➔ 5M MSS ➔ Displacement ➔ 5M IDM ➔ FVG/OB Mitigation",
                "Time": time_str,
                "Entry": entry, "SL": sl, "TP": tp
            }
    return None

def run_global_scanner():
    active_trades = load_json(ACTIVE_TRADES_FILE)
    for symbol, key in GLOBAL_ASSETS.items():
        setup = analyze_strict_global_execution(key, symbol)
        if setup:
            trade_id = f"{symbol}_GLOBAL_STRICT_{setup['Time']}"
            if trade_id not in active_trades:
                active_trades[trade_id] = setup
                save_json(ACTIVE_TRADES_FILE, active_trades)
                
                send_telegram_msg(
                    f"🌍 *STRICT GLOBAL SMC SETUP*\n\n"
                    f"📌 Asset: `{setup['Symbol']}`\n"
                    f"⚡ Signal: `{setup['Signal']}`\n"
                    f"📊 Structure: `{setup['Model']}`\n"
                    f"🕒 Time & Date: `{setup['Time']}`\n\n"
                    f"📍 *Entry Price:* `{setup['Entry']}`\n"
                    f"🛑 *Stop Loss (SL):* `{setup['SL']}`\n"
                    f"🎯 *Target (3R TP):* `{setup['TP']}`"
                )
        sleep_time.sleep(0.05)

if __name__ == "__main__":
    run_global_scanner()
