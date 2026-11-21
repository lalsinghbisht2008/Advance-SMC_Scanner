"""PNG charts for Telegram: HTF structure map (top) + LTF entry model (bottom). matplotlib/Agg, dark theme."""
from __future__ import annotations

import io
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .engine import Frame  # noqa: E402
from .structure import build_map  # noqa: E402

BG, FG, GRID = "#131722", "#d1d4dc", "#232734"
UP, DN = "#26a69a", "#9598a1"
BULL, BEAR, TXT = "#2ebd85", "#f23645", "#e6c229"
IST = "Asia/Kolkata"


def _candles(ax, df: pd.DataFrame):
    x = np.arange(len(df))
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    col = np.where(c >= o, UP, DN)
    ax.vlines(x, l, h, colors=col, linewidth=0.8, zorder=2)
    ax.bar(x, np.maximum(abs(c - o), (h.max() - l.min()) * 0.0015), bottom=np.minimum(o, c),
           color=col, width=0.7, zorder=3)


def _style(ax, df: pd.DataFrame, title: str, extra_right: int):
    ax.set_facecolor(BG)
    ax.grid(color=GRID, linewidth=0.5)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8)
    ax.yaxis.tick_right()
    n = len(df)
    ax.set_xlim(-1, n + extra_right)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    loc = df.index.tz_convert(IST)
    ax.set_xticks(ticks)
    ax.set_xticklabels([loc[i].strftime("%d %b %H:%M") if (loc[1] - loc[0]) < pd.Timedelta(days=1)
                        else loc[i].strftime("%d %b") for i in ticks])
    lo, hi = df["low"].min(), df["high"].max()
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_title(title, color=FG, fontsize=10, loc="left")


def _xpos(df: pd.DataFrame, ts) -> Optional[int]:
    if ts is None:
        return None
    i = int(df.index.searchsorted(pd.Timestamp(ts)))
    return min(i, len(df) - 1)


def draw_structure(ax, htf_df: pd.DataFrame, htf_tf: str, symbol: str, bars: int = 120, htf_n: int = 3):
    f = Frame.from_df(htf_df, htf_tf, htf_n)
    m = build_map(f)
    off = max(0, len(htf_df) - bars)
    d = htf_df.iloc[off:]
    _candles(ax, d)
    _style(ax, d, f"{symbol} · {htf_tf} structure", extra_right=12)
    for x0, x1, price, label, side in m["lines"]:
        if x1 < off:
            continue
        col = BULL if side == "bull" else BEAR
        a, b = max(x0 - off, 0), x1 - off
        ax.hlines(price, a, b + 4, colors=col, linewidth=1.1, zorder=4)
        ax.annotate("", (b + 4, price), (b + 3, price), arrowprops=dict(arrowstyle="->", color=col), zorder=4)
        ax.text(a + 0.5, price, label, color=TXT, fontsize=8, ha="left", va="bottom", zorder=5,
                bbox=dict(facecolor=BG, edgecolor="none", pad=0.4, alpha=0.8))
    for x0, xe, price, label, side in m["rays"]:        # LL/HH/LH/HL levels extended until broken
        if (xe if xe is not None else len(htf_df)) < off:
            continue
        col = BULL if side == "bull" else BEAR
        a = max(x0 - off, 0)
        b = (xe - off) if xe is not None else len(d) + 6
        ax.hlines(price, a, b, colors=col, linewidth=0.9, linestyles=(0, (4, 3)), alpha=0.8, zorder=3)
    for idx, price, label, side in m["pts"]:
        if idx < off:
            continue
        up = label in ("HH", "LH")
        ax.annotate(label, (idx - off, price), xytext=(0, 9 if up else -9), textcoords="offset points",
                    ha="center", va="bottom" if up else "top", color=TXT, fontsize=9, fontweight="bold", zorder=6)
    return m


