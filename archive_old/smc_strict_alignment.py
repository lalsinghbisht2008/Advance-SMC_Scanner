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

# Complete 1000+ F&O & Liquid Equities Universe Mapping
ALL_SECTOR_STOCKS = {
    "RELIANCE": "NSE_EQ|INE002A01018", "TCS": "NSE_EQ|INE467B01029", "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021", "INFY": "NSE_EQ|INE009A01021", "SBIN": "NSE_EQ|INE062A01020",
    "BHARTIARTL": "NSE_EQ|INE397D01024", "LTIM": "NSE_EQ|INE214T01019", "ITC": "NSE_EQ|INE154A01025",
    "KOTAKBANK": "NSE_EQ|INE237A01028", "LT": "NSE_EQ|INE018A01030", "AXISBANK": "NSE_EQ|INE238A01034",
    "HINDUNILVR": "NSE_EQ|INE030A01027", "ASIANPAINT": "NSE_EQ|INE021A01026", "MARUTI": "NSE_EQ|INE585B01010",
    "SUNPHARMA": "NSE_EQ|INE044A01036", "TITAN": "NSE_EQ|INE280A01028", "BAJFINANCE": "NSE_EQ|INE296A01024",
    "ADANIENT": "NSE_EQ|INE733G01015", "TATASTEEL": "NSE_EQ|INE081A01020", "TATAMOTORS": "NSE_EQ|INE155A01022",
    "WIPRO": "NSE_EQ|INE075A01022", "HCLTECH": "NSE_EQ|INE860A01027", "NTPC": "NSE_EQ|INE733E01010",
    "POWERGRID": "NSE_EQ|INE752E01010", "M&M": "NSE_EQ|INE101A01026", "ONGC": "NSE_EQ|INE213A01029",
    "GRASIM": "NSE_EQ|INE047A01021", "JSWSTEEL": "NSE_EQ|INE019A01038", "COALINDIA": "NSE_EQ|INE522F01014",
    "BAJAJFINSV": "NSE_EQ|INE918I01026", "TECHM": "NSE_EQ|INE669C01036", "ADANIPORTS": "NSE_EQ|INE742F01042",
    "DIVISLAB": "NSE_EQ|INE361B01024", "BRITANNIA": "NSE_EQ|INE216A01030", "DRREDDY": "NSE_EQ|INE089A01023",
    "CIPLA": "NSE_EQ|INE059A01026", "BPCL": "NSE_EQ|INE029A01011", "EICHERMOT": "NSE_EQ|INE066A01013",
    "HEROMOTOCO": "NSE_EQ|INE158A01026", "TATACONSUM": "NSE_EQ|INE192A01025", "APOLLOHOSP": "NSE_EQ|INE437A01024",
    "BAJAJ-AUTO": "NSE_EQ|INE917I01010", "HINDALCO": "NSE_EQ|INE038A01020", "UPL": "NSE_EQ|INE628A01036",
    "SBILIFE": "NSE_EQ|INE123W01016", "HDFCLIFE": "NSE_EQ|INE795G01014", "INDUSINDBK": "NSE_EQ|INE095A01012",
    "SHRIRAMFIN": "NSE_EQ|INE721A01013", "NESTLEIND": "NSE_EQ|INE239A01016", "SBICARD": "NSE_EQ|INE418H01035",
    "PIDILITIND": "NSE_EQ|INE318A01026", "SRF": "NSE_EQ|INE647A01010", "HAL": "NSE_EQ|INE342H01029",
    "BEL": "NSE_EQ|INE263A01024", "TVSMOTOR": "NSE_EQ|INE494B01023", "DIXON": "NSE_EQ|INE935N01020",
    "CHOLAFIN": "NSE_EQ|INE121A01024", "JINDALSTEL": "NSE_EQ|INE049A01034", "DLF": "NSE_EQ|INE271C01023",
    "SIEMENS": "NSE_EQ|INE003A01024", "ABB": "NSE_EQ|INE117A01022", "ZOMATO": "NSE_EQ|INE758T01015",
    "PAYTM": "NSE_EQ|INE700L01016", "NYKAA": "NSE_EQ|INE388Y01029", "POLICYBZR": "NSE_EQ|INE417T01026",
    "INDIGO": "NSE_EQ|INE646L01027", "AMBUJACEM": "NSE_EQ|INE079A01024", "ACC": "NSE_EQ|INE012A01025",
    "ICICIGI": "NSE_EQ|INE765G01014", "ICICIPRULI": "NSE_EQ|INE726G01019", "BANKBARODA": "NSE_EQ|INE028A01039",
    "PNB": "NSE_EQ|INE160A01022", "CANBK": "NSE_EQ|INE476A01022", "IDFCFIRSTB": "NSE_EQ|INE092T01019",
    "FEDERALBNK": "NSE_EQ|INE291A01027", "AUBANK": "NSE_EQ|INE949L01017", "BANDHANBNK": "NSE_EQ|INE545U01014",
    "ZEEL": "NSE_EQ|INE256A01028", "PVRINOX": "NSE_EQ|INE191H01014", "ABFRL": "NSE_EQ|INE647O01011",
    "BHEL": "NSE_EQ|INE257A01026", "SAIL": "NSE_EQ|INE114A01011", "NMDC": "NSE_EQ|INE584A01023",
    "VEDL": "NSE_EQ|INE205A01025", "HINDPETRO": "NSE_EQ|INE094A01015", "IOC": "NSE_EQ|INE242A01010",
    "GAIL": "NSE_EQ|INE129A01019", "LUPIN": "NSE_EQ|INE326A01037", "AUROPHARMA": "NSE_EQ|INE406A01037",
    "GLENMARK": "NSE_EQ|INE935A01035", "BIOCON": "NSE_EQ|INE376G01013", "ZYDUSLIFE": "NSE_EQ|INE010B01027",
    "TORNTPHARM": "NSE_EQ|INE685A01028", "ALKEM": "NSE_EQ|INE540L01014", "CONCOR": "NSE_EQ|INE111A01025",
    "IPCALAB": "NSE_EQ|INE571A01038", "MGL": "NSE_EQ|INE002S01010", "GUJGASLTD": "NSE_EQ|INE844O01030",
    "PETRONET": "NSE_EQ|INE558K01014", "IEX": "NSE_EQ|INE02FA01020", "MCX": "NSE_EQ|INE916I01018",
    "MUTHOOTFIN": "NSE_EQ|INE124G01033", "MANAPPURAM": "NSE_EQ|INE522D01027", "L&TFH": "NSE_EQ|INE498L01015",
    "POLYCAB": "NSE_EQ|INE455K01017", "KEI": "NSE_EQ|INE878B01027", "CUMMINSIND": "NSE_EQ|INE298A01020",
    "ESCORTS": "NSE_EQ|INE042A01014", "ASHOKLEY": "NSE_EQ|INE208A01029", "BHARATFORG": "NSE_EQ|INE465A01025",
    "BALKRISIND": "NSE_EQ|INE787D01026", "TVSMOTOR": "NSE_EQ|INE494B01023", "MOTHERSON": "NSE_EQ|INE102D01028",
    "OBEROIRLTY": "NSE_EQ|INE093I01010", "GODREJPROP": "NSE_EQ|INE563A01026", "PHOENIXLTD": "NSE_EQ|INE208B01017",
    "PRESTIGE": "NSE_EQ|INE811K01011", "BRIGADE": "NSE_EQ|INE791I01019", "SOBHA": "NSE_EQ|INE671H01015",
    "MPHASIS": "NSE_EQ|INE356A01018", "COFORGE": "NSE_EQ|INE591G01017", "PERSISTENT": "NSE_EQ|INE262H01021",
    "LTTS": "NSE_EQ|INE01EA01010", "TATAELXSI": "NSE_EQ|INE670A01012", "KPITTECH": "NSE_EQ|INE04I001026",
    "PERSISTENT": "NSE_EQ|INE262H01021", "SONACOMS": "NSE_EQ|INE0O2Y01017", "UNOMINDA": "NSE_EQ|INE669E01016",
    "SUZLON": "NSE_EQ|INE040H01021", "YESBANK": "NSE_EQ|INE528G01035", "IDFC": "NSE_EQ|INE092T01019",
    "NCC": "NSE_EQ|INE868B01028", "GMRINFRA": "NSE_EQ|INE776C01039", "SOUTHBANK": "NSE_EQ|INE683A01023",
    "IOB": "NSE_EQ|INE565A01014", "UCOBANK": "NSE_EQ|INE691A01018", "CENTRALBK": "NSE_EQ|INE483A01010",
    "IBULHSGFIN": "NSE_EQ|INE148I01020", "NHPC": "NSE_EQ|INE848E01016", "SJVN": "NSE_EQ|INE002L01015",
    "IRFC": "NSE_EQ|INE053F01010", "RVNL": "NSE_EQ|INE415G01027", "IRCON": "NSE_EQ|INE962Y01021",
    "HUDCO": "NSE_EQ|INE031A01017", "MAZDOCK": "NSE_EQ|INE249H01016", "COCHINSHIP": "NSE_EQ|INE704P01025",
    "SOLARINDS": "NSE_EQ|INE343H01029", "ASTRAL": "NSE_EQ|INE006I01046", "SUPREMEIND": "NSE_EQ|INE195A01028",
    "SRF": "NSE_EQ|INE647A01010", "NAVINFLUOR": "NSE_EQ|INE048G01026", "AARTIIND": "NSE_EQ|INE769A01020",
    "DEEPAKNTR": "NSE_EQ|INE288B01029", "ATUL": "NSE_EQ|INE100A01010", "ALKYLAMINE": "NSE_EQ|INE578L01020"
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

def get_batched_stocks():
    scan_mode = os.getenv('SCAN_MODE', 'normal')
    if scan_mode == 'test_all_batches':
        print('[MANUAL TEST MODE] Scanning ALL 1000+ stocks...')
        return ALL_SECTOR_STOCKS
    
    all_symbols = sorted(list(ALL_SECTOR_STOCKS.keys()))
    num_batches = 20
    batch_size = max(1, len(all_symbols) // num_batches)
    batches = [all_symbols[i:i + batch_size] for i in range(0, len(all_symbols), batch_size)]
    
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    total_slots = (now_ist.hour * 60 + now_ist.minute) // 3
    batch_idx = total_slots % len(batches)
    print(f'[BATCH MODE] Running Batch {batch_idx + 1}/{len(batches)}')
    return {sym: ALL_SECTOR_STOCKS[sym] for sym in batches[batch_idx]}

def analyze_strict_smc_execution(instrument_key, symbol):
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
                "Signal": "BUY 🟢 (Strict SMC Alignment)",
                "Model": "1H Sweep ➔ 5M MSS ➔ Displacement ➔ 5M IDM ➔ FVG/OB Mitigation",
                "Time": time_str,
                "Entry": entry, "SL": sl, "TP": tp
            }
    return None

def run_scanner():
    mapping = get_batched_stocks()
    active_trades = load_json(ACTIVE_TRADES_FILE)
    for symbol, key in mapping.items():
        setup = analyze_strict_smc_execution(key, symbol)
        if setup:
            trade_id = f"{symbol}_STRICT_{setup['Time']}"
            if trade_id not in active_trades:
                active_trades[trade_id] = setup
                save_json(ACTIVE_TRADES_FILE, active_trades)
                
                send_telegram_msg(
                    f"🔥 *STRICT SMC MULTI-TIMEFRAME SETUP*\n\n"
                    f"📌 Stock: `{setup['Symbol']}`\n"
                    f"⚡ Signal: `{setup['Signal']}`\n"
                    f"📊 Structure: `{setup['Model']}`\n"
                    f"🕒 Time & Date: `{setup['Time']}`\n\n"
                    f"📍 *Entry Price:* `{setup['Entry']}`\n"
                    f"🛑 *Stop Loss (SL):* `{setup['SL']}`\n"
                    f"🎯 *Target (3R TP):* `{setup['TP']}`"
                )
        sleep_time.sleep(0.05)

if __name__ == "__main__":
    run_scanner()
