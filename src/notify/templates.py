"""templates.py — Format pesan sinyal untuk Telegram (HTML mode)."""

from src.models.signal import Signal
from src.utils.time_utils import iso_to_wib_str


def format_signal(sig: Signal, signal_id: str = "") -> str:
    """Format sinyal / setup plan menjadi pesan HTML untuk Telegram."""
    is_setup   = getattr(sig, "is_setup_plan", False)
    is_counter = getattr(sig, "signal_mode",   "trend") == "counter_trend"
    trade_mode = getattr(sig, "trade_mode",    "intraday")
    exec_tf    = getattr(sig, "exec_tf",       "")
    dash = "\u2014"

    # Header
    if is_setup:
        emoji      = "\U0001f4cb"
        mode_label = f"SETUP {'BUY' if sig.direction == 'BUY' else 'SELL'}"
        mode_note  = (
            f"\U0001f4cc <i>Setup Plan {trade_mode.upper()} {dash} "
            f"Antisipasi entry di <b>{exec_tf}</b>. "
            f"Tunggu konfirmasi candle sebelum eksekusi.</i>"
        )
    elif is_counter:
        emoji      = "\U0001f535" if sig.direction == "BUY" else "\U0001f7e0"
        mode_label = "COUNTER BUY" if sig.direction == "BUY" else "COUNTER SELL"
        mode_note  = f"\u26a0\ufe0f <i>Counter Trend {dash} melawan bias HTF. Risiko lebih tinggi.</i>"
    else:
        emoji      = "\U0001f7e2" if sig.direction == "BUY" else "\U0001f534"
        mode_label = sig.direction
        mode_note  = None

    trade_label = " \u26a1 SCALPING" if trade_mode == "scalping" else " \U0001f4c5 INTRADAY"

    # Level harga
    if sig.entry_low is not None and sig.entry_high is not None:
        entry_str = f"{sig.entry_low:.2f} \u2013 {sig.entry_high:.2f}"
    else:
        entry_str = f"{sig.entry:.2f}"

    sl_str  = f"{sig.sl:.2f}"  if sig.sl  is not None else "-"
    tp1_str = f"{sig.tp:.2f}"  if sig.tp  is not None else "-"
    tp2_str = f"{sig.tp2:.2f}" if sig.tp2 is not None else "-"
    tp3_str = f"{sig.tp3:.2f}" if sig.tp3 is not None else "-"
    rr_str  = f"{sig.rr:.2f}R" if sig.rr  is not None else "-"
    sl_label = "ATR-based" if sig.sl_method == "dynamic_atr" else "Fixed pip"

    # Trigger / Confluence notes
    if is_setup:
        trig_str = f"[{sig.trigger_notes}]" if sig.trigger_notes else "SETUP"
    else:
        trig_str = (
            f"{sig.trigger_score}/{sig.trigger_max} [{sig.trigger_notes}]"
            if sig.trigger_notes else f"{sig.trigger_score}/{sig.trigger_max}"
        )
    conf_str = (
        f"{sig.confluence_score} [{sig.confluence_notes}]"
        if sig.confluence_notes else f"{sig.confluence_score}"
    )

    # Susun pesan
    lines = [
        f"{emoji} <b>{mode_label}{trade_label} {dash} {sig.symbol}</b>",
        f"TF: <b>{sig.tf}</b>  |  {iso_to_wib_str(sig.close_time)}",
    ]
    if signal_id:
        lines.append(f"ID: <code>{signal_id}</code>")
    if is_setup and exec_tf:
        lines.append(f"\U0001f3af Eksekusi di : <b>{exec_tf}</b>")

    lines += [
        "",
        f"\U0001f4cc Entry Zone : <code>{entry_str}</code>",
        f"\U0001f6d1 Stop Loss  : <code>{sl_str}</code>  <i>({sl_label})</i>",
        f"\U0001f3af TP1        : <code>{tp1_str}</code>  <i>(RR {sig.tp1_rr})</i>",
        f"\U0001f3af TP2        : <code>{tp2_str}</code>  <i>(RR {sig.tp2_rr})</i>",
        f"\U0001f3af TP3        : <code>{tp3_str}</code>  <i>(RR {sig.tp3_rr})</i>",
        f"\U0001f4ca RR         : <code>{rr_str}</code>",
    ]

    # Jika setup plan, tampilkan dasar penentuan zona entry
    # trigger_notes menyimpan format "SETUP_PLAN via ... | Fibonacci fib_X.XXX@..."
    if is_setup and sig.trigger_notes:
        tn = sig.trigger_notes
        if "Fibonacci" in tn:
            # Ambil bagian setelah "Fibonacci" dari trigger_notes
            fib_part = tn.split("Fibonacci")[-1].strip().split("|")[0].strip()
            lines.append(f"\U0001f4d0 Zona basis : <b>Fibonacci {fib_part}</b>")
        elif "EMA" in tn:
            ema_part = tn.split("|")[-1].strip()
            lines.append(f"\U0001f4d0 Zona basis : <i>{ema_part}</i>")

    lines += [
        "",
        "\u2500\u2500 Analisis Teknikal \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\U0001f4c8 HTF Bias   : <code>{sig.htf_bias.strip() or '-'}</code>",
        f"\U0001f9e9 Trigger    : <code>{trig_str}</code>",
        f"\U0001f48e Confluence : <code>{conf_str}</code>",
    ]

    if sig.pattern_names:
        lines.append(f"\U0001f56f Pattern    : <code>{sig.pattern_names}</code>")
    if sig.fib_detail:
        lines.append(f"\U0001f4d0 Fibonacci  : <code>{sig.fib_detail}</code>")
    if sig.snr_detail:
        lines.append(f"\U0001f532 SnR        : <code>{sig.snr_detail}</code>")
    if sig.snd_detail:
        lines.append(f"\U0001f4e6 Zone       : <code>{sig.snd_detail}</code>")
    if sig.divergence_detail:
        lines.append(f"\U0001f500 Divergence : <code>{sig.divergence_detail}</code>")
    if sig.session_name:
        lines.append(f"\U0001f550 Sesi       : <code>{sig.session_name}</code>")
    if sig.atr_value and sig.atr_value > 0:
        lines.append(f"\U0001f4c9 ATR        : <code>{sig.atr_value:.4f}</code>")

    lines += ["", "\u26a0\ufe0f <i>Rekomendasi manual \u2014 bukan auto-trade.</i>"]
    if mode_note:
        lines.append(mode_note)

    return "\n".join(lines)
