"""templates.py — Format pesan sinyal untuk Telegram (HTML mode)."""
import re

from src.models.signal import Signal
from src.utils.time_utils import iso_to_wib_str


_MODE_TAG: dict[str, str] = {
    "CONTINUATION": "",
    "REVERSAL":     " ⟨REVERSAL⟩",
    "BREAKOUT":     " ⟨BREAKOUT⟩",
    "BREAK_RETEST": " ⟨BREAK_RETEST⟩",
    "MOMENTUM":     " ⟨MOMENTUM⟩",
    "PULLBACK":     " ⟨PULLBACK⟩",
}

_MODE_EXPLAIN: dict[str, str] = {
    "CONTINUATION": "Searah trend (ikut bias HTF)",
    "PULLBACK":     "Pullback rebound dalam trend — setup sah, jalur masuk beda dari trigger normal",
    "REVERSAL":     "Lawan trend — butuh divergence sbg konfirmasi",
    "BREAKOUT":     "Breakout level kunci",
    "BREAK_RETEST": "Breakout lalu retest level — tunggu konfirmasi retest pasca-break, bukan kejar breakout",
    "MOMENTUM":     "Momentum kuat searah — tubuh candle meyakinkan, masuk setelah momentum terkonfirmasi",
}


def _rr_label(sig: Signal, tp: float | None) -> str:
    """RR aktual per TP: TP1=sig.rr, TP2=sig.rr_tp2_actual, selainnya dihitung dari harga."""
    if tp is None or tp <= 0 or sig.sl is None or sig.sl <= 0:
        return "—"
    entry = (sig.entry_high or sig.entry) if sig.direction == "BUY" else (sig.entry_low or sig.entry)
    if not entry:
        return "—"
    if tp == sig.tp and sig.rr is not None:
        return f"{sig.rr:.2f}R"
    if tp == sig.tp2 and sig.rr_tp2_actual > 0:
        return f"{sig.rr_tp2_actual:.2f}R"
    sl_dist = abs(sig.sl - entry)
    if sl_dist <= 0:
        return "—"
    return f"{abs(tp - entry) / sl_dist:.2f}R"


def _htf_fmt(bias_str: str) -> str:
    _arrow = {"BULL": "↑", "BEAR": "↓", "NEUTRAL": "→"}
    parts: list[str] = []
    recovery: str | None = None
    for item in bias_str.strip().split():
        if item.startswith("[MOM_RECOVERY:"):
            m = re.match(r"\[MOM_RECOVERY:(\w+)\((.*)\)\]", item)
            if m:
                dir_b   = m.group(1)
                detail  = m.group(2).split(",")
                recovery = f"→ Recovery:{_arrow.get(dir_b, dir_b)} {dir_b}"
                if detail:
                    recovery += f" ({','.join(detail)})"
            continue
        if item.startswith("["):
            continue   # skip token debug seperti [TF_FAIL:H4_diperlukan]
        if ":" in item:
            tf, b = item.split(":", 1)
            parts.append(f"{tf} {_arrow.get(b.upper(), b)}")
        else:
            parts.append(item)
    s = "  ".join(parts)
    if recovery:
        s = f"{s}  {recovery}" if s else recovery
    return s


def _entry_zone_lines(sig: Signal) -> list[str]:
    """Tampilkan zona entry dengan batas valid yang jelas."""
    has_zone = (
        sig.entry_low is not None
        and sig.entry_high is not None
        and abs(sig.entry_high - sig.entry_low) > 0.005
    )

    if has_zone:
        lo = sig.entry_low
        hi = sig.entry_high
        if sig.direction == "BUY":
            zone_str = f"{lo:.2f} – {hi:.2f}"
            warn = f"⚠️ <i>Skip jika harga sudah di bawah <code>{lo:.2f}</code></i>"
        else:
            zone_str = f"{lo:.2f} – {hi:.2f}"
            warn = f"⚠️ <i>Skip jika harga sudah di atas <code>{hi:.2f}</code></i>"

        return [
            f"📌 <b>Entry Zone</b>   <code>{zone_str}</code>",
            f"   {warn}",
        ]
    else:
        return [
            f"🚀 <b>Entry Now </b>   <code>{sig.entry:.2f}</code>",
        ]


