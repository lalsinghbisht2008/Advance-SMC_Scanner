import yfinance as yf
import pandas as pd

def run_ultimate_smc_backtest(ticker):
    print(f"\n==========================================")
    print(f"   ULTIMATE DUAL-DIRECTION SMC: {ticker}")
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

    # 1H 50 EMA for Trend Filter
    df_1h['EMA50'] = df_1h['Close'].ewm(span=50, adjust=False).mean()

    wins = 0
    losses = 0
    breakevens = 0
    total_r = 0.0
    trade_logs = []
    
    last_trade_time = None

    for i in range(20, len(df_1h)-20):
        c_1h_time = df_1h.index[i]
        c_1h_close = float(df_1h['Close'].iloc[i])
        c_1h_low = float(df_1h['Low'].iloc[i])
        c_1h_high = float(df_1h['High'].iloc[i])
        ema_val = float(df_1h['EMA50'].iloc[i])
        
        ssl_level = float(df_1h['Low'].iloc[i-20:i].min())
        bsl_level = float(df_1h['High'].iloc[i-20:i].max())
        
        # --- BUY SETUP: Uptrend + SSL Sweep ---
        if c_1h_close > ema_val and c_1h_low < ssl_level and c_1h_close > c_1h_low:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=2))]
            
            for j in range(5, len(sub_5m)-2):
                entry_time = sub_5m.index[j]
                
                # Session Filter & Duplicate Check
                if entry_time.hour >= 14 or (last_trade_time and (entry_time - last_trade_time).total_seconds() < 7200):
                    continue

                swing_high = float(sub_5m['High'].iloc[j-5:j].max())
                if float(sub_5m['Close'].iloc[j]) > swing_high: # MSS
                    entry_price = float(sub_5m['Close'].iloc[j])
                    sl = round(c_1h_low * 0.998, 2)
                    risk = entry_price - sl
                    
                    if risk <= 0: continue
                    target = round(entry_price + (risk * 3.0), 2)
                    
                    # Evaluate Trade
                    future_candles = df_5m[df_5m.index > entry_time]
                    is_be = False
                    curr_sl = sl
                    
                    for _, candle in future_candles.iterrows():
                        if not is_be and float(candle['High']) >= (entry_price + risk * 1.5):
                            curr_sl = entry_price
                            is_be = True
                            
                        if float(candle['Low']) <= curr_sl:
                            if is_be:
                                breakevens += 1
                                trade_logs.append({"Date": str(entry_time)[:16], "Type": "LONG", "Entry": entry_price, "SL": sl, "Outcome": "BE"})
                            else:
                                losses += 1
                                total_r -= 1.0
                                trade_logs.append({"Date": str(entry_time)[:16], "Type": "LONG", "Entry": entry_price, "SL": sl, "Outcome": "LOSS"})
                            last_trade_time = entry_time
                            break
                        elif float(candle['High']) >= target:
                            wins += 1
                            total_r += 3.0
                            trade_logs.append({"Date": str(entry_time)[:16], "Type": "LONG", "Entry": entry_price, "SL": sl, "Outcome": "WIN"})
                            last_trade_time = entry_time
                            break
                    break

        # --- SHORT SETUP: Downtrend + BSL Sweep ---
        elif c_1h_close < ema_val and c_1h_high > bsl_level and c_1h_close < c_1h_high:
            sub_5m = df_5m[(df_5m.index >= c_1h_time) & (df_5m.index <= c_1h_time + pd.Timedelta(hours=2))]
            
            for j in range(5, len(sub_5m)-2):
                entry_time = sub_5m.index[j]
                
                if entry_time.hour >= 14 or (last_trade_time and (entry_time - last_trade_time).total_seconds() < 7200):
                    continue

                swing_low = float(sub_5m['Low'].iloc[j-5:j].min())
                if float(sub_5m['Close'].iloc[j]) < swing_low: # MSS Short
                    entry_price = float(sub_5m['Close'].iloc[j])
                    sl = round(c_1h_high * 1.002, 2)
                    risk = sl - entry_price
                    
                    if risk <= 0: continue
                    target = round(entry_price - (risk * 3.0), 2)
                    
                    future_candles = df_5m[df_5m.index > entry_time]
                    is_be = False
                    curr_sl = sl
                    
                    for _, candle in future_candles.iterrows():
                        if not is_be and float(candle['Low']) <= (entry_price - risk * 1.5):
                            curr_sl = entry_price
                            is_be = True
                            
                        if float(candle['High']) >= curr_sl:
                            if is_be:
                                breakevens += 1
                                trade_logs.append({"Date": str(entry_time)[:16], "Type": "SHORT", "Entry": entry_price, "SL": sl, "Outcome": "BE"})
                            else:
                                losses += 1
                                total_r -= 1.0
                                trade_logs.append({"Date": str(entry_time)[:16], "Type": "SHORT", "Entry": entry_price, "SL": sl, "Outcome": "LOSS"})
                            last_trade_time = entry_time
                            break
                        elif float(candle['Low']) <= target:
                            wins += 1
                            total_r += 3.0
                            trade_logs.append({"Date": str(entry_time)[:16], "Type": "SHORT", "Entry": entry_price, "SL": sl, "Outcome": "WIN"})
                            last_trade_time = entry_time
                            break
                    break

    total = wins + losses + breakevens
    if total > 0:
        win_rate = round((wins / total) * 100, 2)
        print(pd.DataFrame(trade_logs).to_string(index=False))
        print("\n------------------------------------------")
        print(f"📊 ULTIMATE REPORT FOR {ticker}:")
        print(f"Total Trades     : {total}")
        print(f"✅ Wins (1:3 RR)  : {wins}")
        print(f"🛡️ Break-Evens   : {breakevens}")
        print(f"❌ Losses (-1R)   : {losses}")
        print(f"🎯 Win Rate      : {win_rate}%")
        print(f"💰 Net R Gained  : {round(total_r, 2)} R")
        print("------------------------------------------")

if __name__ == "__main__":
    run_ultimate_smc_backtest("TECHM.NS")
    run_ultimate_smc_backtest("INFY.NS")
    run_ultimate_smc_backtest("RELIANCE.NS")