"""
anytf_mta_engine.py
===================
Rule-Based Decision Engine -- Multi-Timeframe Analysis (MTA).

Alur keputusan 5 gate:
    GATE 1 -- Validasi awal   : bars cukup, ATR valid, cooldown, session
    GATE 2 -- HTF Bias        : vote bias dari TF lebih tinggi (EMA50/200)
    GATE 3 -- Trigger Score   : 6 komponen Layer-1 (min default 4/6)
    GATE 4 -- Confluence Score: 5 komponen Layer-2 (min default 2/5+)
                  - Candlestick Pattern (0-2)
                  - RSI/MACD Divergence (0-1)
                  - Fibonacci confluence  (0-2)
                  - SnR confluence        (0-1)
                  - SnD Zone confluence   (0-1)
    GATE 5 -- SL/TP & RR      : ATR-based (primary), fixed pip (fallback)
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytz

from src.features.fibonacci import fib_confluence_score
from src.features.session import is_active_session, session_name
from src.features.zones_snr import swing_points, nearest_level, snr_confluence_score
from src.features.zones_snd import snd_confluence_score
from src.models.signal import Signal
from src.risk.rr import calc_rr
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp
from src.strategy.timeframe_hierarchy import higher_timeframes


# ── State cooldown (per symbol+tf) ───────────────────────────────────
_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}


# ═════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════

def _atr_proxy(df: pd.DataFrame, n: int = 14) -> float:
    """Baca ATR dari kolom atr_14, fallback ke avg high-low range."""
    if "atr_14" in df.columns:
        v = df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            return float(v)
    if len(df) < 3:
        return 0.0
    w = df.iloc[-n:] if len(df) > n else df
    v = (w["high"].astype(float) - w["low"].astype(float)).mean()
    return float(v) if pd.notna(v) and v > 0 else 0.0


def _latest_closed(df: pd.DataFrame) -> pd.Series:
    """Candle kedua dari belakang = candle yang baru saja close."""
    return df.iloc[-2]


def _safe(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    return None if (v is None or pd.isna(v)) else float(v)


def _reject(df: pd.DataFrame, reason: str) -> None:
    df.attrs["reject_reason"] = reason


# ═════════════════════════════════════════════════════════════════════
# GATE 2 -- HTF BIAS
# ═════════════════════════════════════════════════════════════════════

def _bias_from_tf(df: pd.DataFrame) -> str | None:
    """Baca bias (BULL/BEAR) dari satu TF berdasarkan EMA50/200."""
    if len(df) < 220:
        return None
    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")
    if any(v is None for v in [close, ema50, ema200]):
        return None
    if close > ema200 and ema50 > ema200:    # type: ignore[operator]
        return "BULL"
    if close < ema200 and ema50 < ema200:    # type: ignore[operator]
        return "BEAR"
    return None


def _vote_bias(
    data_by_tf:  dict[str, pd.DataFrame],
    confirm_tfs: list[str],
) -> tuple[str | None, str]:
    """
    Vote bias dari semua TF konfirmasi.

    Returns:
        (bias, detail_str)
        bias = "BULL" / "BEAR" / None (jika seri atau tidak cukup vote)
    """
    votes   = {"BULL": 0, "BEAR": 0}
    details: list[str] = []

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING")
            continue
        b = _bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL")
            continue
        votes[b] += 1
        details.append(f"{tf}:{b}")

    if votes["BULL"] == votes["BEAR"]:
        return None, " ".join(details)
    return ("BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"), " ".join(details)


# ═════════════════════════════════════════════════════════════════════
# GATE 3 -- TRIGGER SCORE (Layer 1)
# ═════════════════════════════════════════════════════════════════════

def _trigger_score(
    df:        pd.DataFrame,
    direction: str,
    min_score: int = 4,
) -> tuple[bool, int, str]:
    """
    Hitung Trigger Score Layer-1 (maks 6 poin).

    Komponen:
        1. EMA200 side     -- WAJIB, langsung tolak jika gagal
        2. EMA50 pullback  -- entry dekat EMA50
        3. EMA alignment   -- EMA20 > EMA50 > EMA200 (BUY) atau sebaliknya
        4. RSI arah        -- RSI naik (BUY) / turun (SELL), tidak ekstrem
        5. MACD histogram  -- histogram naik (BUY) / turun (SELL)
        6. Candle          -- candle bullish (BUY) / bearish (SELL)

    Returns:
        (lulus, skor, notes)
    """
    direction = direction.upper()
    notes: list[str] = []
    score = 0

    if len(df) < 30:
        return False, 0, "TOO_FEW_BARS"

    last = _latest_closed(df)
    prev = df.iloc[-3] if len(df) > 3 else last

    close   = _safe(last, "close")
    open_   = _safe(last, "open")
    ema20   = _safe(last, "ema_20")
    ema50   = _safe(last, "ema_50")
    ema200  = _safe(last, "ema_200")
    rsi     = _safe(last, "rsi_14")
    rsi_p   = _safe(prev, "rsi_14")
    mhist   = _safe(last, "macdhist")
    mhist_p = _safe(prev, "macdhist")
    atr     = _atr_proxy(df)

    if close is None:
        return False, 0, "NO_CLOSE"

    # 1. EMA200 -- wajib
    if ema200 is not None:
        if (direction == "BUY" and close > ema200) or \
           (direction == "SELL" and close < ema200):
            score += 1; notes.append("EMA200+")
        else:
            notes.append("EMA200-(wajib)")
            return False, score, " ".join(notes)
    else:
        notes.append("EMA200_NA")

    # 2. EMA50 pullback
    if ema50 is not None and atr > 0:
        if abs(close - ema50) <= 2.0 * atr:
            score += 1; notes.append("EMA50+")
        else:
            notes.append("EMA50-")

    # 3. EMA alignment
    if all(v is not None for v in [ema20, ema50, ema200]):
        if (direction == "BUY"  and ema20 > ema50 > ema200) or \
           (direction == "SELL" and ema20 < ema50 < ema200):
            score += 1; notes.append("ALIGN+")
        else:
            notes.append("ALIGN-")

    # 4. RSI arah + tidak di zona ekstrem berlawanan
    if rsi is not None and rsi_p is not None:
        if (direction == "BUY" and rsi < 75 and rsi > rsi_p) or \
           (direction == "SELL" and rsi > 25 and rsi < rsi_p):
            score += 1; notes.append(f"RSI+({rsi:.0f})")
        else:
            notes.append(f"RSI-({rsi:.0f})")

    # 5. MACD histogram arah
    if mhist is not None and mhist_p is not None:
        if (direction == "BUY"  and mhist > mhist_p) or \
           (direction == "SELL" and mhist < mhist_p):
            score += 1; notes.append("MACD+")
        else:
            notes.append("MACD-")

    # 6. Candle konfirmasi
    if open_ is not None:
        if (direction == "BUY"  and close > open_) or \
           (direction == "SELL" and close < open_):
            score += 1; notes.append("CDL+")
        else:
            notes.append("CDL-")

    return score >= min_score, score, " ".join(notes)


# ═════════════════════════════════════════════════════════════════════
# GATE 4 -- CONFLUENCE SCORE (Layer 2)
# ═════════════════════════════════════════════════════════════════════

def _get_active_patterns(
    direction: str,
    last_row:  pd.Series,
) -> list[str]:
    """Kembalikan nama pattern yang aktif di candle terakhir."""
    from src.features.patterns import PATTERN_FUNCS
    names: list[str] = []
    for name in PATTERN_FUNCS:
        val = _safe(last_row, name)
        if val is None:
            continue
        if direction == "BUY"  and val >= 100:
            names.append(name.replace("CDL", ""))
        elif direction == "SELL" and val <= -100:
            names.append(name.replace("CDL", ""))
    return names


def _confluence_score(
    df:        pd.DataFrame,
    direction: str,
    entry:     float,
    atr:       float,
) -> tuple[int, str, dict]:
    """
    Hitung Confluence Score Layer-2 (maks ~7, target min 2).

    Komponen:
        - Candlestick Pattern  0-2
        - RSI/MACD Divergence  0-1
        - Fibonacci            0-2
        - SnR                  0-1
        - SnD Zone             0-1

    Returns:
        (total_score, notes_str, detail_dict)
    """
    direction = direction.upper()
    score = 0
    notes: list[str] = []
    detail: dict = {
        "pattern_names": "",
        "fib_detail":    "",
        "snr_detail":    "",
        "snd_detail":    "",
        "div_detail":    "",
    }

    last = _latest_closed(df)

    # 1. Candlestick Pattern
    bull_count = int(_safe(last, "pattern_bull_count") or 0)
    bear_count = int(_safe(last, "pattern_bear_count") or 0)

    if direction == "BUY":
        if bull_count >= 2:
            score += 2; notes.append("Pattern++")
        elif bull_count >= 1:
            score += 1; notes.append("Pattern+")
        else:
            notes.append("Pattern-")
    else:
        if bear_count >= 2:
            score += 2; notes.append("Pattern++")
        elif bear_count >= 1:
            score += 1; notes.append("Pattern+")
        else:
            notes.append("Pattern-")

    pattern_names = _get_active_patterns(direction, last)
    detail["pattern_names"] = ", ".join(pattern_names[:3]) if pattern_names else ""

    # 2. RSI / MACD Divergence
    rsi_bull_div  = bool(_safe(last, "rsi_bull_div")  or False)
    rsi_bear_div  = bool(_safe(last, "rsi_bear_div")  or False)
    macd_bull_div = bool(_safe(last, "macd_bull_div") or False)
    macd_bear_div = bool(_safe(last, "macd_bear_div") or False)

    div_parts: list[str] = []
    if direction == "BUY" and (rsi_bull_div or macd_bull_div):
        score += 1
        if rsi_bull_div:  div_parts.append("RSI_DIV")
        if macd_bull_div: div_parts.append("MACD_DIV")
        notes.append("Div+")
    elif direction == "SELL" and (rsi_bear_div or macd_bear_div):
        score += 1
        if rsi_bear_div:  div_parts.append("RSI_DIV")
        if macd_bear_div: div_parts.append("MACD_DIV")
        notes.append("Div+")
    else:
        notes.append("Div-")
    detail["div_detail"] = "+".join(div_parts)

    # 3. Fibonacci
    if atr > 0:
        fib_sc, fib_note = fib_confluence_score(direction, entry, df, atr)
        score += fib_sc
        notes.append(f"Fib+({fib_note})" if fib_sc > 0 else "Fib-")
        detail["fib_detail"] = fib_note if fib_sc > 0 else ""
    else:
        notes.append("Fib_SKIP")

    # 4. SnR
    if atr > 0:
        snr_sc = snr_confluence_score(direction, entry, df, atr)
        score += snr_sc

        recent = df.iloc[-200:] if len(df) > 200 else df
        highs, lows = swing_points(recent)
        nr = nearest_level(entry, highs)
        ns = nearest_level(entry, lows)
        snr_parts: list[str] = []
        if ns: snr_parts.append(f"S~{ns:.2f}")
        if nr: snr_parts.append(f"R~{nr:.2f}")
        detail["snr_detail"] = " ".join(snr_parts)
        notes.append("SnR+" if snr_sc > 0 else "SnR-")
    else:
        notes.append("SnR_SKIP")

    # 5. SnD Zone
    if atr > 0:
        snd_sc, snd_note = snd_confluence_score(direction, entry, df, atr)
        score += snd_sc
        notes.append("SnD+" if snd_sc > 0 else "SnD-")
        detail["snd_detail"] = snd_note if snd_sc > 0 else ""
    else:
        notes.append("SnD_SKIP")

    return score, " ".join(notes), detail


# ═════════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═════════════════════════════════════════════════════════════════════

def evaluate_any_tf_mta(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    trigger_tf:           str,
    enabled_tfs:          list[str],
    # Gate thresholds
    min_rr:               float = 1.5,
    min_confirm_votes:    int   = 1,
    min_trigger_score:    int   = 4,
    min_confluence_score: int   = 2,
    cooldown_bars:        int   = 3,
    atr_min_pct:          float = 0.0006,
    # SL/TP ATR params
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    # SL/TP fixed fallback
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    # Session filter
    session_filter:       bool  = True,
) -> Signal | None:
    """
    Evaluasi sinyal trading untuk satu (symbol, trigger_tf).

    Menjalankan 5 gate keputusan secara berurutan. Jika semua gate lulus,
    kembalikan objek Signal. Jika ada gate yang gagal, kembalikan None
    dan catat alasan di df_t.attrs["reject_reason"].

    Returns:
        Signal jika semua gate lulus, None jika ada yang gagal.
    """
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _reject(df_t, "INIT")

    # ── GATE 1: Validasi Awal ─────────────────────────────────────────

    if len(df_t) < 220:
        _reject(df_t, f"NOT_ENOUGH_BARS({len(df_t)})")
        return None

    last          = _latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"])
    close_time    = str(close_time_ts.to_pydatetime().isoformat())
    price_now     = float(last["close"])
    atr           = _atr_proxy(df_t)

    if atr <= 0:
        _reject(df_t, "ATR_INVALID"); return None
    if atr < (price_now * atr_min_pct):
        _reject(df_t, f"ATR_TOO_LOW({atr:.4f})"); return None

    # Cooldown
    key        = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        tf_min_map = {
            "M1": 1, "M5": 5, "M15": 15, "M30": 30,
            "H1": 60, "H4": 240, "D1": 1440,
        }
        tf_min     = tf_min_map.get(trigger_tf, 5)
        bars_since = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars_since < cooldown_bars:
            _reject(df_t, f"COOLDOWN({bars_since:.1f}bar)"); return None

    # Session filter
    now_utc = datetime.now(pytz.utc)
    sess    = session_name(now_utc)
    if session_filter and not is_active_session(now_utc, trigger_tf):
        _reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # ── GATE 2: HTF Bias ──────────────────────────────────────────────

    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = _vote_bias(data_by_tf, confirm_tfs)

    if confirm_tfs:
        bull_v = bias_detail.count(":BULL")
        bear_v = bias_detail.count(":BEAR")
        if max(bull_v, bear_v) < min_confirm_votes:
            bias = None

    # ── GATE 3: Trigger Score ─────────────────────────────────────────

    direction:  str | None = None
    trig_score: int        = 0
    trig_notes: str        = ""

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"
        ok, sc, nt = _trigger_score(df_t, dir_try, min_trigger_score)
        if ok:
            direction, trig_score, trig_notes = dir_try, sc, nt
        else:
            _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{min_trigger_score}[{nt}]")
            return None
    else:
        # Tidak ada bias jelas: coba kedua arah
        ok_b, sc_b, nt_b = _trigger_score(df_t, "BUY",  min_trigger_score)
        ok_s, sc_s, nt_s = _trigger_score(df_t, "SELL", min_trigger_score)
        if ok_b and ok_s:
            direction, trig_score, trig_notes = \
                ("BUY", sc_b, nt_b) if sc_b >= sc_s else ("SELL", sc_s, nt_s)
        elif ok_b:
            direction, trig_score, trig_notes = "BUY",  sc_b, nt_b
        elif ok_s:
            direction, trig_score, trig_notes = "SELL", sc_s, nt_s
        else:
            _reject(df_t, f"TRIGGER_FAIL BUY={sc_b} SELL={sc_s} min={min_trigger_score}")
            return None

    # ── GATE 4: Confluence Score ──────────────────────────────────────

    conf_score, conf_notes, conf_detail = _confluence_score(
        df_t, direction, price_now, atr
    )

    if conf_score < min_confluence_score:
        _reject(df_t,
            f"CONFLUENCE_FAIL conf={conf_score}/{min_confluence_score}[{conf_notes}]"
        )
        return None

    # ── GATE 5: SL/TP & RR ───────────────────────────────────────────

    plan = dynamic_atr_sltp(
        direction=direction, price_now=price_now, atr=atr,
        sl_atr_mult=sl_atr_mult, tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
    )
    sl_method = "dynamic_atr"

    if plan is None:
        plan = fixed_zone_sltp(
            direction=direction, price_now=price_now,
            entry_zone_pips=30, sl_pips=sl_pips,
            tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
            pip_size=pip_size,
        )
        sl_method = "fixed"

    if plan is None:
        _reject(df_t, "SLTP_NONE"); return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)

    if rr is None or rr < min_rr:
        _reject(df_t, f"RR_FAIL({rr})"); return None

    # ── Build reason (legacy kompatibilitas) ──────────────────────────

    reason = (
        f"{trigger_tf} {direction}"
        f" | HTF:{bias_detail}"
        f" | Trigger:{trig_score}/6[{trig_notes}]"
        f" | Conf:{conf_score}[{conf_notes}]"
        f" | Pattern:{conf_detail['pattern_names']}"
        f" | Fib:{conf_detail['fib_detail']}"
        f" | SnR:{conf_detail['snr_detail']}"
        f" | SnD:{conf_detail['snd_detail']}"
        f" | Div:{conf_detail['div_detail']}"
        f" | Session:{sess}"
        f" | SL:{sl_method}"
        f" | ATR:{atr:.4f}"
        f" | EZ={plan.entry_low:.2f}-{plan.entry_high:.2f}"
        f" | SL={plan.sl:.2f}"
        f" | TP1={plan.tp1:.2f} TP2={plan.tp2:.2f} TP3={plan.tp3:.2f}"
        f" | RR={rr:.2f}"
    )

    # ── Update state cooldown & return Signal ─────────────────────────

    _LAST_SIGNAL_TIME[key] = close_time_ts
    _reject(df_t, "OK")

    return Signal(
        symbol     = symbol,
        tf         = trigger_tf,
        direction  = direction,
        close_time = close_time,

        entry      = float(entry_for_rr),
        entry_low  = float(plan.entry_low),
        entry_high = float(plan.entry_high),
        sl         = float(plan.sl),
        tp         = float(plan.tp1),
        tp2        = float(plan.tp2),
        tp3        = float(plan.tp3),
        rr         = float(rr),
        sl_method  = sl_method,
        atr_value  = float(atr),
        tp1_rr     = float(tp1_rr),
        tp2_rr     = float(tp2_rr),
        tp3_rr     = float(tp3_rr),

        trigger_score    = trig_score,
        trigger_max      = 6,
        confluence_score = conf_score,
        htf_bias         = bias_detail,

        trigger_notes     = trig_notes,
        confluence_notes  = conf_notes,
        pattern_names     = conf_detail["pattern_names"],
        fib_detail        = conf_detail["fib_detail"],
        snr_detail        = conf_detail["snr_detail"],
        snd_detail        = conf_detail["snd_detail"],
        divergence_detail = conf_detail["div_detail"],
        session_name      = sess,

        reason = reason,
    )
