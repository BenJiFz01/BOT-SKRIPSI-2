"""
templates.py
============
Format pesan sinyal untuk Telegram (HTML mode).

Telegram mendukung emoji dan karakter unicode penuh.
File ini hanya menghasilkan string -- tidak ada print() ke terminal,
jadi tidak ada masalah encoding Windows.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from src.models.signal import Signal


_WIB = timezone(timedelta(hours=7))


def _to_wib_str(iso_str: str) -> str:
    """
    Konversi ISO timestamp ke format 'YYYY-MM-DD HH:MM WIB'.
    Fallback ke string asli jika parse gagal.
    """
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_wib = dt.astimezone(_WIB)
        return dt_wib.strftime("%Y-%m-%d %H:%M WIB")
    except Exception:
        return iso_str


def format_signal(sig: Signal, signal_id: str = "") -> str:
    """
    Format sinyal menjadi pesan HTML untuk Telegram.

    Contoh output:
        🟢 SINYAL BUY — XAUUSD
        TF: H1  |  2026-07-20 14:00 WIB
        ID: XAUUSD_H1_20260720_140000

        📌 Entry Zone : 3310.00 – 3313.00
        🛑 Stop Loss  : 3296.50  (ATR-based)
        🎯 TP1        : 3329.00  (RR 1.5)
        🎯 TP2        : 3341.00  (RR 2.5)
        🎯 TP3        : 3357.00  (RR 4.0)
        📊 RR         : 1.85R

        ── Analisis Teknikal ──────────────
        📈 HTF Bias   : M15:BULL H4:BULL D1:BULL
        🧩 Trigger    : 5/6 [EMA200+ EMA50+ ALIGN+ RSI+(42) MACD+ CDL+]
        💎 Confluence : 5 [Pattern+ Fib+ SnR+ SnD+ Div+]
        🕯 Pattern    : ENGULFING, MORNINGSTAR
        📐 Fibonacci  : FIB_STRONG(fib_0.618=3311.50)
        🔲 SnR        : S~3305.20 R~3340.00
        📦 Zone       : SND_DEMAND(3308.50-3313.00)
        🔀 Divergence : RSI_DIV
        🕐 Sesi       : London
        📉 ATR        : 12.5000

        ⚠️ Rekomendasi manual — bukan auto-trade.
    """
    # Header emoji sesuai arah
    emoji = "\U0001f7e2" if sig.direction == "BUY" else "\U0001f534"  # 🟢 / 🔴
    dash  = "\u2014"  # —

    # Timestamp ke WIB
    time_str = _to_wib_str(sig.close_time)

    # Entry zone
    if sig.entry_low is not None and sig.entry_high is not None:
        entry_str = f"{sig.entry_low:.2f} \u2013 {sig.entry_high:.2f}"  # –
    else:
        entry_str = f"{sig.entry:.2f}"

    # Harga
    sl_str  = f"{sig.sl:.2f}"  if sig.sl  is not None else "-"
    tp1_str = f"{sig.tp:.2f}"  if sig.tp  is not None else "-"
    tp2_str = f"{sig.tp2:.2f}" if sig.tp2 is not None else "-"
    tp3_str = f"{sig.tp3:.2f}" if sig.tp3 is not None else "-"
    rr_str  = f"{sig.rr:.2f}R" if sig.rr  is not None else "-"

    sl_label = "ATR-based" if sig.sl_method == "dynamic_atr" else "Fixed pip"

    # RR per TP
    tp1_rr = sig.tp1_rr
    tp2_rr = sig.tp2_rr
    tp3_rr = sig.tp3_rr

    # Trigger notes
    trig_str = (
        f"{sig.trigger_score}/{sig.trigger_max} [{sig.trigger_notes}]"
        if sig.trigger_notes
        else f"{sig.trigger_score}/{sig.trigger_max}"
    )

    # Confluence notes
    conf_str = (
        f"{sig.confluence_score} [{sig.confluence_notes}]"
        if sig.confluence_notes
        else f"{sig.confluence_score}"
    )

    htf_str = sig.htf_bias.strip() if sig.htf_bias else "-"

    # ── Susun pesan ───────────────────────────────────────────────────
    lines = [
        f"{emoji} <b>SINYAL {sig.direction} {dash} {sig.symbol}</b>",
        f"TF: <b>{sig.tf}</b>  |  {time_str}",
    ]

    if signal_id:
        lines.append(f"ID: <code>{signal_id}</code>")

    lines += [
        "",
        f"\U0001f4cc Entry Zone : <code>{entry_str}</code>",            # 📌
        f"\U0001f6d1 Stop Loss  : <code>{sl_str}</code>  <i>({sl_label})</i>",  # 🛑
        f"\U0001f3af TP1        : <code>{tp1_str}</code>  <i>(RR {tp1_rr})</i>",  # 🎯
        f"\U0001f3af TP2        : <code>{tp2_str}</code>  <i>(RR {tp2_rr})</i>",
        f"\U0001f3af TP3        : <code>{tp3_str}</code>  <i>(RR {tp3_rr})</i>",
        f"\U0001f4ca RR         : <code>{rr_str}</code>",               # 📊
        "",
        "\u2500\u2500 Analisis Teknikal \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",  # ──
        f"\U0001f4c8 HTF Bias   : <code>{htf_str}</code>",              # 📈
        f"\U0001f9e9 Trigger    : <code>{trig_str}</code>",             # 🧩
        f"\U0001f48e Confluence : <code>{conf_str}</code>",             # 💎
    ]

    if sig.pattern_names:
        lines.append(f"\U0001f56f Pattern    : <code>{sig.pattern_names}</code>")   # 🕯
    if sig.fib_detail:
        lines.append(f"\U0001f4d0 Fibonacci  : <code>{sig.fib_detail}</code>")      # 📐
    if sig.snr_detail:
        lines.append(f"\U0001f532 SnR        : <code>{sig.snr_detail}</code>")      # 🔲
    if sig.snd_detail:
        lines.append(f"\U0001f4e6 Zone       : <code>{sig.snd_detail}</code>")      # 📦
    if sig.divergence_detail:
        lines.append(f"\U0001f500 Divergence : <code>{sig.divergence_detail}</code>")  # 🔀
    if sig.session_name:
        lines.append(f"\U0001f550 Sesi       : <code>{sig.session_name}</code>")    # 🕐
    if sig.atr_value and sig.atr_value > 0:
        lines.append(f"\U0001f4c9 ATR        : <code>{sig.atr_value:.4f}</code>")   # 📉

    lines += [
        "",
        "\u26a0\ufe0f <i>Rekomendasi manual \u2014 bukan auto-trade.</i>",  # ⚠️
    ]

    return "\n".join(lines)


def format_startup(
    login:            int,
    server:           str,
    symbols:          list[str],
    timeframes:       list[str],
    settings_summary: str,
) -> str:
    """Format pesan startup bot untuk Telegram."""
    return (
        "\U0001f680 <b>BOT TRADING ONLINE</b>\n\n"   # 🚀
        f"Account  : <code>{login}</code>\n"
        f"Server   : <code>{server}</code>\n"
        f"Symbols  : {', '.join(symbols)}\n"
        f"TFs      : {', '.join(timeframes)}\n\n"
        f"{settings_summary}"
    )
