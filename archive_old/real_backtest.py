import yfinance as yf
import pandas as pd

def run_refined_smc_backtest(ticker):
    print(f"\n==========================================")
    print(f"   REFINED SMC STRATEGY BACKTEST: {ticker}")
    print(f"==========================================")
    
    # Fetch 60 days 1H and 5M data
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
    total_r = 0.0
    trade_logs = []

    for i in range(20, len(df_1h)-20):
        ssl_level = float(df_1h['Low'].iloc[i-20:i].min())
        c_1h_low = float(df_1h['Low'].iloc[i])
        c_1h_close = float(df_1h['Close'].iloc[i])
        c_1h_open = float(df_1h['Open'].iloc[i])
        
        # 1. SSL Sweep Condition (Price sweeps low but rejection/bullish body forms)
        if c_1h_low < ssl_level and c_1h_close > c_1h_low:
            sweep_time = df_1h.index[i]
            sweep_low = c_1h_low  # Realistic SL level below sweep point
            
            sub_5m = df_5m[(df_5m.index >= sweep_time) & (df_5m.index <= sweep_time + pd.Timedelta(hours=2))]
            
            if len(sub_5m) < 6:
                continue

            for j in range(5, len(sub_5m)-2):
                # 2. True MSS: Break of recent 5M Swing High (10 bars)
                swing_high_5m = float(sub_5m['High'].iloc[j-5:j].max())
                mss_break = float(sub_5m['Close'].iloc[j]) > swing_high_5m
                
                # 3. FVG Presence (Bullish Gap)
                fvg_present = float(sub_5m['Low'].iloc[j]) > float(sub_5m['High'].iloc[j-2])
                
                if mss_break and fvg_present:
                    ob_level = float(sub_5m['Low'].iloc[j-1])  # Order Block zone
                    entry_price = float(sub_5m['Close'].iloc[j])
                    
                    # Stop Loss below sweep low
                    sl = round(sweep_low * 0.998, 2)  # 0.2% buffer below sweep low
                    target = round(float(df_1h['High'].iloc[max(0, i-20):i].max()), 2)
                    
                    risk = entry_price - sl
                    reward = target - entry_price
                    
                    if risk <= 0 or reward <= 0:
                        break
                        
                    target_rr = round(reward / risk, 2)
                    entry_time = sub_5m.index[j]
                    
                    # 4. Outcome Evaluation on Future 5M Candles
                    future_candles = df_5m[df_5m.index > entry_time]
                    
                    result = "PENDING"
                    for _, candle in future_candles.iterrows():
                        low_val = float(candle['Low'])
                        high_val = float(candle['High'])
                        
                        if low_val <= sl:
                            result = "LOSS"
                            losses += 1
                            total_r -= 1.0
                            break
                        elif high_val >= target:
                            result = "WIN"
                            wins += 1
                            total_r += target_rr
                            break
                    
                    if result != "PENDING":
                        trade_logs.append({
                            "Date": str(entry_time)[:16],
                            "Entry": round(entry_price, 2),
                            "SL": sl,
                            "Target": target,
                            "R:R": target_rr,
                            "Outcome": result
                        })
                    break  # Limit 1 trade per 1H sweep event

    total_trades = wins + losses
    if total_trades > 0:
        win_rate = round((wins / total_trades) * 100, 2)
        df_results = pd.DataFrame(trade_logs)
        print(df_results.to_string(index=False))
        print("\n------------------------------------------")
        print(f"📊 ACCURATE SMC REPORT FOR {ticker}:")
        print(f"Total Trades Evaluated : {total_trades}")
        print(f"✅ Total Wins          : {wins}")
        print(f"❌ Total Losses        : {losses}")
        print(f"🎯 Real Win Rate       : {win_rate}%")
        print(f"💰 Net R Gained        : {round(total_r, 2)} R")
        print("------------------------------------------")
    else:
        print("No valid SMC setups matched the strict conditions.")

if __name__ == "__main__":
    run_refined_smc_backtest("TECHM.NS")
    run_refined_smc_backtest("INFY.NS")
    run_refined_smc_backtest("RELIANCE.NS")