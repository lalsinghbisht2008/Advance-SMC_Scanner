"""Telegram alerts. HTML parse mode (safe escaping), status checks, retries, splitting."""
from __future__ import annotations

import html
import logging
import time

import pandas as pd
import requests

from .config import OPTION_STEP, env

log = logging.getLogger("smc.notify")
LIMIT = 4000


class Telegram:
    def __init__(self, token: str = "", chat_id: str = "", session=None):
        self.token = token or env("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
        self.chat_id = chat_id or env("TELEGRAM_CHAT_ID")
        self.http = session or requests
        self.sent = 0
        self.failed = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing)")
            return False
        ok = True
        for chunk in _split(text):
            ok = self._post(chunk) and ok
        return ok

    def _post(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        for attempt in range(3):
            try:
                r = self.http.post(url, json=payload, timeout=15)
                if r.status_code == 200 and r.json().get("ok"):
                    self.sent += 1
                    return True
                if r.status_code == 429:
                    wait = 2.0
                    try:
                        wait = float(r.json().get("parameters", {}).get("retry_after", 2))
                    except Exception:
                        pass
                    time.sleep(min(wait, 20))
                    continue
                # 400/401/403 etc: log the reason (never the token)
                log.error("Telegram error %s: %s", r.status_code, r.text[:200])
                break
            except requests.RequestException as e:
                log.error("Telegram network error: %s", type(e).__name__)
                time.sleep(1.5 * (attempt + 1))
        self.failed += 1
        return False


def _split(text: str) -> list:
    if len(text) <= LIMIT:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > LIMIT:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        parts.append(cur)
    return parts


# --------------------------------------------------------------------------- formatting
def _e(x) -> str:
    return html.escape(str(x))


def fmt_price(x) -> str:
    if x is None:
        return "-"
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.2f}"
    if ax >= 10:
        return f"{x:.3f}".rstrip("0").rstrip(".") if f"{x:.3f}"[-1] == "0" else f"{x:.3f}"
    if ax >= 1:
        return f"{x:.5f}".rstrip("0").rstrip(".")
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _ist(ts) -> str:
    return pd.Timestamp(ts).tz_convert("Asia/Kolkata").strftime("%d %b %H:%M IST")


def setup_message(t: dict) -> str:
    buy = t["side"] == "BUY"
    icon = "🟢" if buy else "🔴"
    if t["status"] != "PENDING":
        state = "⚡ TRIGGERED – price is in the zone"
    elif t.get("stage") == "WAIT_IDM":
        state = "⏳ WATCH – IDM abhi sweep nahi hua; sweep ke baad hi zone par entry"
    else:
        state = "⏳ PENDING – IDM taken, limit entry zone par"
    idm_line = None
    if t.get("idm_level") is not None:
        if t.get("idm_taken_time"):
            idm_line = f"🧩 IDM taken @ {fmt_price(t['idm_level'])} → HH {fmt_price(t['hh_level'])} validated" + \
                       (" · BOS ✔" if t.get("bos_time") else " · BOS pending")
        else:
            idm_line = f"🧩 IDM level {fmt_price(t['idm_level'])} (sweep pending)"
    ob = f"OB {fmt_price(t['ob'][0])} – {fmt_price(t['ob'][1])}" if t.get("ob") else "OB –"
    fvg = f"FVG {fmt_price(t['fvg'][0])} – {fmt_price(t['fvg'][1])}" if t.get("fvg") else "FVG –"
    risk = abs(t["entry"] - t["sl"])
    lines = [
        f"{icon} <b>{t['side']} SETUP · {_e(t['symbol'])}</b>  <i>({_e(t['market_label'])} · {_e(t['htf'])}→{_e(t['ltf'])})</i>",
        f"Score <b>{t['score']}/11</b> · bias {_e(t['bias'])} · {_e(t['zone_pd'])}",
        "",
        f"🧲 {_e(t['pool_kind'])} swept @ {fmt_price(t['pool_level'])} (wick {fmt_price(t['sweep_extreme'])}, reclaimed)",
        f"🏗 MSS: close beyond {fmt_price(t['mss_level'])} + displacement",
        f"📦 {ob} · {fvg}",
    ] + ([idm_line] if idm_line else []) + [
        "",
        state,
        f"📍 Entry <b>{fmt_price(t['entry'])}</b>",
        f"🛑 SL <b>{fmt_price(t['sl'])}</b>  (risk {fmt_price(risk)} = {risk / t['entry'] * 100:.2f}%)",
        f"🎯 TP1 <b>{fmt_price(t['tp1'])}</b> ({t['rr1']:.1f}R, {_e(t['tp_kind'])}) · TP2 <b>{fmt_price(t['tp2'])}</b> ({t['rr2']:.1f}R)",
        f"↪️ TP1 par 50% book + SL entry par",
    ]
    step = OPTION_STEP.get(t["symbol"])
    if step:
        atm = round(t["entry"] / step) * step
        lines.append(f"🎫 Option idea: ATM ~{atm} {'CE' if buy else 'PE'} (spot setup, option price alag check karein)")
    lines += ["", "✔ " + " · ".join(_e(r) for r in t["reasons"]),
              f"🕒 MSS {_ist(t['mss_time'])}", "<i>Alert only – not financial advice.</i>"]
    return "\n".join(lines)


EVENT_TEXT = {
    "IDM_TAKEN": "🧩 <b>IDM TAKEN</b> – HH validated, entry zone ab active",
    "FILLED": "⚡ <b>ENTRY FILLED</b>",
    "TP1": "🎯 <b>TP1 HIT</b> – 50% booked, SL → entry",
    "TP2": "🏆 <b>TP2 HIT</b> – trade closed",
    "SL": "🛑 <b>STOP LOSS HIT</b>",
    "BE": "➖ <b>Closed at break-even</b> (after TP1)",
    "EOD": "🔔 <b>End-of-session exit</b>",
    "CANCELLED": "❎ <b>Setup cancelled</b> – target reached without entry",
    "EXPIRED": "⌛ <b>Setup expired</b> – no fill",
}


def event_message(t: dict, kind: str, price: float, when, r=None) -> str:
    icon = "🟢" if t["side"] == "BUY" else "🔴"
    txt = f"{EVENT_TEXT.get(kind, kind)}\n{icon} {_e(t['side'])} {_e(t['symbol'])} ({_e(t['htf'])}→{_e(t['ltf'])})\n"
    txt += f"@ {fmt_price(price)} · {_ist(when)}"
    if r is not None and kind in ("TP2", "SL", "BE", "EOD"):
        txt += f"\nResult: <b>{r:+.2f}R</b>"
    return txt


def health_message(title: str, detail: str) -> str:
    return f"⚠️ <b>{_e(title)}</b>\n{_e(detail)}"