def _pullback_summary(sig: Signal) -> str:
    """Ringkasan skor pullback (X/4) — pengganti 'Trigger X/6' utk mode PULLBACK."""
    m = re.search(r"PULLBACK\[([\w,\+\-]+)\]", sig.trigger_notes or "")
    if not m:
        return "↩️ Pullback"
    checks = m.group(1).split(",")
    ok = sum(1 for c in checks if c.endswith("+"))
    return f"↩️ Pullback {ok}/{len(checks)}"


def _pullback_checks(sig: Signal) -> list[str]:
    """Checklist konfirmasi pullback (rejection/rsi/momentum/div) utk template."""
    m = re.search(r"PULLBACK\[([\w,\+\-]+)\]", sig.trigger_notes or "")
    if not m:
        return []
    checks = m.group(1).split(",")
    parts = [f"{c[:-1]}{'✓' if c.endswith('+') else '✗'}" for c in checks]
    return ["↩️ <b>Pullback Setup</b>  " + "  ".join(parts)]


def _technical_section(sig: Signal) -> list[str]:
    L: list[str] = []
    L.append("─────────────────────")
    L.append("📈 <b>Analisis Teknikal</b>")
    L.append("")

    if sig.htf_bias and sig.htf_bias.strip():
        L.append("🗺 <b>HTF Bias</b>")
        L.append(f"   <code>{_htf_fmt(sig.htf_bias)}</code>")
        if sig.htf_bias_all and sig.htf_bias_all.strip():
            L.append(f"   <code>Stack: {_htf_stack_compact(sig.htf_bias_all)}</code>")
        L.append("")

    # Confluence — rinci per komponen
    confluences: list[str] = []

    if sig.pattern_names:
        confluences.append(f"✓ <b>Pattern</b>: {sig.pattern_names}")

    if sig.fib_detail:
        fib_clean = sig.fib_detail.split('|')[0]
        fib_clean = fib_clean.replace('FIB_STRONG', 'Strong').replace('FIB_NEAR', 'Near').replace('FIB_GOLD', 'Golden')
        confluences.append(f"✓ <b>Fibonacci</b>: {fib_clean}")

    # SNR — tampilkan tipe level, harga, kekuatan (touch count)
    if sig.snr_detail:
        if "SNR_OK" in sig.snr_detail or "SNR_WEAK" in sig.snr_detail:
            quality = "✓" if "SNR_OK" in sig.snr_detail else "~"
            level_match  = re.search(r'(SUP|RES)=([0-9.]+)', sig.snr_detail)
            touch_match  = re.search(r't=(\d+)', sig.snr_detail)
            fresh_match  = re.search(r'(FRESH|AGED)', sig.snr_detail)
            tf_match     = re.search(r'tf=([\w+]+)', sig.snr_detail)
            level_type   = "Support" if level_match and level_match.group(1) == "SUP" else "Resistance"
            level_price  = level_match.group(2) if level_match else ""
            touches      = touch_match.group(1) if touch_match else ""
            freshness    = fresh_match.group(1).lower() if fresh_match else ""
            tf_label     = f" ({tf_match.group(1)})" if tf_match else ""
            detail_parts = []
            if level_price: detail_parts.append(f"@ {level_price}")
            if touches:     detail_parts.append(f"{touches}-touch")
            if freshness:   detail_parts.append(freshness)
            detail_str   = " | ".join(detail_parts)
            confluences.append(f"{quality} <b>S/R {level_type}</b>{tf_label}: {detail_str}")
        elif "SNR_BLOCKED" in sig.snr_detail:
            confluences.append("✗ <b>S/R</b>: blocked (jalan terhalang)")

    # SND — Supply/Demand zone
    if sig.snd_detail:
        zone_type = "Demand" if sig.direction == "BUY" else "Supply"
        price_match = re.search(r'([0-9.]+)-([0-9.]+)', sig.snd_detail)
        if price_match:
            confluences.append(f"✓ <b>S&D {zone_type}</b>: {price_match.group(1)}–{price_match.group(2)}")
        else:
            confluences.append(f"✓ <b>S&D {zone_type}</b> zone")

    if sig.divergence_detail:
        confluences.append(f"✓ <b>Divergence</b>: {sig.divergence_detail}")

    # Liquidity Sweep — entry-timing scalping
    if sig.sweep_detail:
        confluences.append(f"✓ <b>Liquidity Sweep</b>: {sig.sweep_detail}")

    # FVG — entry-timing scalping
    if sig.fvg_detail:
        fvg_disp = sig.fvg_detail
        if fvg_disp.startswith("FVG_OK("):
            fvg_disp = fvg_disp[len("FVG_OK("):-1]
        confluences.append(f"✓ <b>FVG</b>: {fvg_disp}")

    # Trigger komponen (EMA, RSI, MACD, Candle) — ringkas dari trigger_notes
    if sig.trigger_notes:
        trigger_parts: list[str] = []
        notes = sig.trigger_notes.split()
        comp_map = {
            "EMA200+": "EMA200✓", "EMA50+": "EMA50✓", "ALIGN+": "Align✓",
            "MACD+":   "MACD✓",   "CDL+":   "Candle✓",
        }
        for token in notes:
            base = token.split("(")[0]
            if base in comp_map:
                trigger_parts.append(comp_map[base])
            elif base.startswith("RSI+"):
                rsi_val = re.search(r'\((\d+)\)', token)
                trigger_parts.append(f"RSI✓({rsi_val.group(1)})" if rsi_val else "RSI✓")
        if trigger_parts:
            confluences.append(f"📊 <b>Trigger</b>: {' · '.join(trigger_parts)}")

    if confluences:
        L.append("🔍 <b>Konfirmasi</b>")
        for c in confluences:
            L.append(f"   {c}")
        L.append("")

    # Session, ATR, Trigger strength
    info: list[str] = []
    if sig.session_name:
        sess_emoji = {"asian": "🌅", "london": "🇬🇧", "new york": "🗽",
                      "overlap l+ny": "🌐", "overlap": "🌐"}.get(
                      sig.session_name.lower(), "🕐")
        info.append(f"{sess_emoji} {sig.session_name}")
    if sig.atr_value and sig.atr_value > 0:
        info.append(f"ATR {sig.atr_value:.2f}")
    if sig.trigger_notes and sig.trigger_notes.startswith("PULLBACK["):
        info.append(_pullback_summary(sig))
    elif sig.trigger_score and sig.trigger_max:
        info.append(f"⚡ Trigger {sig.trigger_score}/{sig.trigger_max}")
    if sig.confluence_score is not None:
        info.append(f"Conf {sig.confluence_score}")
    if info:
        L.append("📊 " + " | ".join(info))

    if sig.trigger_notes and sig.trigger_notes.startswith("PULLBACK["):
        checks = _pullback_checks(sig)
        if checks:
            L.extend(checks)
            L.append("")

    return L


