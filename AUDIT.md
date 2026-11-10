# Purane code ka audit (jo mila aur v2 mein kya kiya)

Maine zip ki saari scanner files padhi. Neeche sirf wahi baatein hain jo code mein dekhi gayi.

## A. Security / setup
| Problem | Fix |
|---|---|
| `config.py` mein Telegram bot token plain text mein commit tha | Token revoke karna zaroori. v2 sirf env / `.env` / GitHub Secrets padhta hai. `archive_old/` se token hata diya gaya hai |
| `config.py` ki stock list mein commas missing (jaise `"ICICIBANK.NS" "OLAELEC.NS"`), Python dono ko jodkar ek galat string bana deta hai | Naya watchlist `smc/config.py` mein |
| 7 workflows (`scanner.yml`, `smc_scanner.yml`, `nifty_scanner.yml`, `swing_scanner.yml`, `global_smc_scanner.yml`, `smc_global_scanner.yml`, `run_scanner.yml`) ek saath chalte the | 1 workflow, concurrency lock |
| `smc_live_scanner.py`, `smc_master_scanner.py`, `smc_swing_scanner.py` bilkul identical (same md5), 9 alag backtest files | Ek engine + ek `backtest.py` |

## B. Data
| Problem | Fix |
|---|---|
| Upstox **V2 historical-candle** endpoint par `1minute` mangta tha. Upstox docs ke hisaab se aaj ke live candles ke liye alag *intraday* endpoint hai, toh market ke beech mein scanner purana data dekh sakta tha | V3: historical (beete din) + intraday (aaj) merge, native 5m/15m/1h/4h/1d |
| Global scanner mein keys jaise `NSE_FX|EURUSD`, `NSE_EQ|BTC` — Upstox par global forex/crypto nahi milta | Crypto: Binance, Forex/Gold/Silver: Yahoo, India/MCX: Upstox |
| 1H/4H candles 1m data se midnight-anchor par resample hote the (NSE ka session 09:15 se hai) aur **chalta hua (adhura) candle** bhi signal mein use hota tha = repaint | Native HTF candles, sirf **closed** candles (session-aware), pivots sirf confirm hone ke baad |
| Hardcoded ISIN list maintain karna mushkil (rename/demerger par key tootti hai) | Instrument master se symbol -> key runtime par |
| GitHub runner UTC mein `datetime.now()` | IST/UTC explicit |
| Stale data ka koi guard nahi | Stale check + Telegram health alert |
| Token expiry ka pata nahi chalta | Expiry se 14 din pehle alert, 401 par alert |

## C. SMC logic (jo "advance concept mein kuch lag hai" tha)
| Purana | Ab |
|---|---|
| Live/global/strict scanners mein sirf BUY side (SELL code hi nahi) | Dono side, bearish = price-inverted copy par wahi code (test se proved) |
| "Sweep" = pichhle ~20 candle ka sabse neecha low, swing/liquidity nahi | Real pools: HTF swing, equal highs/lows, PDH/PDL, internal |
| Sweep ke liye close wapas upar hona zaroori nahi tha (global scanner) | Sweep = wick + 3 candle ke andar reclaim, warna breakdown |
| MSS = sweep se pehle ke 10 candle ka max high ya koi bhi swing high; MSS sweep ke **baad** hua ya nahi check nahi hota tha | MSS = sweep ke baad, sweep-low se pehle ke last swing high ke upar **close** |
| Structure: koi bhi swing break = BOS, IDM ka concept nahi | IDM-validated HH/HL: IDM sweep ke baad hi HH valid, uske baad close = BOS |
| OB = pehli bearish candle jo mile (purani), mitigation check nahi | Leg ke origin par last bearish candle, SL hit hone par setup invalid |
| Entry = current price par, SL = fixed % | Limit entry OB mein, SL sweep-extreme ke neeche (ATR buffer), TP = next liquidity |
| Premium/discount filter nahi | Long sirf discount, short sirf premium |
| HTF bias nahi | IDM-validated structure se bias, score mein |
| Entry ke baad zone se bahar (price SSL ke neeche) bhi entry ban jaati thi | Reclaim zaroori, SL ke neeche gaya toh setup dead |

## D. Alerts / tracking
| Purana | Ab |
|---|---|
| Trade ID mein last candle ka time tha, toh wahi setup har 5 min naya ID banata = duplicate spam | ID = symbol + profile + side + MSS candle, ek setup = ek alert |
| `active_trades.json` mein trades jama hote the, SL/TP kabhi check nahi hota tha, `trade_history.json` khali | Har trade ka lifecycle: pending -> IDM -> fill -> TP1 -> TP2/SL/BE/EOD, R-multiple history mein |
| Telegram `parse_mode=Markdown` — `_`, `&` (jaise M&M) wale symbols par message chup-chaap fail; response check nahi | HTML mode + escape, status check, 429 retry, 4096 split |
| `[cite: 2]` jaisa copy-paste kachra alerts/state mein mila (`active_global_trades.json`) | Saaf message format |
| Stocks batches mein rotate hote the, har stock kam baar scan hota tha | Saare symbols har run mein, rate limiter ke saath |

## E. Jo abhi bhi aap ko dekhna hai
- Live API calls mere sandbox se test nahi hue (internet nahi tha): `python run.py selftest --telegram` chalayein.
- Real data par backtest chalayein, defaults (`min_score`, `entry_mode`, `swing_n`) apne market ke hisaab se tune karein.
- Option chain ka SMC (purana `nifty_intraday_scanner.py`) v2 mein nahi hai: v2 index par setup deta hai aur ATM CE/PE ka idea likhta hai, option premium chart par scan nahi karta.
