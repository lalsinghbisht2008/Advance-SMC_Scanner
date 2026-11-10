# SMC Scanner v2

Ek hi clean scanner: **India (NSE/BSE + MCX via Upstox)**, **Crypto (Binance)**, **Forex/Gold/Silver (Yahoo)**,
Telegram alerts ke saath, buy aur sell dono side, aur har alert ka SL/TP result track hota hai.

## Kya karta hai (SMC flow)

HTF liquidity -> LTF sweep -> MSS -> IDM -> (BOS) -> FVG/OB par limit entry.

| Profile | HTF (liquidity) | LTF (entry) | Kab |
|---|---|---|---|
| `5m` (default) | 1H + previous-day high/low | 5m | intraday |
| `15m` | 4H | 15m | intraday / BTST |
| `swing` | 1D | 1H | swing |

Bullish setup ke rules (bearish bilkul mirror):
1. **Liquidity pool** neeche: HTF swing low / equal lows / previous-day low / internal LTF low (jo pehle trade-through na hua ho).
2. **Sweep**: wick pool ke neeche, aur 3 candle ke andar close wapas upar (close neeche raha toh breakdown hai, sweep nahi).
3. **MSS**: sweep ke baad candle **close** us last LTF swing high ke upar jo sweep-low se pehle bana tha.
4. **Displacement + FVG**: strong bullish candle aur imbalance.
5. **IDM**: leg ke andar pehla pullback low. Jab tak IDM sweep nahi hota, high ko HH confirm nahi maante. IDM sweep hone ke baad hi entry zone active hota hai.
6. **BOS**: IDM taken ke **baad** HH ko candle close se todna. IDM se pehle ka close BOS nahi gina jata.
7. **POI/Entry**: order block (50% par limit) + FVG confluence. **SL** sweep-low ke neeche. **TP1** agla opposite liquidity (min 1.5R), **TP2** uske aage. TP1 par 50% book + SL entry par.
8. **Filters/score (max 11)**: HTF liquidity, strong displacement, OB+FVG, HTF bias (IDM-validated structure), discount/premium, IDM taken, kill-zone, volume, RR. Default `min_score = 6`.
9. Longs sirf **discount** mein, shorts sirf **premium** mein (`require_discount`).

Telegram par ye alerts aate hain: **NEW SETUP** (WATCH = IDM abhi baki / PENDING = IDM taken), **IDM TAKEN**, **ENTRY FILLED**, **TP1**, **TP2 / SL / BE / EOD**, **EXPIRED / CANCELLED**. Data stale ya token expire hone par health alert bhi.

## Setup (10 minute)

1. **Pehle purana Telegram token revoke karein** (BotFather -> `/revoke`). Purane `config.py` mein token plain text mein tha, history mein bhi rahega.
2. `pip install -r requirements.txt`
3. `.env.example` ko `.env` banakar teen values bharein: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `UPSTOX_ACCESS_TOKEN` (1-year Analytics Token chalega, ye read-only market data ke liye hai).
4. Check: `python run.py selftest --telegram` (token, symbol resolve, candles ki freshness, Telegram sab dikhata hai).
5. Test: `python run.py scan --market india --dry-run`

### Local server par (recommended, 24/7)
```
python run.py loop --market india,crypto,forex          # har 5 min, candle close ke 6 sec baad
```
`systemd`/`tmux`/`pm2` se chalayein. Sirf wahi market scan hota hai jo us waqt open hai.

### GitHub Actions par
Repo Settings -> Secrets -> Actions mein teeno secrets daalein. `.github/workflows/scanner.yml` ek hi workflow hai (concurrency lock ke saath). GitHub cron kabhi 5-15 min late ho sakta hai; isliye 24/7 ke liye local server behtar hai. Private repo par free minutes limited hote hain.