def _position_section(sig: Signal) -> list[str]:
    be    = sig.breakeven_sl
    trail = sig.trailing_sl_tp2
    if be is None and trail is None:
        return []

    tp1_str   = f"{sig.tp:.2f}"   if sig.tp   else "—"
    tp2_str   = f"{sig.tp2:.2f}"  if sig.tp2  else "—"
    be_str    = f"{be:.2f}"       if be       else "entry"
    trail_str = f"{trail:.2f}"    if trail    else tp1_str

    return [
        "",
        "─────────────────────",
        "💼 <b>Manajemen Posisi</b>",
        f"   TP1 ({tp1_str}) → tutup {sig.lot_split_tp1}%  |  SL → <code>{be_str}</code>",
        f"   TP2 ({tp2_str}) → tutup {sig.lot_split_tp2}%  |  SL → <code>{trail_str}</code>",
        f"   TP3 → biarkan {sig.lot_split_tp3}% berjalan",
    ]


def _htf_stack_compact(all_bias_str: str) -> str:
    """Stack bias lintas-TF — versi RINGKAS (display-only): tiap TF hanya verdict
    BULL/BEAR/NEUTRAL; tail detail teknikal (harga_antara_MA e50=... dst) dipangkas.
    Aditif — tak menyentuh skor/gate/threshold engine."""
    toks: list[str] = []
    for tok in all_bias_str.split():
        base = tok.split("(", 1)[0]
        if base.strip():
            toks.append(base)
    return _htf_fmt(" ".join(toks))