def draw_entry(ax, ltf_df: pd.DataFrame, t: dict, bars: int = 130):
    off = max(0, len(ltf_df) - bars)
    d = ltf_df.iloc[off:]
    _candles(ax, d)
    _style(ax, d, f"{t['symbol']} · {t['ltf']} entry model  ({t['side']})", extra_right=18)
    n = len(d)
    buy = t["side"] == "BUY"
    zc = BULL if buy else BEAR

    def hline(price, col, label, ls="-"):
        if price is None:
            return
        ax.hlines(price, 0, n + 17, colors=col, linewidth=1.0, linestyles=ls, zorder=4)
        ax.text(n + 17, price, f"{label} {price:.2f}", color=col, fontsize=7.5, ha="right", va="bottom", zorder=5)

    zx = _xpos(d, t.get("sweep_time")) or 0
    for key, col in (("ob", "#4f8cff"), ("fvg", "#c77dff")):
        if t.get(key):
            lo, hi = t[key]
            ax.add_patch(Rectangle((zx, lo), n + 17 - zx, hi - lo, color=col, alpha=0.25, zorder=1))
            ax.text(zx, hi, key.upper(), color=col, fontsize=8, va="bottom", zorder=5)
    hline(t.get("pool_level"), TXT, "sweep lvl", ":")
    hline(t.get("mss_level"), FG, "MSS", ":")
    if t.get("idm_level") is not None:
        hline(t["idm_level"], "#ff9800", "IDM", "--")
    hline(t["entry"], "#4f8cff", "ENTRY")
    hline(t["sl"], BEAR, "SL")
    hline(t["tp1"], BULL, "TP1")
    hline(t["tp2"], BULL, "TP2", "--")
    for key, lab in (("sweep_time", "sweep"), ("mss_time", "MSS")):
        x = _xpos(d, t.get(key))
        if x is not None and t.get(key) is not None and pd.Timestamp(t[key]) >= d.index[0]:
            y = d["low"].iloc[x] if buy == (key == "sweep_time") else d["high"].iloc[x]
            ax.annotate(lab, (x, y), xytext=(0, -14 if y == d["low"].iloc[x] else 14), textcoords="offset points",
                        ha="center", color=zc, fontsize=8, arrowprops=dict(arrowstyle="-", color=zc))


def render(trade: dict, ltf_df: pd.DataFrame, htf_df: pd.DataFrame, htf_n: int = 3) -> bytes:
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw=dict(height_ratios=[1.1, 1]))
    fig.patch.set_facecolor(BG)
    draw_structure(a1, htf_df, trade["htf"], trade["symbol"], htf_n=htf_n)
    side = "SELL" if trade["side"] == "SELL" else "BUY"
    if trade.get("htf_idm_level") is not None:
        a1.axhline(trade["htf_idm_level"], color="#ff9800", linestyle="--", linewidth=0.9, zorder=4)
        a1.text(0.01, 0.02, f"{trade['htf']} IDM swept @ {trade['htf_idm_level']:.2f}  ->  {side} model active",
                transform=a1.transAxes, color="#ff9800", fontsize=9, va="bottom")
    draw_entry(a2, ltf_df, trade)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def render_structure_only(symbol: str, htf_df: pd.DataFrame, htf_tf: str, ltf_df: Optional[pd.DataFrame] = None,
                          ltf_tf: str = "", htf_n: int = 3) -> tuple:
    """Chart for `run.py chart`: 4H structure map (+ plain LTF). Returns (png_bytes, state)."""
    two = ltf_df is not None and len(ltf_df) > 0
    fig, axes = plt.subplots(2 if two else 1, 1, figsize=(12, 10 if two else 6))
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor(BG)
    m = draw_structure(axes[0], htf_df, htf_tf, symbol, htf_n=htf_n)
    st = m["state"]
    prof_tf = htf_tf
    txt = []
    for side, d in (("BUY", st["buy"]), ("SELL", st["sell"])):
        if d["state"] == "SWEPT":
            txt.append(f"{side}: {prof_tf} IDM swept @ {d['level']:.2f} -> {ltf_tf or 'LTF'} model ON")
        elif d["state"] == "WAIT":
            txt.append(f"{side}: IDM {d['level']:.2f} not swept yet (waiting)")
    axes[0].text(0.01, 0.02, "\n".join(txt) or "no fresh 4H IDM sweep (15m model OFF)", transform=axes[0].transAxes,
                 color="#ff9800", fontsize=9, va="bottom")
    if two:
        d = ltf_df.iloc[-130:]
        _candles(axes[1], d)
        _style(axes[1], d, f"{symbol} · {ltf_tf}", extra_right=4)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue(), st
