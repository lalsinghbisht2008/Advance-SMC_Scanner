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

ACTIVE_TRADES_FILE = "active_trades.json"
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

ALL_SECTOR_STOCKS = {
    "HDFCBANK": "NSE_EQ|INE040A01034", "ICICIBANK": "NSE_EQ|INE090A01021", "SBIN": "NSE_EQ|INE062A01020",
    "AXISBANK": "NSE_EQ|INE238A01034", "KOTAKBANK": "NSE_EQ|INE237A01028", "INDUSINDBK": "NSE_EQ|INE095A01012",
    "BANKBARODA": "NSE_EQ|INE028A01039", "PNB": "NSE_EQ|INE160A01022", "CANBK": "NSE_EQ|INE476A01022",
    "IDFCFIRSTB": "NSE_EQ|INE092T01019", "FEDERALBNK": "NSE_EQ|INE291A01027", "AUBANK": "NSE_EQ|INE949L01017",
    "BANDHANBNK": "NSE_EQ|INE545U01014", "BANKINDIA": "NSE_EQ|INE084A01016", "UNIONBANK": "NSE_EQ|INE692A01016",
    "TCS": "NSE_EQ|INE467B01029", "INFY": "NSE_EQ|INE009A01021", "HCLTECH": "NSE_EQ|INE860A01027",
    "WIPRO": "NSE_EQ|INE075A01022", "TECHM": "NSE_EQ|INE669C01036", "LTIM": "NSE_EQ|INE214T01019",
    "MPHASIS": "NSE_EQ|INE356A01018", "COFORGE": "NSE_EQ|INE591G01017", "PERSISTENT": "NSE_EQ|INE262H01021",
    "LTTS": "NSE_EQ|INE01EA01010", "TATAELXSI": "NSE_EQ|INE670A01012", "KPITTECH": "NSE_EQ|INE04I001026",
    "RELIANCE": "NSE_EQ|INE002A01018", "TATAMOTORS": "NSE_EQ|INE155A01022", "MARUTI": "NSE_EQ|INE585B01010",
    "M&M": "NSE_EQ|INE101A01026", "BAJAJ-AUTO": "NSE_EQ|INE917I01010", "EICHERMOT": "NSE_EQ|INE066A01013",
    "HEROMOTOCO": "NSE_EQ|INE158A01026", "TVSMOTOR": "NSE_EQ|INE494B01023", "ASHOKLEY": "NSE_EQ|INE208A01029",
    "BHARATFORG": "NSE_EQ|INE465A01025", "BALKRISIND": "NSE_EQ|INE787D01026", "MOTHERSON": "NSE_EQ|INE102D01028",
    "SUNPHARMA": "NSE_EQ|INE044A01036", "DRREDDY": "NSE_EQ|INE089A01023", "CIPLA": "NSE_EQ|INE059A01026",
    "DIVISLAB": "NSE_EQ|INE361B01024", "APOLLOHOSP": "NSE_EQ|INE437A01024", "LUPIN": "NSE_EQ|INE326A01037",
    "TORNTPHARM": "NSE_EQ|INE685A01028", "AUROPHARMA": "NSE_EQ|INE406A01037", "GLENMARK": "NSE_EQ|INE935A01035",
    "BIOCON": "NSE_EQ|INE376G01013", "ZYDUSLIFE": "NSE_EQ|INE010B01027", "MAXHEALTH": "NSE_EQ|INE027H01010",
    "TATASTEEL": "NSE_EQ|INE081A01020", "JSWSTEEL": "NSE_EQ|INE019A01038", "HINDALCO": "NSE_EQ|INE038A01020",
    "NTPC": "NSE_EQ|INE733E01010", "POWERGRID": "NSE_EQ|INE752E01010", "ONGC": "NSE_EQ|INE213A01029",
    "ADANIENT": "NSE_EQ|INE733G01015", "ADANIPORTS": "NSE_EQ|INE742F01042", "COALINDIA": "NSE_EQ|INE522F01014",
    "BPCL": "NSE_EQ|INE029A01011", "IOC": "NSE_EQ|INE242A01010", "GAIL": "NSE_EQ|INE129A01019",
    "VEDL": "NSE_EQ|INE205A01025", "NMDC": "NSE_EQ|INE584A01023", "JINDALSTEL": "NSE_EQ|INE049A01034",
    "ITC": "NSE_EQ|INE154A01025", "HINDUNILVR": "NSE_EQ|INE030A01027", "NESTLEIND": "NSE_EQ|INE239A01016",
    "BRITANNIA": "NSE_EQ|INE216A01030", "TATACONSUM": "NSE_EQ|INE192A01025", "TITAN": "NSE_EQ|INE280A01028",
    "DABUR": "NSE_EQ|INE016A01026", "MARICO": "NSE_EQ|INE196A01026", "GODREJCP": "NSE_EQ|INE102D01010",
    "COLPAL": "NSE_EQ|INE259A01022", "VBL": "NSE_EQ|INE200M01021", "HAVELLS": "NSE_EQ|INE176B01034",
    "SUZLON": "NSE_EQ|INE040H01021", "IDEA": "NSE_EQ|INE669E01016", "JPPOWER": "NSE_EQ|INE351F01018",
    "YESBANK": "NSE_EQ|INE528G01035", "RPOWER": "NSE_EQ|INE940H01020", "IDFC": "NSE_EQ|INE092T01019",
    "NCC": "NSE_EQ|INE868B01028", "GMRINFRA": "NSE_EQ|INE776C01039", "SOUTHBANK": "NSE_EQ|INE683A01023",
    "IOB": "NSE_EQ|INE565A01014", "UCOBANK": "NSE_EQ|INE691A01018", "CENTRALBK": "NSE_EQ|INE483A01010",
    "IBULHSGFIN": "NSE_EQ|INE148I01020", "BHEL": "NSE_EQ|INE257A01026", "SAIL": "NSE_EQ|INE114A01011",
    "NHPC": "NSE_EQ|INE848E01016", "SJVN": "NSE_EQ|INE002L01015", "IRFC": "NSE_EQ|INE053F01010",
    "RVNL": "NSE_EQ|INE415G01027", "IRCON": "NSE_EQ|INE962Y01021", "HUDCO": "NSE_EQ|INE031A01017"
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

def fetch_candles(instrument_key, interval, days_back=30):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}"}
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    api_interval = "30minute" if interval in ["60minute", "4hour"] else interval
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
                
                if interval == "60minute" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('1h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                elif interval == "4hour" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                elif interval == "day" and not df.empty:
                    df.set_index('Timestamp', inplace=True)
                    df = df.resample('1D').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna().reset_index()
                return df
    except Exception:
        pass
    return pd.DataFrame()

def get_batched_fo_stocks():
    scan_mode = os.getenv('SCAN_MODE', 'normal')
    if scan_mode == 'test_all_batches':
        print('[MANUAL TEST MODE] Scanning ALL stocks...')
        return ALL_SECTOR_STOCKS
    
    all_symbols = sorted(list(ALL_SECTOR_STOCKS.keys()))
    num_batches = 20
    batch_size = max(1, len(all_symbols) // num_batches)
    batches = [all_symbols[i:i + batch_size] for i in range(0, len(all_symbols), batch_size)]
    
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    total_slots = (now_ist.hour * 60 + now_ist.minute) // 2
    batch_idx = total_slots % len(batches)
    return {sym: ALL_SECTOR_STOCKS[sym] for sym in batches[batch_idx]}

def analyze_smc_structure(instrument_key, symbol):
    df_1d = fetch_candles(instrument_key, "day", days_back=60)
    df_4h = fetch_candles(instrument_key, "4hour", days_back=30)
    df_1h = fetch_candles(instrument_key, "60minute", days_back=15)
    
    if df_4h.empty or len(df_4h) < 15 or df_1h.empty or len(df_1h) < 15:
        return None

    # Check Multi-Timeframe Sweep Context (1H or Daily Candle Sweep)
    highs_1h = df_1h['High'].values
    lows_1h = df_1h['Low'].values
    closes_1h = df_1h['Close'].values
    timestamps_1h = df_1h['Timestamp'].values

    # Determine Higher Timeframe External Levels
    recent_ssl = min(lows_1h[-20:-1])
    recent_bsl = max(highs_1h[-20:-1])
    
    current_low = lows_1h[-1]
    current_high = highs_1h[-1]
    current_close = closes_1h[-1]
    sweep_time = pd.to_datetime(timestamps_1h[-1]).strftime('%d-%m-%Y %I:%M %p')

    # Check Daily level sweep if applicable
    candle_type = "1-Hour (1H) Candle"
    if not df_1d.empty and len(df_1d) > 5:
        daily_low = df_1d['Low'].iloc[-2]
        daily_high = df_1d['High'].iloc[-2]
        if current_low < daily_low:
            candle_type = "Daily (1D) Candle"
        elif current_high > daily_high:
            candle_type = "Daily (1D) Candle"

    # Bullish Setup (SSL Sweep -> HL Rejection -> Buy)
    if current_low < recent_ssl and current_close > recent_ssl:
        entry = round(float(current_close), 2)
        sl = round(float(current_low * 0.998), 2)
        risk = entry - sl
        if risk > 0:
            tp = round(float(entry + (risk * 3.0)), 2)
            return {
                "Symbol": symbol,
                "Signal": "BUY 🟢",
                "Model": "Model 1: Confirmed HL Sweep Reversal",
                "CandleType": candle_type,
                "SweepLevel": recent_ssl,
                "SweepTime": sweep_time,
                "Context": f"{candle_type} SSL Sweep at {recent_ssl} with Rejection",
                "Entry": entry, "SL": sl, "TP": tp
            }

    # Bearish Setup (BSL Sweep -> LH Rejection -> Sell)
    if current_high > recent_bsl and current_close < recent_bsl:
        entry = round(float(current_close), 2)
        sl = round(float(current_high * 1.002), 2)
        risk = sl - entry
        if risk > 0:
            tp = round(float(entry - (risk * 3.0)), 2)
            return {
                "Symbol": symbol,
                "Signal": "SELL 🔴",
                "Model": "Model 1: Confirmed LH Sweep Reversal",
                "CandleType": candle_type,
                "SweepLevel": recent_bsl,
                "SweepTime": sweep_time,
                "Context": f"{candle_type} BSL Sweep at {recent_bsl} with Rejection",
                "Entry": entry, "SL": sl, "TP": tp
            }

    return None

def run_scanner():
    mapping = get_batched_fo_stocks()
    active_trades = load_json(ACTIVE_TRADES_FILE)
    for symbol, key in mapping.items():
        setup = analyze_smc_structure(key, symbol)
        if setup:
            trade_id = f"{symbol}_{setup['Signal']}_{setup['SweepTime']}"
            if trade_id not in active_trades:
                active_trades[trade_id] = setup
                save_json(ACTIVE_TRADES_FILE, active_trades)
                
                # Step 1: Sweep Alert Notification
                send_telegram_msg(
                    f"⚠️ *LIQUIDITY SWEEP DETECTED*\n\n"
                    f"📌 Stock: `{setup['Symbol']}`\n"
                    f"🕒 Sweep Time: `{setup['SweepTime']}`\n"
                    f"🔍 Candle Type: `{setup['CandleType']}`\n"
                    f"💧 Level Swept: `{setup['SweepLevel']}`"
                )
                
                # Step 2: Structure & Execution Setup Notification
                send_telegram_msg(
                    f"🎯 *SMC STRUCTURE EXECUTION SETUP*\n\n"
                    f"📌 Stock: `{setup['Symbol']}`\n"
                    f"⚡ Signal / Action: `{setup['Signal']}`\n"
                    f"📊 Model: `{setup['Model']}`\n"
                    f"🕒 Time & Date: `{setup['SweepTime']}`\n\n"
                    f"📍 *Entry Price:* `{setup['Entry']}`\n"
                    f"🛑 *Stop Loss (SL):* `{setup['SL']}`\n"
                    f"🎯 *Target (TP):* `{setup['TP']}`"
                )
        sleep_time.sleep(0.05)

if __name__ == "__main__":
    run_scanner()