def _format_live(sig: Signal, signal_id: str, signal_mode: str) -> str:
    trade_mode = sig.trade_mode or "intraday"
    mode_tag   = _MODE_TAG.get(signal_mode, "")

    if signal_mode == "BREAKOUT":
        h_emoji = "⚡"
    elif signal_mode == "BREAK_RETEST":
        h_emoji = "🔄"
    elif signal_mode == "MOMENTUM":
        h_emoji = "🔥"
    elif signal_mode == "REVERSAL":
        h_emoji = "🔵" if sig.direction == "BUY" else "🟠"
    elif signal_mode == "PULLBACK":
        h_emoji = "↩️" if sig.direction == "BUY" else "↪️"
    else:
        h_emoji = "🚀" if sig.direction == "BUY" else "🔻"

    dir_emoji  = "📈" if sig.direction == "BUY" else "📉"
    mode_emoji = "⚡" if trade_mode == "scalping" else "📅"
    mode_text  = "SCALPING" if trade_mode == "scalping" else "SWING"

    sl_str  = f"{sig.sl:.2f}"  if sig.sl  else "—"
    tp1_str = f"{sig.tp:.2f}"  if sig.tp  else "—"
    tp2_str = f"{sig.tp2:.2f}" if sig.tp2 else "—"
    tp3_str = f"{sig.tp3:.2f}" if sig.tp3 else "—"
    rr_str  = f"{sig.rr:.2f}R" if sig.rr  else "—"

    L: list[str] = []
    L.append(f"{h_emoji} <b>LIVE {sig.direction}</b>{mode_tag}  {dir_emoji}  {mode_emoji} <b>{mode_text}</b>")
    L.append(f"<b>{sig.symbol}</b> | <b>{sig.tf}</b> | {iso_to_wib_str(sig.close_time)}")

    if signal_mode in _MODE_EXPLAIN:
        L.append(f"ℹ️ <i>{_MODE_EXPLAIN[signal_mode]}</i>")

    if signal_id:
        L.append(f"🆔 <code>{signal_id}</code>")

    L.append("")
    L.append("─────────────────────")

    entry_lines = _entry_zone_lines(sig)
    for line in entry_lines:
        if "Skip" in line:
            L.append(f"<b>{line}</b>")
        else:
            L.append(line)
    
    L.append(f"🛑 <b>Stop Loss </b>   <code>{sl_str}</code>")
    L.append("")
    L.append("🎯 <b>Take Profit</b>")
    L.append(f"   TP1 : <code>{tp1_str}</code>  (RR {_rr_label(sig, sig.tp)})")
    L.append(f"   TP2 : <code>{tp2_str}</code>  (RR {_rr_label(sig, sig.tp2)})")
    L.append(f"   TP3 : <code>{tp3_str}</code>  (RR {_rr_label(sig, sig.tp3)})")
    L.append(f"📊 <b>Risk/Reward</b>  <code>{rr_str}</code>")
    L.extend(_position_section(sig))
    L.extend(_technical_section(sig))
    L.append("")
    L.append("─────────────────────")
    
    # Footer (tanpa duplikasi direction)
    if sig.reason and sig.reason.strip():
        L.append(f"💡 <i>{sig.reason}</i>")
        L.append("")
    L.append("<i>⚠️ Rekomendasi manual — bukan auto-trade.</i>")
    
    return "\n".join(L)


