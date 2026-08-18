"""main.py — Entry point bot trading DSS Forex.

Jalankan: python -m src.main
"""

import time
from datetime import datetime

import MetaTrader5 as mt5
import pytz
from loguru import logger

from src.config.settings import load_settings
from src.engine.evaluator import evaluate_any_tf_mta
from src.engine.setup_plan import scan_setup_plan
from src.infra.report.generator import generate_report
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.infra.logger import setup_logger
from src.infra.scheduler import CandleCloseWatcher
from src.infra.signal_logger import SignalLogger
from src.infra.signal_tracker import SignalTracker
from src.mt5.connector import connect, shutdown
from src.mt5.market_data import ensure_symbol, fetch_ohlc
from src.notify.telegram import send_message
from src.notify.templates import format_signal


# ── Label komponen trigger (internal → tampilan manusia) ─────────────────────
_COMP_LABEL: dict[str, str] = {
    "EMA200+":   "EMA200✓", "EMA200-":   "EMA200✗", "EMA200_NA": "EMA200?",
    "EMA50+":    "EMA50✓",  "EMA50-":    "EMA50✗",
    "ALIGN+":    "Align✓",  "ALIGN-":    "Align✗",
    "RSI+":      "RSI✓",    "RSI-":      "RSI✗",    "RSI+MOM":   "RSI+mom✓",
    "MACD+":     "MACD✓",   "MACD-":     "MACD✗",
    "CDL+":      "Candle✓", "CDL-":      "Candle✗",
    "Pattern++": "Pattern✓✓","Pattern+": "Pattern✓","Pattern-":  "Pattern✗",
    "Div+":      "Div✓",    "Div-":      "Div✗",
    "Fib+":      "Fib✓",    "Fib-":      "Fib✗",    "Fib_SKIP":  "Fib?",
    "SnR+":      "SnR✓",    "SnR-":      "SnR✗",    "SnR_SKIP":  "SnR?",
    "SnD+":      "SnD✓",    "SnD-":      "SnD✗",    "SnD_SKIP":  "SnD?",
}

# Kondisi pasar → teks ringkas
_MKT_LABEL: dict[str, str] = {
    "volatile":   "pasar volatil (threshold diturunkan -1)",
    "sideways":   "pasar sideways (threshold dinaikkan +1)",
    "news_spike": "news spike",
    "normal":     "",
}


def _fmt_comp(raw_comp: str) -> str:
    """
    Konversi string komponen mentah jadi teks ringkas.
    'EMA200+ EMA50- RSI-(58) MACD+ CDL+' → 'EMA200✓ EMA50✗ RSI✗(58) MACD✓ Candle✓'
    """
    parts = raw_comp.split()
    out = []
    for p in parts:
        # handle token seperti RSI-(58) atau RSI+(62)
        base = p.split("(")[0]
        rest = ("(" + p.split("(")[1]) if "(" in p else ""
        out.append(_COMP_LABEL.get(base, base) + rest)
    return " ".join(out)


def _extract_between(s: str, open_: str, close_: str) -> str:
    """Ambil teks antara open_ dan close_. Return '' jika tidak ada."""
    try:
        return s[s.index(open_) + len(open_): s.rindex(close_)]
    except (ValueError, IndexError):
        return ""


