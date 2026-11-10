import yfinance as yf
import pandas as pd
from datetime import time

def is_in_killzone(dt):
    """
    NSE Liquidity Kill-Zones:
    - Morning Kill-Zone: 09:30 AM - 11:30 AM
    - Afternoon Kill-Zone: 01:15 PM - 03:00 PM
    """
    t = dt.time()
    morning_start, morning_end = time(9, 30), time(11, 30)
    afternoon_start, afternoon_end = time(13, 15), time(15, 0)
    
    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)

def run_killzone_smc_backtest(ticker):
    print(f"\n==========================================")
    print(f"   INSTITUTIONAL SMC (KILL-ZONES + TREND + 50% FVG/OB): {ticker}")
    print(f"==========================================")
    
    df_daily = yf.download(ticker, period="1y", interval="1d", progress=False)
    df_1h = yf.download(ticker, period="60d", interval="1h", progress=False)
    df_5m = yf.download(ticker, period="60d", interval="5m", progress=False)

    if df_daily.empty or df_1h.empty or df_5m.empty:
        print("Data unavailable.")
        return

    for df in [df_daily, df_1h, df_5m]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # 20 SMA for Daily Trend Alignment
    df_daily['SMA_20'] = df_daily['Close'].rolling(window=20).mean()

    wins = 0
    losses = 0
    breakevens = 0
    total_r = 0.0
    trade_logs = []
    
    last_filled_time = None

    for i in range(30, len(df_1h)-20):
        c_1h_time = df_1h.index[i]
        
        # Match Daily Trend
        daily_matches = df_daily[df_daily.index.date <= c_1h_time.date()]
        if daily_matches.empty or pd.isna(daily_matches['SMA_20'].iloc[-1]):
            continue
            
        daily_close = float(daily_matches['Close'].iloc[-1])
        daily_sma = float(daily_matches['SMA_20'].iloc[-1])
        daily_trend = "BULLISH" if daily_close >= daily_sma else "BEARISH"

        # 1H HTF Range & Sweeps
        htf_high = float(df_1h['High'].iloc[i-30:i].max())
        htf_low = float(df_1h['Low'].iloc[i-30:i].min())
        equilibrium = htf_low + (htf_high - htf_low) * 0.50
        
        c_1h_close = float(df_1h['Close'].iloc[i])
        c_1h_low = float(df_1h['Low'].iloc[i])
        c_1h_high = float(df_1h['High'].iloc[i])
        
        ssl_level = float(df_1h['Low'].iloc[i-20:i].min())
        bsl_level = float(df_1h['High'].iloc[i-20:i].max())
        
        # --- LONG SETUP: Daily Bullish + Discount Zone + SSL Sweep ---
        if daily_trend == "BULLISH" and c_1h_close < equilibrium and c_1h_low < ssl_level and c_1h_close > c_1h_low:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=3))]
            
            for j in range(5, len(sub_5m)-2):
                swing_high = float(sub_5m['High'].iloc[j-5:j].max())
                mss_break = float(sub_5m['Close'].iloc[j]) > swing_high
                fvg_top = float(sub_5m['Low'].iloc[j])
                fvg_bottom = float(sub_5m['High'].iloc[j-2])
                
                if mss_break and fvg_top > fvg_bottom:
                    fvg_50 = fvg_bottom + (fvg_top - fvg_bottom) * 0.5
                    
                    ob_high = None
                    for k in range(j-1, max(0, j-4), -1):
                        if float(sub_5m['Close'].iloc[k]) < float(sub_5m['Open'].iloc[k]):
                            ob_high = float(sub_5m['High'].iloc[k])
                            break
                    
                    if ob_high is not None and ob_high >= fvg_bottom:
                        limit_entry = round((fvg_50 + ob_high) / 2.0, 2)
                    else:
                        limit_entry = round(fvg_50, 2)
                        
                    sl = round(c_1h_low * 0.998, 2)
                    risk = limit_entry - sl
                    
                    if risk <= 0 or (risk / limit_entry) > 0.015:
                        continue
                        
                    target = round(limit_entry + (risk * 3.0), 2)
                    
                    sub_future = sub_5m.iloc[j+1:]
                    order_filled = False
                    fill_time = None
                    
                    for f_time, candle in sub_future.iterrows():
                        if float(candle['Low']) <= limit_entry:
                            # Check if entry is inside Liquidity Kill-Zone
                            if is_in_killzone(f_time):
                                order_filled = True
                                fill_time = f_time
                            break
                            
                    if not order_filled:
                        continue
                    
                    if last_filled_time is not None and fill_time <= last_filled_time:
                        continue

                    trade_future = df_5m[df_5m.index > fill_time]
                    is_be = False
                    curr_sl = sl
                    
                    for _, candle in trade_future.iterrows():
                        c_low = float(candle['Low'])
                        c_high = float(candle['High'])
                        
                        if not is_be and c_high >= (limit_entry + risk * 1.5):
                            curr_sl = limit_entry
                            is_be = True
                            
                        if c_low <= curr_sl:
                            if is_be:
                                breakevens += 1
                                trade_logs.append({"Date": str(fill_time)[:16], "Type": "LONG", "Entry": limit_entry, "SL": sl, "Outcome": "BE"})
                            else:
                                losses += 1
                                total_r -= 1.0
                                trade_logs.append({"Date": str(fill_time)[:16], "Type": "LONG", "Entry": limit_entry, "SL": sl, "Outcome": "LOSS"})
                            break
                        elif c_high >= target:
                            wins += 1
                            total_r += 3.0
                            trade_logs.append({"Date": str(fill_time)[:16], "Type": "LONG", "Entry": limit_entry, "SL": sl, "Outcome": "WIN"})
                            break
                    
                    last_filled_time = fill_time
                    break

        # --- SHORT SETUP: Daily Bearish + Premium Zone + BSL Sweep ---
        elif daily_trend == "BEARISH" and c_1h_close > equilibrium and c_1h_high > bsl_level and c_1h_close < c_1h_high:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=3))]
            
            for j in range(5, len(sub_5m)-2):
                swing_low = float(sub_5m['Low'].iloc[j-5:j].min())
                mss_break = float(sub_5m['Close'].iloc[j]) < swing_low
                fvg_bottom = float(sub_5m['High'].iloc[j])
                fvg_top = float(sub_5m['Low'].iloc[j-2])
                
                if mss_break and fvg_top > fvg_bottom:
                    fvg_50 = fvg_bottom + (fvg_top - fvg_bottom) * 0.5
                    
                    ob_low = None
                    for k in range(j-1, max(0, j-4), -1):
                        if float(sub_5m['Close'].iloc[k]) > float(sub_5m['Open'].iloc[k]):
                            ob_low = float(sub_5m['Low'].iloc[k])
                            break
                            
                    if ob_low is not None and ob_low <= fvg_top:
                        limit_entry = round((fvg_50 + ob_low) / 2.0, 2)
                    else:
                        limit_entry = round(fvg_50, 2)
                        
                    sl = round(c_1h_high * 1.002, 2)
                    risk = sl - limit_entry
                    
                    if risk <= 0 or (risk / limit_entry) > 0.015:
                        continue
                        
                    target = round(limit_entry - (risk * 3.0), 2)
                    
                    sub_future = sub_5m.iloc[j+1:]
                    order_filled = False
                    fill_time = None
                    
                    for f_time, candle in sub_future.iterrows():
                        if float(candle['High']) >= limit_entry:
                            # Check if entry is inside Liquidity Kill-Zone
                            if is_in_killzone(f_time):
                                order_filled = True
                                fill_time = f_time
                            break
                            
                    if not order_filled:
                        continue
                        
                    if last_filled_time is not None and fill_time <= last_filled_time:
                        continue

                    trade_future = df_5m[df_5m.index > fill_time]
                    is_be = False
                    curr_sl = sl
                    
                    for _, candle in trade_future.iterrows():
                        c_low = float(candle['Low'])
                        c_high = float(candle['High'])
                        
                        if not is_be and c_low <= (limit_entry - risk * 1.5):
                            curr_sl = limit_entry
                            is_be = True
                            
                        if c_high >= curr_sl:
                            if is_be:
                                breakevens += 1
                                trade_logs.append({"Date": str(fill_time)[:16], "Type": "SHORT", "Entry": limit_entry, "SL": sl, "Outcome": "BE"})
                            else:
                                losses += 1
                                total_r -= 1.0
                                trade_logs.append({"Date": str(fill_time)[:16], "Type": "SHORT", "Entry": limit_entry, "SL": sl, "Outcome": "LOSS"})
                            break
                        elif c_low <= target:
                            wins += 1
                            total_r += 3.0
                            trade_logs.append({"Date": str(fill_time)[:16], "Type": "SHORT", "Entry": limit_entry, "SL": sl, "Outcome": "WIN"})
                            break
                            
                    last_filled_time = fill_time
                    break

    total = wins + losses + breakevens
    if total > 0:
        win_rate = round((wins / total) * 100, 2)
        print(pd.DataFrame(trade_logs).to_string(index=False))
        print("\n------------------------------------------")
        print(f"📊 KILL-ZONE ENHANCED SMC REPORT FOR {ticker}:")
        print(f"Total Trades     : {total}")
        print(f"✅ Wins (1:3 RR)  : {wins}")
        print(f"🛡️ Break-Evens   : {breakevens}")
        print(f"❌ Losses (-1R)   : {losses}")
        print(f"🎯 Win Rate      : {win_rate}%")
        print(f"💰 Net R Gained  : {round(total_r, 2)} R")
        print("------------------------------------------")
    else:
        print("No valid setups matched inside Kill-Zones.")

if __name__ == "__main__":
    run_killzone_smc_backtest("TECHM.NS")
    run_killzone_smc_backtest("INFY.NS")
    run_killzone_smc_backtest("RELIANCE.NS")