def _format_setup(sig: Signal, signal_id: str, signal_mode: str) -> str:
    trade_mode = sig.trade_mode or "intraday"
    exec_tf    = sig.exec_tf or sig.tf
    mode_tag   = _MODE_TAG.get(signal_mode, "")

    dir_emoji  = "📈" if sig.direction == "BUY" else "📉"
    mode_emoji = "⚡" if trade_mode == "scalping" else "📅"
    mode_text  = "SCALPING" if trade_mode == "scalping" else "INTRADAY"

    if sig.entry_low is not None and sig.entry_high is not None:
        entry_str = f"{sig.entry_low:.2f} – {sig.entry_high:.2f}"
    else:
        entry_str = f"{sig.entry:.2f}"

    sl_str  = f"{sig.sl:.2f}"  if sig.sl  else "—"
    tp1_str = f"{sig.tp:.2f}"  if sig.tp  else "—"
    tp2_str = f"{sig.tp2:.2f}" if sig.tp2 else "—"
    tp3_str = f"{sig.tp3:.2f}" if sig.tp3 else "—"
    rr_str  = f"{sig.rr:.2f}R" if sig.rr  else "—"

    direction_word = "bullish" if sig.direction == "BUY" else "bearish"
    limit_label    = "di bawah" if sig.direction == "BUY" else "di atas"
    limit_price    = f"{sig.entry_low:.2f}" if sig.direction == "BUY" else f"{sig.entry_high:.2f}"

    L: list[str] = []
    L.append(f"📋 <b>SETUP {sig.direction}</b>{mode_tag}  {dir_emoji}  {mode_emoji} {mode_text}")
    L.append(f"<b>{sig.symbol}</b> | {sig.tf} | {iso_to_wib_str(sig.close_time)}")

    if signal_mode in _MODE_EXPLAIN:
        L.append(f"ℹ️ <i>{_MODE_EXPLAIN[signal_mode]}</i>")

    if signal_id:
        L.append(f"<code>{signal_id}</code>")
    L.append("")
    L.append("─────────────────────")
    L.append(f"📌 <b>Entry Zone</b>   <code>{entry_str}</code>")
    L.append(f"   ⚠️ <i>Skip jika harga sudah {limit_label} <code>{limit_price}</code></i>")
    L.append(f"🛑 <b>Stop Loss </b>   <code>{sl_str}</code>")
    L.append("")
    L.append("🎯 <b>Take Profit</b>")
    L.append(f"   TP1 : <code>{tp1_str}</code>  (RR {_rr_label(sig, sig.tp)})")
    L.append(f"   TP2 : <code>{tp2_str}</code>  (RR {_rr_label(sig, sig.tp2)})")
    L.append(f"   TP3 : <code>{tp3_str}</code>  (RR {_rr_label(sig, sig.tp3)})")
    L.append(f"📊 <b>Risk/Reward</b>  <code>{rr_str}</code>")
    L.extend(_position_section(sig))
    L.extend(_technical_section(sig))
    L.append("")
    L.append("─────────────────────")
    L.append("📋 <b>Cara Entry</b>")
    L.append(f"1️⃣ Tunggu harga masuk zona  <code>{entry_str}</code>")
    L.append(f"2️⃣ Konfirmasi candle {direction_word} di {exec_tf}")
    L.append(f"3️⃣ Entry, SL di  <code>{sl_str}</code>")
    if sig.reason and sig.reason.strip():
        L.append(f"💡 <i>{sig.reason}</i>")
    L.append("")
    L.append("<i>⚠️ Rekomendasi manual — bukan auto-trade.</i>")
    return "\n".join(L)


def format_signal(sig: Signal, signal_id: str = "") -> str:
    signal_mode = sig.signal_mode or "CONTINUATION"
    if sig.is_setup_plan or sig.signal_type == "SETUP":
        return _format_setup(sig, signal_id, signal_mode)
    return _format_live(sig, signal_id, signal_mode)