## Commands
```
python run.py scan --market auto                 # jo market open ho
python run.py scan --market india --profile 5m,15m --symbols RELIANCE,NIFTY
python run.py loop --market india --every 5
python run.py selftest --market india --symbol NIFTY
python run.py summary --send                     # aaj ke trades ka R summary Telegram par
python backtest.py --market crypto --symbol BTCUSDT --profile 5m --days 30
python -m pytest tests
```

## 1000+ stocks (batch mode)
`symbols.txt` mein ek line par ek symbol rakhein, phir:
```
python run.py scan --market india --symbols-file symbols.txt --batch-size 40 --dry-run
```
Har run agla batch leta hai aur pointer `.cache/batch_ptr.json` mein save hota hai (dry-run mein bhi), end par wapas shuru se. Har 3 minute par apne aap:
```
python run.py loop --market india --symbols-file symbols.txt --batch-size 40 --every 3
```
Upstox limit 2000 calls / 30 min = ~200 calls per 3-min run. Naye symbol ke ~5 calls lagte hain (pehla pass), uske baad din bhar ~2 calls (beeta data cache hota hai). Isliye pehle din `--batch-size 40`, cache garam hone par 80-100. Limit khatam hone par scanner ruk-ruk kar nahi atakta, wo symbols skip karke agle batch mein aate hain. Manual (alag-alag) commands ka limiter alag process mein reset hota hai, isliye batch-size chhota rakhein.

## Settings kahan badalni hain
- Watchlist, kill-zones, sessions, profiles: `smc/config.py`
- Strategy parameters (swing strength, displacement, RR, entry mode, `require_idm`, `min_score`): `smc/engine.py -> Params`
- Entry mode: `entry_mode = "mid" | "proximal" | "distal"` (OB ka 50% / upar ka edge / neeche ka edge)

## Data sources
- **India:** Upstox API V3 `historical-candle` (beete din) + `intraday` (aaj ka) merge hota hai, native timeframes (5m, 15m, 1h, 4h, 1d). Symbol -> instrument key official instrument master se runtime par resolve hota hai, ISIN hardcode nahi.
- **MCX:** Upstox futures, nearest expiry (expiry se 2 din pehle next contract).
- **Crypto:** Binance public klines (`data-api.binance.vision` pehle, kyunki GitHub ke US servers par `api.binance.com` block hota hai).
- **Forex/Gold/Silver:** Yahoo chart API (`GC=F`, `SI=F` futures hain, spot se thoda alag). Upstox par EURUSD jaise global forex pairs nahi milte.

## Zaroori sacchai (limits)
- Ye alert tool hai, auto-trader nahi. Financial advice nahi.
- Mere sandbox se internet access nahi tha, isliye **live Upstox/Binance/Yahoo/Telegram calls maine khud nahi chalayi**. Parsing, URLs, retries, rate-limit sab mocked responses se test hue hain (66 tests). Pehle `selftest` zaroor chalayein.
- Logic synthetic data par verify hua hai (buy/sell mirror, no-repaint, SL/TP rules). **Real market par profitability prove nahi hui.** `backtest.py` apne data par chalayein, aur 30 se kam trades ka result mat maanein.
- IDM: agar leg mein koi pullback low hi nahi (pure impulse), toh wahan IDM define nahi hota aur setup skip hota hai (`require_idm=False` karne par `NO_IDM` stage ke saath aayega).
- NSE holiday par data nahi aata; scanner khud skip/stale warning deta hai.

## Purani files
Sab purani files `archive_old/` mein safe hain (token hata diya gaya hai). Details: `AUDIT.md`.

### GitHub repo ko saaf karne ke commands
Apne repo ke clone mein (naye project ki files copy karne se pehle):
```
git rm -r .github/workflows                  # purane 7 workflows
git rm -r --ignore-unmatch *.py *.json run_scanner.yml requirements.txt
# is zip ki saari files (archive_old/ samet) repo mein copy karein, phir:
git add -A
git commit -m "SMC scanner v2"
git push
```
Aur GitHub par: Settings -> Secrets -> Actions mein `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `UPSTOX_ACCESS_TOKEN` banayein.
