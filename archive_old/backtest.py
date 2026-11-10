import yfinance as yf
import pandas as pd

def backtest_smc(ticker):
    print(f"\n==========================================")
    print(f"       Backtesting SMC Setup: {ticker}")
    print(f"==========================================")
    
    # 60 days of 1-Hour and 5-Minute Data
    df_1h = yf.download(ticker, period="60d", interval="1h", progress=False)
    df_5m = yf.download(ticker, period="60d", interval="5m", progress=False)

    if df_1h.empty or df_5m.empty:
        print("Data unavailable.")
        return

    if isinstance(df_1h.columns, pd.MultiIndex):
        df_1h.columns = df_1h.columns.get_level_values(0)
    if isinstance(df_5m.columns, pd.MultiIndex):
        df_5m.columns = df_5m.columns.get_level_values(0)

    trades = []
    
    for i in range(20, len(df_1h)-1):
        ssl_level = float(df_1h['Low'].iloc[i-20:i-1].min())
        current_1h_low = float(df_1h['Low'].iloc[i])
        
        # 1H SSL Sweep
        if current_1h_low < ssl_level:
            sweep_time = df_1h.index[i]
            sub_5m = df_5m[df_5m.index >= sweep_time].head(12) # Next 1 hour in 5m candles
            
            for j in range(2, len(sub_5m)):
                recent_high_5m = float(sub_5m['High'].iloc[j-5:j-1].max()) if j >= 5 else float(sub_5m['High'].iloc[0:j].max())
                mss = float(sub_5m['Close'].iloc[j]) > recent_high_5m
                fvg = float(sub_5m['Low'].iloc[j]) > float(sub_5m['High'].iloc[j-2])
                
                if mss and fvg:
                    entry = float(sub_5m['Close'].iloc[j])
                    sl = float(sub_5m['Low'].iloc[max(0, j-5):j+1].min())
                    target = float(df_1h['High'].iloc[max(0, i-20):i].max())
                    
                    risk = entry - sl
                    reward = target - entry
                    
                    if risk > 0 and reward > 0:
                        rr = round(reward / risk, 2)
                        trades.append({
                            "Date": str(sweep_time)[:16],
                            "Entry": round(entry, 2),
                            "SL": round(sl, 2),
                            "Target": round(target, 2),
                            "RR": rr
                        })
                    break

    df_results = pd.DataFrame(trades)
    
    if not df_results.empty:
        print(f"Total Trade Signals: {len(df_results)}")
        print(df_results.head(10).to_string(index=False))
        print(f"\nAverage Risk to Reward (R:R): 1:{df_results['RR'].mean():.2f}")
    else:
        print("No valid setup patterns found in the past 60 days.")

if __name__ == "__main__":
    backtest_smc("TECHM.NS")
    backtest_smc("INFY.NS")
    backtest_smc("RELIANCE.NS")