"""templates.py — Format pesan sinyal untuk Telegram (HTML mode)."""

from src.models.signal import Signal
from src.utils.time_utils import iso_to_wib_str


def format_signal(sig: Signal, signal_id: str = "") -> str:
    """Format sinyal / setup plan menjadi pesan HTML untuk Telegram."""
    is_setup   = getattr(sig, "is_setup_plan", False)
    is_counter = getattr(sig, "signal_mode",   "trend") == "counter_trend"
    trade_mode = getattr(sig, "trade_mode",    "intraday")
    exec_tf    = getattr(sig, "exec_tf",       "")

    if is_setup:
        emoji      = "📋"
        type_label = "SETUP PLAN"
        direction  = sig.direction
        mode_emoji = "⚡" if trade_mode == "scalping" else "📅"
        mode_text  = trade_mode.upper()
    elif is_counter:
        emoji      = "🔵" if sig.direction == "BUY" else "🟠"
        type_label = "COUNTER TREND"
        direction  = sig.direction
        mode_emoji = "⚡" if trade_mode == "scalping" else "📅"
        mode_text  = trade_mode.upper()
    else:
        emoji      = "🟢" if sig.direction == "BUY" else "🔴"
        type_label = "LIVE SIGNAL"
        direction  = sig.direction
        mode_emoji = "⚡" if trade_mode == "scalping" else "📅"
        mode_text  = trade_mode.upper()

    if sig.entry_low is not None and sig.entry_high is not None:
        entry_str   = f"{sig.entry_low:.2f} – {sig.entry_high:.2f}"
        entry_label = "Entry Zone"
    else:
        entry_str   = f"{sig.entry:.2f}"
        entry_label = "Entry Price"

    sl_str  = f"{sig.sl:.2f}"  if sig.sl  else "—"
    tp1_str = f"{sig.tp:.2f}"  if sig.tp  else "—"
    tp2_str = f"{sig.tp2:.2f}" if sig.tp2 else "—"
    tp3_str = f"{sig.tp3:.2f}" if sig.tp3 else "—"

    lines = [
        f"{emoji} <b>{type_label}</b> — {direction} {mode_emoji} {mode_text}",
        f"<b>{sig.symbol}</b> | {sig.tf} | {iso_to_wib_str(sig.close_time)}",
    ]
    if signal_id:
        lines.append(f"<code>{signal_id}</code>")
    lines.append("")

    lines += [
        f"📌 <b>{entry_label}</b>",
        f"   <code>{entry_str}</code>",
        "",
        f"🛑 <b>Stop Loss</b> : <code>{sl_str}</code>",
        f"🎯 <b>Take Profit</b>",
        f"   TP1 : <code>{tp1_str}</code>  (RR {sig.tp1_rr})",
        f"   TP2 : <code>{tp2_str}</code>  (RR {sig.tp2_rr})",
        f"   TP3 : <code>{tp3_str}</code>  (RR {sig.tp3_rr})",
    ]
    if sig.rr:
        lines.append(f"📊 <b>Risk/Reward</b> : <code>{sig.rr:.2f}R</code>")
    lines.append("")

    lines.append("━━━ 📈 Analisis Teknikal ━━━")
    if sig.htf_bias and sig.htf_bias.strip():
        lines.append(f"📍 HTF Bias : <code>{sig.htf_bias.strip()}</code>")
    if sig.trigger_score > 0:
        lines.append(f"⚡ Trigger : <b>{sig.trigger_score}/{sig.trigger_max}</b>")
        if sig.trigger_notes:
            notes = sig.trigger_notes[:60] + "..." if len(sig.trigger_notes) > 60 else sig.trigger_notes
            lines.append(f"   <code>{notes}</code>")
    if sig.confluence_score >= 0:
        lines.append(f"💎 Confluence : <b>{sig.confluence_score}/{sig.confluence_max}</b>")

    details = []
    if sig.pattern_names:
        details.append(f"🕯 Pattern: {sig.pattern_names}")
    if sig.fib_detail:
        details.append(f"📐 Fibonacci: {sig.fib_detail}")
    if sig.snr_detail and "BLOCKED" not in sig.snr_detail:
        details.append(f"🔲 S/R: {sig.snr_detail}")
    if sig.snd_detail:
        details.append(f"📦 S&D Zone: {sig.snd_detail}")
    if sig.divergence_detail:
        details.append(f"🔄 Divergence: {sig.divergence_detail}")
    if details:
        lines.append("")
        for d in details:
            lines.append(f"   {d}")

    if sig.snr_detail and "BLOCKED" in sig.snr_detail:
        lines.append("")
        lines.append(f"⚠️ <b>Perhatian:</b> {sig.snr_detail}")

    info_line = []
    if sig.session_name:
        info_line.append(f"🕐 {sig.session_name}")
    if sig.atr_value and sig.atr_value > 0:
        info_line.append(f"📉 ATR {sig.atr_value:.2f}")
    if info_line:
        lines.append("")
        lines.append(" | ".join(info_line))

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if is_setup:
        lines.append("📋 <b>SETUP PLAN</b>")
        lines.append("<i>Tunggu harga masuk zona entry, kemudian konfirmasi dengan candle bullish/bearish yang kuat sebelum eksekusi.</i>")
        if exec_tf:
            lines.append(f"<i>Eksekusi optimal di timeframe <b>{exec_tf}</b></i>")
    elif is_counter:
        lines.append("⚠️ <b>COUNTER TREND</b>")
        lines.append("<i>Sinyal melawan bias HTF. Risk management ketat — cut loss jika break struktur.</i>")
    else:
        lines.append("✅ <b>LIVE SIGNAL</b>")
        lines.append("<i>Harga sudah di zona entry. Eksekusi setelah konfirmasi candle.</i>")

    lines.append("")
    lines.append("⚠️ <i>Rekomendasi manual — bukan auto-trade.</i>")

    return "\n".join(lines)
