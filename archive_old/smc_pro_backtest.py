import yfinance as yf
import pandas as pd

def run_pro_smc_backtest(ticker):
    print(f"\n==========================================")
    print(f"   PRO SMC BACKTEST (WITH TRAILING BE): {ticker}")
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

    for i in range(20, len(df_1h)-20):
        ssl_level = float(df_1h['Low'].iloc[i-20:i].min())
        c_1h_low = float(df_1h['Low'].iloc[i])
        c_1h_close = float(df_1h['Close'].iloc[i])
        
        # 1. 1H SSL Sweep
        if c_1h_low < ssl_level and c_1h_close > c_1h_low:
            sweep_time = df_1h.index[i]
            sweep_low = c_1h_low
            
            sub_5m = df_5m[(df_5m.index >= sweep_time) & (df_5m.index <= sweep_time + pd.Timedelta(hours=2))]
            
            if len(sub_5m) < 6:
                continue

            for j in range(5, len(sub_5m)-2):
                swing_high_5m = float(sub_5m['High'].iloc[j-5:j].max())
                mss_break = float(sub_5m['Close'].iloc[j]) > swing_high_5m
                fvg_present = float(sub_5m['Low'].iloc[j]) > float(sub_5m['High'].iloc[j-2])
                
                if mss_break and fvg_present:
                    entry_price = float(sub_5m['Close'].iloc[j])
                    sl = round(sweep_low * 0.998, 2) # Buffer below sweep low
                    target_bsl = round(float(df_1h['High'].iloc[max(0, i-20):i].max()), 2)
                    
                    risk = entry_price - sl
                    if risk <= 0:
                        break
                        
                    # Target 1: Fixed 1:3 RR | Target 2: BSL
                    target_1to3 = round(entry_price + (risk * 3.0), 2)
                    final_target = min(target_bsl, target_1to3) if target_bsl > entry_price else target_1to3
                    
                    entry_time = sub_5m.index[j]
                    future_candles = df_5m[df_5m.index > entry_time]
                    
                    result = "PENDING"
                    is_be_triggered = False
                    current_sl = sl
                    
                    for _, candle in future_candles.iterrows():
                        c_low = float(candle['Low'])
                        c_high = float(candle['High'])
                        
                        # Rule 1: Move SL to Break-Even at 1:1.5 R:R profit
                        if not is_be_triggered and c_high >= (entry_price + (risk * 1.5)):
                            current_sl = entry_price # Risk reduced to 0
                            is_be_triggered = True
                            
                        # Rule 2: Check SL / BE Hit
                        if c_low <= current_sl:
                            if is_be_triggered:
                                result = "BREAK-EVEN"
                                breakevens += 1
                                # 0 R gain/loss
                            else:
                                result = "LOSS"
                                losses += 1
                                total_r -= 1.0
                            break
                            
                        # Rule 3: Check Target Hit (1:3 RR)
                        elif c_high >= final_target:
                            result = "WIN"
                            wins += 1
                            total_r += 3.0 # Secured 1:3 R:R
                            break
                    
                    if result != "PENDING":
                        trade_logs.append({
                            "Date": str(entry_time)[:16],
                            "Entry": round(entry_price, 2),
                            "SL": sl,
                            "Target": final_target,
                            "Outcome": result
                        })
                    break

    total_trades = wins + losses + breakevens
    if total_trades > 0:
        win_rate = round((wins / total_trades) * 100, 2)
        df_results = pd.DataFrame(trade_logs)
        print(df_results.to_string(index=False))
        print("\n------------------------------------------")
        print(f"📊 PRO SMC REPORT WITH TRAILING BE ({ticker}):")
        print(f"Total Signals Evaluated : {total_trades}")
        print(f"✅ Total Wins (1:3 R:R)  : {wins}")
        print(f"🛡️ Total Break-Evens (0R): {breakevens}")
        print(f"❌ Total Losses (-1R)    : {losses}")
        print(f"🎯 Real Win Rate        : {win_rate}%")
        print(f"💰 Net Profit Gained     : +{round(total_r, 2)} R")
        print("------------------------------------------")

if __name__ == "__main__":
    run_pro_smc_backtest("TECHM.NS")
    run_pro_smc_backtest("INFY.NS")
    run_pro_smc_backtest("RELIANCE.NS")