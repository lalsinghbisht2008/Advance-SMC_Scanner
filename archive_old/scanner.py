import yfinance as yf
import requests
import pandas as pd
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, STOCKS

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def check_smc_setup(ticker):
    print(f"Scanning {ticker}...")
    
    # 1. Fetch 1-Hour Data for 1H SSL Sweep Check
    df_1h = yf.download(ticker, period="1mo", interval="1h", progress=False)
    if df_1h.empty or len(df_1h) < 20:
        return

    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = df_1h.columns.get_level_values(0)

    recent_ssl = float(df_1h['Low'].iloc[-20:-2].min())  # Valid 1H Swing Low (SSL)
    last_low_1h = float(df_1h['Low'].iloc[-1])
    
    # 1H SSL Sweep Condition
    if last_low_1h < recent_ssl:
        # 2. Fetch 5-Minute Data for MSS + FVG Check
        df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
        if df_5m.empty or len(df_5m) < 10:
            return
        
        if isinstance(df_5m.columns, pd.MultiIndex):
            df_5m.columns = df_5m.columns.get_level_values(0)

        recent_high_5m = float(df_5m['High'].iloc[-10:-2].max())
        last_close_5m = float(df_5m['Close'].iloc[-1])
        
        # 5M MSS Condition (Break of Structure)
        mss_confirmed = last_close_5m > recent_high_5m
        
        # 5M FVG Condition (Bullish Gap)
        fvg_confirmed = float(df_5m['Low'].iloc[-1]) > float(df_5m['High'].iloc[-3])

        if mss_confirmed and fvg_confirmed:
            entry_price = round(last_close_5m, 2)
            sl_price = round(float(df_5m['Low'].iloc[-5:].min()), 2)
            target_bsl = round(float(df_1h['High'].iloc[-20:].max()), 2)

            msg = (
                f"🚨 *SMC SSL -> BSL SETUP ALERT!*\n\n"
                f"📌 *Stock:* `{ticker.replace('.NS', '')}`\n"
                f"⚡ *1H SSL Swept:* Below `{recent_ssl:.2f}`\n"
                f"📈 *5M MSS & FVG:* Confirmed\n"
                f"🎯 *Entry Zone:* ~`{entry_price}`\n"
                f"🛑 *Stop Loss:* `{sl_price}`\n"
                f"🏁 *Target (BSL):* `{target_bsl}`"
            )
            print(msg)
            send_telegram(msg)

def run_scanner():
    print("--- Starting SMC SSL-BSL Scan ---")
    for stock in STOCKS:
        check_smc_setup(stock)
    print("--- Scan Complete ---")

if __name__ == "__main__":
    # send_telegram("✅ SMC Scanner Connected Successfully!")  <-- Is line ko comment (#) kar dein
    run_scanner()