def _explain_reject(raw: str) -> str:
    """
    Terjemahkan reject reason terstruktur dari evaluator.py ke pesan manusia.

    Format input yang didukung (semuanya dari evaluator.py):
      Gate 1: NOT_ENOUGH_BARS(N) | ATR_INVALID | ATR_TOO_LOW(val<min)
              NEWS_SPIKE_SKIP | OUT_OF_SESSION(sess) | COOLDOWN(N/M)
      Gate 2: BIAS_FAIL(detail) | BIAS_FAIL+CT_FAIL(detail)
      Gate 3: TRIGGER_FAIL:dir=X:score=N/M:comp=[...]:cond=X
              EMA200_WAJIB:dir=X:bias=X:comp=[...]:cond=X
              RSI_EXTREME:RSI_OVERBOUGHT/OVERSOLD(val):dir=X:cond=X
              CT_EMA200_FAIL:dir=X:comp=[...] | CT_NO_FIB(...) | CT_NO_DIV
      Gate 4: SLTP_NONE
      Gate 5: CONFLUENCE_FAIL:score=N/M:comp=[...]:cond=X
              INTRADAY_NO_FIB:comp=[...]
              RR_FAIL:rr=X/min=Y | CANDLE_CONFIRM_FAIL:dir=X

    Contoh output:
      Gate 3 ✗ – Trigger skor 2/4
        Komponen : EMA200✓ EMA50✗ Align✗ RSI✗(58) MACD✗ Candle✓
        Arah coba: BUY | Pasar: sideways (threshold dinaikkan +1)
    """
    if not raw or raw in ("INIT", "OK"):
        return raw

    # ── Normalisasi: ubah format KEY(val) → KEY dengan extractor terpisah ────
    # Beberapa reject reason dari Gate 1 menggunakan format KEY(val) bukan KEY:key=val
    # Tangani sebelum token parser dijalankan
    raw_upper = raw.upper()

    if raw_upper.startswith("NOT_ENOUGH_BARS"):
        val = _extract_between(raw, "(", ")")
        return f"Gate 1 ✗ – Data tidak cukup ({val} bar, butuh ≥220)"

    if raw_upper.startswith("ATR_INVALID"):
        return "Gate 1 ✗ – ATR tidak valid (data flat atau kosong)"

    if raw_upper.startswith("ATR_TOO_LOW"):
        val = _extract_between(raw, "(", ")")
        return f"Gate 1 ✗ – ATR terlalu kecil, pasar flat ({val})"

    if raw_upper.startswith("NEWS_SPIKE_SKIP"):
        return "Gate 1 ✗ – Lonjakan ATR ekstrem (kemungkinan news), sinyal dilewati"

    if raw_upper.startswith("COOLDOWN"):
        val = _extract_between(raw, "(", ")")
        return f"Gate 1 ✗ – Cooldown aktif ({val} sebelum sinyal berikutnya)"

    if raw_upper.startswith("OUT_OF_SESSION"):
        val = _extract_between(raw, "(", ")")
        return f"Gate 1 ✗ – Di luar sesi trading (saat ini: {val})"

    if raw_upper.startswith("SLTP_NONE"):
        return "Gate 4 ✗ – SL/TP tidak dapat dihitung (harga atau ATR tidak valid)"

    if raw_upper.startswith("CT_NO_DIV"):
        return "Gate 3 ✗ – Counter trend: tidak ada divergence RSI/MACD (wajib)"

    if raw_upper.startswith("CT_NO_FIB"):
        detail = _extract_between(raw, "(", ")")
        return f"Gate 3 ✗ – Counter trend: tidak ada level Fibonacci valid ({detail})"

    # BIAS_FAIL dan BIAS_FAIL+CT_FAIL menggunakan format KEY(detail)
    if raw_upper.startswith("BIAS_FAIL"):
        detail = _extract_between(raw, "(", ")")
        parts = []
        for item in detail.split():
            if ":" in item:
                tf_part, b = item.split(":", 1)
                b_label = {"BULL":"↑BULL","BEAR":"↓BEAR","NEUTRAL":"→netral","MISSING":"N/A"}.get(b.upper(), b)
                parts.append(f"{tf_part}:{b_label}")
            elif item:
                # handle token [TF_FAIL:H1_diperlukan]
                parts.append(item.replace("[", "").replace("]", ""))
        bias_str = " ".join(parts)
        if "CT_FAIL" in raw_upper:
            return f"Gate 2 ✗ – Bias netral & counter trend gagal\n        HTF  : {bias_str}"
        return f"Gate 2 ✗ – Bias HTF netral/tidak jelas\n        HTF  : {bias_str}"

    # RSI_EXTREME: format RSI_EXTREME:RSI_OVERBOUGHT(val):dir=X:cond=X
    if raw_upper.startswith("RSI_EXTREME"):
        segs = raw.split(":", 2)
        inner = segs[1] if len(segs) > 1 else ""
        val   = _extract_between(inner, "(", ")")
        kind  = "overbought (BUY terlalu berisiko)" if "OVERBOUGHT" in inner.upper() \
                else "oversold (SELL terlalu berisiko)"
        # parse dir dari sisa
        dir_ = "?"
        for seg in segs[2:] if len(segs) > 2 else []:
            for part in seg.split(":"):
                if part.startswith("dir="):
                    dir_ = part[4:]
        return f"Gate 3 ✗ – RSI {kind} (RSI={val}) → arah {dir_} ditolak"
    def _tokens(s: str) -> dict[str, str]:
        result: dict[str, str] = {}
        i = 0
        parts = s.split(":")
        while i < len(parts):
            kv = parts[i]
            if "=" not in kv:
                result["_type"] = kv
                i += 1
                continue
            k, v = kv.split("=", 1)
            # Jika value mulai dengan '[', gabungkan sampai ']'
            if v.startswith("[") and "]" not in v:
                while i + 1 < len(parts) and "]" not in v:
                    i += 1
                    v += ":" + parts[i]
            result[k] = v
            i += 1
        return result

    tok = _tokens(raw)
    rtype = tok.get("_type", raw.split(":")[0])

    # ── Gate 1 (format :key=val — sudah ditangani di atas via prefix) ──────────

    # ── Gate 2 (sudah ditangani di atas via prefix) ───────────────────────────

    # ── Gate 3 ────────────────────────────────────────────────────────────────
    if rtype == "TRIGGER_FAIL":
        score  = tok.get("score", "?")
        comp   = _fmt_comp(_extract_between(raw, "[", "]"))
        dir_   = tok.get("dir", "?")
        cond   = _MKT_LABEL.get(tok.get("cond", ""), "")
        lines  = [f"Gate 3 ✗ – Trigger skor kurang ({score})"]
        lines.append(f"        Arah     : {dir_}")
        lines.append(f"        Komponen : {comp}")
        if cond:
            lines.append(f"        Pasar    : {cond}")
        return "\n".join(lines)

    if rtype == "EMA200_WAJIB":
        dir_  = tok.get("dir", "?")
        bias  = tok.get("bias", "?")
        comp  = _fmt_comp(_extract_between(raw, "[", "]"))
        cond  = _MKT_LABEL.get(tok.get("cond", ""), "")
        lines = [f"Gate 3 ✗ – Harga di sisi salah EMA200 (wajib lulus)"]
        lines.append(f"        Arah coba: {dir_} (bias HTF={bias})")
        lines.append(f"        Komponen : {comp}")
        if cond:
            lines.append(f"        Pasar    : {cond}")
        return "\n".join(lines)

    if rtype == "RSI_EXTREME":
        # RSI_EXTREME:RSI_OVERBOUGHT(65):dir=BUY:cond=normal
        inner = raw[len("RSI_EXTREME:"):].split(":")[0]
        kind  = "overbought (BUY terlalu berisiko)" if "OVERBOUGHT" in inner else "oversold (SELL terlalu berisiko)"
        val   = _extract_between(inner, "(", ")")
        dir_  = tok.get("dir", "?")
        return f"Gate 3 ✗ – RSI {kind} (RSI={val}) → arah {dir_} ditolak"

    if rtype == "CT_EMA200_FAIL":
        dir_  = tok.get("dir", "?")
        comp  = _fmt_comp(_extract_between(raw, "[", "]"))
        return (
            f"Gate 3 ✗ – Counter trend: harga di sisi salah EMA200\n"
            f"        Arah coba: {dir_} | Komponen: {comp}"
        )

    if rtype == "CONFLUENCE_FAIL":
        score = tok.get("score", "?")
        comp  = _fmt_comp(_extract_between(raw, "[", "]"))
        cond  = _MKT_LABEL.get(tok.get("cond", ""), "")
        lines = [f"Gate 5 ✗ – Confluence skor kurang ({score})"]
        lines.append(f"        Komponen : {comp}")
        if cond:
            lines.append(f"        Pasar    : {cond}")
        return "\n".join(lines)

    if rtype == "INTRADAY_NO_FIB":
        comp = _fmt_comp(_extract_between(raw, "[", "]"))
        return (
            f"Gate 5 ✗ – Intraday wajib Fibonacci, tidak ditemukan\n"
            f"        Komponen : {comp}"
        )

    if rtype == "RR_FAIL":
        # Format: RR_FAIL:rr=1.23/min=1.5
        # Karena '/' di dalam value, parse manual
        rr_part = ""
        min_part = ""
        for seg in raw.split(":"):
            if seg.startswith("rr="):
                val = seg[3:]
                if "/" in val:
                    rr_part, min_part = val.split("/", 1)
                    if min_part.startswith("min="):
                        min_part = min_part[4:]
                else:
                    rr_part = val
        return f"Gate 5 ✗ – Risk-Reward terlalu rendah (RR={rr_part or '?'}, butuh ≥{min_part or '?'})"

    if rtype == "CANDLE_CONFIRM_FAIL":
        dir_ = tok.get("dir", "?")
        return f"Gate 5 ✗ – Konfirmasi candle gagal (2 candle terakhir tidak mendukung arah {dir_})"

    if rtype == "SLTP_NONE":
        return "Gate 4 ✗ – SL/TP tidak dapat dihitung"

    # ── Fallback — tampilkan apa adanya dengan formatting minimal ────────────
    return raw


