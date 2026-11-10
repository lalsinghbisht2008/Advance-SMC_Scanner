import yfinance as yf
import pandas as pd

def run_ob_fvg_smc_backtest(ticker):
    print(f"\n==========================================")
    print(f"   INSTITUTIONAL SMC (OB + FVG CONFLUENCE): {ticker}")
    print(f"==========================================")
    
    df_1h = yf.download(ticker, period="60d", interval="1h", progress=False)
    df_5m = yf.download(ticker, period="60d", interval="5m", progress=False)

    if df_1h.empty or df_5m.empty:
        print("Data unavailable.")
        return

    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = df_1h.columns.get_level_values(0)
    if isinstance(df_5m.columns, pd.MultiIndex):
        df_5m.columns = df_5m.columns.get_level_values(0)

    wins = 0
    losses = 0
    breakevens = 0
    total_r = 0.0
    trade_logs = []
    
    last_filled_time = None

    for i in range(30, len(df_1h)-20):
        # 1. HTF 30-bar Premium / Discount Range
        htf_high = float(df_1h['High'].iloc[i-30:i].max())
        htf_low = float(df_1h['Low'].iloc[i-30:i].min())
        equilibrium = htf_low + (htf_high - htf_low) * 0.50
        
        c_1h_time = df_1h.index[i]
        c_1h_close = float(df_1h['Close'].iloc[i])
        c_1h_low = float(df_1h['Low'].iloc[i])
        c_1h_high = float(df_1h['High'].iloc[i])
        
        ssl_level = float(df_1h['Low'].iloc[i-20:i].min())
        bsl_level = float(df_1h['High'].iloc[i-20:i].max())
        
        # --- LONG SETUP: Discount Zone (< 50%) + SSL Sweep ---
        if c_1h_close < equilibrium and c_1h_low < ssl_level and c_1h_close > c_1h_low:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=3))]
            
            for j in range(5, len(sub_5m)-2):
                swing_high = float(sub_5m['High'].iloc[j-5:j].max())
                mss_break = float(sub_5m['Close'].iloc[j]) > swing_high
                fvg_top = float(sub_5m['Low'].iloc[j])
                fvg_bottom = float(sub_5m['High'].iloc[j-2])
                
                # Check FVG Creation
                if mss_break and fvg_top > fvg_bottom:
                    # Search for Order Block (Last Bearish Candle before displacement)
                    ob_high = None
                    for k in range(j-1, max(0, j-4), -1):
                        if float(sub_5m['Close'].iloc[k]) < float(sub_5m['Open'].iloc[k]):
                            ob_high = float(sub_5m['High'].iloc[k])
                            break
                    
                    if ob_high is None:
                        continue
                        
                    # OB + FVG Confluence Level (Limit entry near OB High or FVG Top)
                    limit_entry = round(min(fvg_top, ob_high), 2)
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

        # --- SHORT SETUP: Premium Zone (> 50%) + BSL Sweep ---
        elif c_1h_close > equilibrium and c_1h_high > bsl_level and c_1h_close < c_1h_high:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=3))]
            
            for j in range(5, len(sub_5m)-2):
                swing_low = float(sub_5m['Low'].iloc[j-5:j].min())
                mss_break = float(sub_5m['Close'].iloc[j]) < swing_low
                fvg_bottom = float(sub_5m['High'].iloc[j])
                fvg_top = float(sub_5m['Low'].iloc[j-2])
                
                if mss_break and fvg_top > fvg_bottom:
                    # Search for Order Block (Last Bullish Candle before displacement)
                    ob_low = None
                    for k in range(j-1, max(0, j-4), -1):
                        if float(sub_5m['Close'].iloc[k]) > float(sub_5m['Open'].iloc[k]):
                            ob_low = float(sub_5m['Low'].iloc[k])
                            break
                            
                    if ob_low is None:
                        continue
                        
                    limit_entry = round(max(fvg_bottom, ob_low), 2)
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
        print(f"📊 OB + FVG CONFLUENCE REPORT FOR {ticker}:")
        print(f"Total Trades     : {total}")
        print(f"✅ Wins (1:3 RR)  : {wins}")
        print(f"🛡️ Break-Evens   : {breakevens}")
        print(f"❌ Losses (-1R)   : {losses}")
        print(f"🎯 Win Rate      : {win_rate}%")
        print(f"💰 Net R Gained  : {round(total_r, 2)} R")
        print("------------------------------------------")
    else:
        print("No valid OB + FVG setups matched.")

if __name__ == "__main__":
    run_ob_fvg_smc_backtest("TECHM.NS")
    run_ob_fvg_smc_backtest("INFY.NS")
    run_ob_fvg_smc_backtest("RELIANCE.NS")