# ── Fungsi helper ─────────────────────────────────────────────────────────────

def _fetch_prepare(symbol: str, tf: str, bars: int):
    df = fetch_ohlc(symbol, tf, bars).sort_values("time").reset_index(drop=True)
    df = add_indicators(df)
    df = add_patterns(df)
    return df


def _get_mt5_price(symbol: str) -> tuple[float, float]:
    tick = mt5.symbol_info_tick(symbol)
    return (tick.bid, tick.ask) if tick else (0.0, 0.0)


def _refresh_report(sig_logger: SignalLogger) -> None:
    try:
        generate_report(sig_logger, silent=True)
    except PermissionError:
        logger.debug("Report skip: file sedang dibuka di Excel")
    except Exception as e:
        logger.debug(f"Report refresh gagal: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    setup_logger()
    logger.info("Logger aktif")

    s = load_settings()
    logger.info(
        f"BOT START | symbols={s.symbols} TFs={s.timeframes} "
        f"bars={s.bars} poll={s.poll_seconds}s"
    )
    logger.info(
        f"PARAMS | RR>={s.min_rr} trigger>={s.min_trigger_score}/6 "
        f"conf>={s.min_confluence_score} cooldown={s.cooldown_bars}bar "
        f"session_filter={s.session_filter}"
    )

    sig_logger = SignalLogger()
    logger.info("SignalLogger aktif → logs/signal_history.csv")

    def _notify(msg: str) -> None:
        try:
            send_message(s.telegram_token, s.telegram_chat_id, msg)
        except Exception as e:
            logger.warning(f"Tracker notify error: {e}")

    tracker = SignalTracker(
        sig_logger        = sig_logger,
        get_price_fn      = _get_mt5_price,
        send_notify_fn    = _notify,
        refresh_report_fn = lambda: _refresh_report(sig_logger),
    )
    watcher = CandleCloseWatcher()
    _setup_plan_sent: dict[tuple, object] = {}

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path)
        logger.info(f"MT5 terhubung | login={acc.login} server={acc.server}")
        tracker.start()

        send_message(
            s.telegram_token, s.telegram_chat_id,
            (
                "<b>BOT TRADING ONLINE</b>\n\n"
                f"Account  : <code>{acc.login}</code>\n"
                f"Server   : <code>{acc.server}</code>\n"
                f"Symbols  : {', '.join(s.symbols)}\n"
                f"TFs      : {', '.join(s.timeframes)}\n\n"
                f"RR>={s.min_rr} | Trigger>={s.min_trigger_score}/6 "
                f"| Conf>={s.min_confluence_score} "
                f"| Cooldown={s.cooldown_bars}bar "
                f"| Session={'ON' if s.session_filter else 'OFF'}\n"
                f"Tracker  : ON ({tracker.get_active_count()} sinyal pending)"
            ),
        )

        while True:
            for symbol in s.symbols:
                ensure_symbol(symbol)

                data_by_tf: dict = {}
                last_events: dict[str, object] = {}

                for trigger_tf in s.timeframes:
                    tf_u = trigger_tf.upper()
                    try:
                        df = _fetch_prepare(symbol, tf_u, s.bars)
                        data_by_tf[tf_u] = df
                    except Exception as e:
                        logger.error(f"[FETCH ERROR] {symbol} {tf_u}: {e}")
                        continue
                    event = watcher.check(symbol, tf_u, df)
                    if event is not None:
                        last_events[tf_u] = event

                if not last_events:
                    time.sleep(s.poll_seconds)
                    continue

                _live_signals: set[tuple] = set()
                # reject_by_gate: untuk ringkasan akhir per loop
                # key = gate prefix (BIAS_FAIL, TRIGGER_FAIL, dst.)
                # value = list TF yang kena gate itu
                _reject_by_gate: dict[str, list[str]] = {}
                signal_count = 0

                tfs_closing = ", ".join(last_events.keys())
                logger.info(f"┌─ {symbol} | Candle close: {tfs_closing}")

                for tf_u, event in last_events.items():
                    tf_u_norm = tf_u.upper()
                    enabled_u = [t.upper() for t in s.timeframes]
                    data_norm = {k.upper(): v for k, v in data_by_tf.items()}

                    _sl_cap = {
                        "M5":  s.max_sl_m5,  "M15": s.max_sl_m15,
                        "H1":  s.max_sl_h1,  "H4":  s.max_sl_h4,
                        "D1":  s.max_sl_d1,
                    }
                    _max_sl = _sl_cap.get(tf_u_norm, s.max_sl_points)

                    sig = evaluate_any_tf_mta(
                        data_by_tf           = data_norm,
                        symbol               = symbol,
                        trigger_tf           = tf_u_norm,
                        enabled_tfs          = enabled_u,
                        min_rr               = s.min_rr,
                        min_confirm_votes    = s.min_confirm_votes,
                        min_trigger_score    = s.min_trigger_score,
                        min_confluence_score = s.min_confluence_score,
                        cooldown_bars        = s.cooldown_bars,
                        atr_min_pct          = s.atr_min_pct,
                        sl_atr_mult          = s.sl_atr_mult,
                        tp1_rr               = s.tp1_rr,
                        tp2_rr               = s.tp2_rr,
                        tp3_rr               = s.tp3_rr,
                        max_sl_points        = _max_sl,
                        sl_pips              = s.sl_pips,
                        tp1_pips             = s.tp1_pips,
                        tp2_pips             = s.tp2_pips,
                        tp3_pips             = s.tp3_pips,
                        pip_size             = s.pip_size,
                        session_filter       = s.session_filter,
                        counter_trend_enabled  = s.counter_trend_enabled,
                        min_counter_confluence = s.min_counter_confluence,
                        counter_trend_min_rr   = s.counter_trend_min_rr,
                        counter_trend_tfs      = s.counter_trend_tfs,
                        scalping_min_trigger_score    = s.scalping_min_trigger_score,
                        scalping_min_confluence_score = s.scalping_min_confluence_score,
                        scalping_sl_atr_mult          = s.scalping_sl_atr_mult,
                        scalping_cooldown_bars        = s.scalping_cooldown_bars,
                        scalping_max_sl_points        = s.max_sl_m5,
                        scalping_tp1_rr               = s.scalping_tp1_rr,
                        scalping_tp2_rr               = s.scalping_tp2_rr,
                        scalping_tp3_rr               = s.scalping_tp3_rr,
                    )

                    if sig is None:
                        raw   = data_norm.get(tf_u_norm, {}).attrs.get("reject_reason", "UNKNOWN")
                        human = _explain_reject(raw)
                        # Log detail per TF ke file (DEBUG) — tidak bising di terminal
                        logger.debug(f"│  {tf_u_norm:<4} ✗  {human}")
                        # Untuk ringkasan terminal: ambil gate prefix saja
                        gate_key = raw.split(":")[0].split("(")[0]
                        _reject_by_gate.setdefault(gate_key, []).append(tf_u_norm)
                    else:
                        signal_count += 1
                        signal_id = sig_logger.log_signal(sig)
                        mode_str  = "COUNTER" if sig.signal_mode == "counter_trend" else sig.trade_mode.upper()

                        # Log sinyal keluar di INFO (selalu muncul di terminal)
                        logger.info(
                            f"│  {tf_u_norm:<4} ✅ SINYAL {sig.direction} [{mode_str}]"
                            f"  entry={sig.entry:.2f}  sl={sig.sl:.2f}  tp1={sig.tp:.2f}"
                            f"  RR={sig.rr:.2f}  T={sig.trigger_score}/6  C={sig.confluence_score}/7"
                        )
                        # Detail teknikal satu baris di bawah (INFO juga)
                        detail_parts = []
                        if sig.trigger_notes:
                            detail_parts.append(f"trigger=[{sig.trigger_notes[:50]}]")
                        if sig.fib_detail:
                            detail_parts.append(f"fib={sig.fib_detail}")
                        if sig.snr_detail:
                            detail_parts.append(f"snr={sig.snr_detail}")
                        if detail_parts:
                            logger.info(f"│       → {' | '.join(detail_parts)}")

                        _live_signals.add((symbol, sig.tf, sig.direction))
                        rec = sig_logger.get_by_id(signal_id)
                        if rec:
                            tracker.add_signal(rec)
                        _refresh_report(sig_logger)
                        send_message(
                            s.telegram_token, s.telegram_chat_id,
                            format_signal(sig, signal_id=signal_id),
                        )

                # ── Ringkasan penutup per loop ────────────────────────────────
                if signal_count > 0:
                    logger.info(f"└─ {symbol} | ✅ {signal_count} sinyal berhasil dikirim")
                elif _reject_by_gate:
                    # Kelompokkan per gate — tampilkan satu baris ringkas di terminal
                    # Detail sudah ada di file log (DEBUG)
                    gate_parts = []
                    for gate, tfs in _reject_by_gate.items():
                        gate_label = {
                            "NOT_ENOUGH_BARS":    "G1:data kurang",
                            "ATR_INVALID":        "G1:ATR invalid",
                            "ATR_TOO_LOW":        "G1:ATR flat",
                            "NEWS_SPIKE_SKIP":    "G1:news spike",
                            "COOLDOWN":           "G1:cooldown",
                            "OUT_OF_SESSION":     "G1:luar sesi",
                            "BIAS_FAIL":          "G2:bias netral",
                            "BIAS_FAIL+CT_FAIL":  "G2:bias+CT gagal",
                            "TRIGGER_FAIL":       "G3:trigger kurang",
                            "EMA200_WAJIB":       "G3:EMA200 salah sisi",
                            "RSI_EXTREME":        "G3:RSI ekstrem",
                            "CT_EMA200_FAIL":     "G3:CT-EMA200 gagal",
                            "CT_NO_FIB":          "G3:CT-Fib tidak ada",
                            "CT_NO_DIV":          "G3:CT-divergence tidak ada",
                            "SLTP_NONE":          "G4:SL/TP gagal",
                            "CONFLUENCE_FAIL":    "G5:confluence kurang",
                            "INTRADAY_NO_FIB":    "G5:intraday-Fib tidak ada",
                            "RR_FAIL":            "G5:RR terlalu rendah",
                            "CANDLE_CONFIRM_FAIL":"G5:candle confirm gagal",
                        }.get(gate, gate)
                        gate_parts.append(f"{gate_label}({','.join(tfs)})")
                    logger.info(f"└─ {symbol} | ✗ Tidak ada sinyal → " + "  ".join(gate_parts))
                    logger.info(f"   (detail lengkap di logs/app.log)")
                else:
                    logger.info(f"└─ {symbol} | Menunggu candle close berikutnya")

                # ── Setup plan scan ───────────────────────────────────────────
                if data_by_tf:
                    try:
                        _now = datetime.now(pytz.utc)
                        setup_count = 0
                        for _sp_scalping, _sp_anchor in [(True, "M15"), (False, "H1")]:
                            if _sp_anchor not in data_by_tf:
                                continue
                            _sp_max_sl = s.max_sl_m15 if _sp_scalping else s.max_sl_h1
                            setups = scan_setup_plan(
                                data_by_tf        = data_by_tf,
                                symbol            = symbol,
                                enabled_tfs       = s.timeframes,
                                min_confirm_votes = s.min_confirm_votes,
                                atr_min_pct       = s.atr_min_pct,
                                sl_atr_mult       = s.scalping_sl_atr_mult if _sp_scalping else s.sl_atr_mult,
                                tp1_rr            = s.scalping_tp1_rr  if _sp_scalping else s.tp1_rr,
                                tp2_rr            = s.scalping_tp2_rr  if _sp_scalping else s.tp2_rr,
                                tp3_rr            = s.scalping_tp3_rr  if _sp_scalping else s.tp3_rr,
                                max_sl_points     = _sp_max_sl,
                                sl_pips           = s.sl_pips,
                                tp1_pips          = s.tp1_pips,
                                tp2_pips          = s.tp2_pips,
                                tp3_pips          = s.tp3_pips,
                                pip_size          = s.pip_size,
                                session_filter    = s.session_filter,
                            )
                            for sp in setups:
                                sp_key     = (symbol, sp.tf, sp.direction)
                                sp_last_dt = _setup_plan_sent.get(sp_key)
                                if sp_key in _live_signals:
                                    logger.debug(
                                        f"[SETUP SKIP] {sp.symbol} {sp.tf} {sp.direction}"
                                        f" — live signal sudah ada"
                                    )
                                    continue
                                if sp_last_dt is not None and \
                                        (_now - sp_last_dt).total_seconds() / 60 < 15:
                                    continue
                                _setup_plan_sent[sp_key] = _now
                                logger.info(
                                    f"[SETUP] {sp.symbol} {sp.tf} {sp.direction}"
                                    f" ({sp.trade_mode})"
                                    f"  zona={sp.entry_low:.2f}-{sp.entry_high:.2f}"
                                    f"  sl={sp.sl:.2f}  RR={sp.rr:.2f}"
                                )
                                logger.info(f"        basis={sp.trigger_notes[:80]}")
                                sp_id  = sig_logger.log_signal(sp)
                                sp_rec = sig_logger.get_by_id(sp_id)
                                if sp_rec:
                                    tracker.add_signal(sp_rec)
                                send_message(
                                    s.telegram_token, s.telegram_chat_id,
                                    format_signal(sp, signal_id=sp_id),
                                )
                                _refresh_report(sig_logger)
                                setup_count += 1

                        if setup_count > 0:
                            logger.info(f"[SETUP] {symbol} | {setup_count} setup plan terkirim")
                    except Exception as e:
                        logger.debug(f"Setup plan scan error: {e}")

            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.info("Bot dihentikan oleh user (Ctrl+C).")
    except Exception:
        logger.exception("FATAL ERROR — bot berhenti tidak terduga")
    finally:
        tracker.stop()
        shutdown()
        logger.info("MT5 disconnected. Bot selesai.")


if __name__ == "__main__":
    main()
