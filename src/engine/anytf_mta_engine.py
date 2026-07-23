"""anytf_mta_engine.py — Rule-Based Decision Engine (Multi-Timeframe Analysis).

5 gate: Validasi → HTF Bias → Trigger Score → Confluence Score → SL/TP & RR.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytz

from src.features.fibonacci import (
    fib_confluence_score, fib_levels, fib_lookback_for_tf, last_swing, nearest_fib,
)
from src.features.session import is_active_session, session_name
from src.features.zones_snr import snr_confluence_score
from src.features.zones_snd import snd_confluence_score
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp
from src.strategy.multi_timeframe import higher_timeframes

# Cooldown state per (symbol, tf)
_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}


def detect_market_condition(df: pd.DataFrame, atr_period: int = 20) -> str:
    """
    Deteksi kondisi pasar dari ATR relatif terhadap rata-rata historisnya.
    Returns: "volatile" | "sideways" | "normal".
    ATR > 1.5× avg → volatile, ATR < 0.7× avg → sideways.
    """
    col = "atr_14" if "atr_14" in df.columns else None
    if col is None or len(df) < atr_period + 3:
        return "normal"

    series = df[col].dropna()
    if len(series) < atr_period + 2:
        return "normal"

    current_atr = float(series.iloc[-2])
    avg_atr     = float(series.iloc[-(atr_period + 2):-2].mean())

    if avg_atr <= 0:
        return "normal"

    ratio = current_atr / avg_atr
    if ratio > 1.5:
        return "volatile"
    if ratio < 0.7:
        return "sideways"
    return "normal"


def calc_rr(direction: str, entry: float, sl: float, tp: float, min_risk: float = 0.0) -> float | None:
    """Hitung Risk-Reward Ratio. Returns RR float atau None jika input tidak valid."""
    try:
        entry = float(entry)
        sl    = float(sl)
        tp    = float(tp)
    except Exception:
        return None

    direction = direction.upper().strip()

    if direction == "BUY":
        risk   = entry - sl
        reward = tp - entry
    elif direction == "SELL":
        risk   = sl - entry
        reward = entry - tp
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    if min_risk > 0 and risk < min_risk:
        return None

    return reward / risk

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

def _bias_from_tf(df: pd.DataFrame) -> str | None:
    """Baca bias BULL/BEAR dari satu TF berdasarkan EMA50/200. Validasi gap, slope, fallback ATR."""
    if len(df) < 220:
        return None

    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")

    if any(v is None for v in [close, ema50, ema200]):
        return None

    is_bull_pos = close > ema200 and ema50 > ema200   # type: ignore[operator]
    is_bear_pos = close < ema200 and ema50 < ema200   # type: ignore[operator]

    if not (is_bull_pos or is_bear_pos):
        return None

    min_gap_pct = 0.0005
    gap_pct     = abs(ema50 - ema200) / close

    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()

    slope_ok = False
    if len(ema50_recent) >= 3:
        diffs   = ema50_recent.diff().dropna()
        n_up    = (diffs > 0).sum()
        n_dn    = (diffs < 0).sum()
        n_total = len(diffs)
        if is_bull_pos and n_up / n_total >= 0.5:
            slope_ok = True
        if is_bear_pos and n_dn / n_total >= 0.5:
            slope_ok = True
    else:
        slope_ok = True

    if gap_pct >= min_gap_pct and slope_ok:
        return "BULL" if is_bull_pos else "BEAR"

    atr = _atr_proxy(df)
    if atr > 0:
        if is_bull_pos and close > ema200 + atr:
            return "BULL"
        if is_bear_pos and close < ema200 - atr:
            return "BEAR"

    return None

def _vote_bias(
    data_by_tf:        dict[str, pd.DataFrame],
    confirm_tfs:       list[str],
    trigger_tf:        str = "M5",
    min_confirm_votes: int = 1,
) -> tuple[str | None, str]:
    """
    Vote bias dari TF konfirmasi.
    M5/M15 → hanya H1 penentu. H1 → hanya H4. H4/D1 → semua ikut voting.
    Returns (bias, detail_str).
    """
    trigger_up = trigger_tf.upper()

    # TF yang benar-benar ikut voting (penentu)
    _decisive_tf: dict[str, list[str]] = {
        "M5":  ["H1"],
        "M15": ["H1"],
        "H1":  ["H4"],
    }
    decisive_tfs = _decisive_tf.get(trigger_up)   # None = semua ikut (H4/D1)

    votes   = {"BULL": 0, "BEAR": 0}
    details: list[str] = []
    votes_by_tf: dict[str, str] = {}

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING")
            continue
        b = _bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL")
            continue

        details.append(f"{tf}:{b}")

        if decisive_tfs is None or tf in decisive_tfs:
            votes[b]       += 1
            votes_by_tf[tf] = b

    if not votes_by_tf:
        return None, " ".join(details)

    if votes["BULL"] == votes["BEAR"]:
        return None, " ".join(details)
    bias = "BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"

    # Validasi: TF wajib harus ada dan selaras
    _required_tf: dict[str, str | None] = {
        "M5":  "H1",
        "M15": "H1",
        "H1":  "H4",
        "H4":  None,
        "D1":  None,
    }
    required = _required_tf.get(trigger_up)
    if required is not None:
        req_vote = votes_by_tf.get(required)
        if req_vote is None or req_vote != bias:
            return None, " ".join(details) + f" [TF_FAIL:{required}_diperlukan]"

    if max(votes["BULL"], votes["BEAR"]) < min_confirm_votes:
        return None, " ".join(details)

    return bias, " ".join(details)

def _detect_trade_mode(trigger_tf: str) -> tuple[str, str]:
    """
    Tentukan trade_mode dan exec_tf berdasarkan trigger TF.
    Returns (trade_mode, exec_tf).
    """
    trigger_tf = trigger_tf.upper()
    if trigger_tf in ("M5", "M15"):
        return "scalping", "M5"
    elif trigger_tf == "H1":
        return "intraday", "M15"
    else:
        return "intraday", "H1"

def _trigger_score(df: pd.DataFrame, direction: str, min_score: int = 4) -> tuple[bool, int, str]:
    """
    Hitung Trigger Score Layer-1 (maks 6).
    Komponen: EMA200(wajib), EMA50 pullback, EMA alignment, RSI, MACD hist, Candle.
    Returns (lulus, skor, notes).
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

    # EMA200 — wajib, langsung tolak jika gagal
    if ema200 is not None:
        if (direction == "BUY" and close > ema200) or \
           (direction == "SELL" and close < ema200):
            score += 1; notes.append("EMA200+")
        else:
            notes.append("EMA200-(wajib)")
            return False, score, " ".join(notes)
    else:
        notes.append("EMA200_NA")

    # EMA50 pullback — dalam radius 1.5×ATR dari EMA50
    if ema50 is not None and atr > 0:
        if abs(close - ema50) <= 1.5 * atr:
            score += 1; notes.append("EMA50+")
        else:
            notes.append("EMA50-")

    # EMA alignment
    if all(v is not None for v in [ema20, ema50, ema200]):
        if (direction == "BUY"  and ema20 > ema50 > ema200) or \
           (direction == "SELL" and ema20 < ema50 < ema200):
            score += 1; notes.append("ALIGN+")
        else:
            notes.append("ALIGN-")

    # RSI arah + tidak di zona ekstrem
    if rsi is not None and rsi_p is not None:
        if (direction == "BUY"  and rsi < 65 and rsi > rsi_p) or \
           (direction == "SELL" and rsi > 35 and rsi < rsi_p):
            score += 1; notes.append(f"RSI+({rsi:.0f})")
        else:
            notes.append(f"RSI-({rsi:.0f})")

    # MACD histogram arah
    if mhist is not None and mhist_p is not None:
        if (direction == "BUY"  and mhist > mhist_p) or \
           (direction == "SELL" and mhist < mhist_p):
            score += 1; notes.append("MACD+")
        else:
            notes.append("MACD-")

    # Candle konfirmasi
    if open_ is not None:
        if (direction == "BUY"  and close > open_) or \
           (direction == "SELL" and close < open_):
            score += 1; notes.append("CDL+")
        else:
            notes.append("CDL-")

    return score >= min_score, score, " ".join(notes)

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
    df:          pd.DataFrame,
    direction:   str,
    entry:       float,
    atr:         float,
    tf:          str   = "",
    is_scalping: bool  = False,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
) -> tuple[int, str, dict]:
    """
    Hitung Confluence Score Layer-2 (maks ~7, target min 2).
    Komponen: Pattern(0-2), Divergence(0-1), Fibonacci(0-2), SnR(0-1), SnD(0-1).
    Returns (total_score, notes_str, detail_dict).
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

    # Candlestick Pattern
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

    # RSI / MACD Divergence
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

    # Fibonacci
    if atr > 0:
        fib_sc, fib_note = fib_confluence_score(direction, entry, df, atr, tf=tf)
        score += fib_sc
        notes.append(f"Fib+({fib_note})" if fib_sc > 0 else "Fib-")
        detail["fib_detail"] = fib_note if fib_sc > 0 else ""
    else:
        notes.append("Fib_SKIP")

    # SnR — reject scalping jika jalan terblokir
    if atr > 0:
        snr_sc, snr_note = snr_confluence_score(
            direction=direction, entry_price=entry,
            df=df, atr=atr, sl=sl, tp1_rr=tp1_rr,
        )
        if is_scalping and "SNR_BLOCKED" in snr_note:
            score = -99
            detail["snr_detail"] = snr_note
            notes.append("SnR_BLOCKED(REJECT)")
            return score, " ".join(notes), detail
        score += snr_sc
        detail["snr_detail"] = snr_note
        notes.append("SnR+" if snr_sc > 0 else "SnR-")
    else:
        notes.append("SnR_SKIP")

    # SnD Zone
    if atr > 0:
        snd_sc, snd_note = snd_confluence_score(direction, entry, df, atr)
        score += snd_sc
        notes.append("SnD+" if snd_sc > 0 else "SnD-")
        detail["snd_detail"] = snd_note if snd_sc > 0 else ""
    else:
        notes.append("SnD_SKIP")

    return score, " ".join(notes), detail


def _is_counter_trend_valid(
    df:                    pd.DataFrame,
    direction:             str,
    entry:                 float,
    atr:                   float,
    min_counter_confluence: int = 3,
) -> tuple[bool, str, int]:
    """
    Validasi counter trend. Wajib ada divergence.
    Tambahan: Fib golden zone, SnD zone, SnR (bonus).
    Returns (valid, detail, score).
    """
    score = 0
    notes = []

    last = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

    # Divergence — wajib ada
    has_div = False
    if direction == "BUY":
        rsi_div  = bool(_safe(last, "rsi_bull_div")  or False)
        macd_div = bool(_safe(last, "macd_bull_div") or False)
    else:
        rsi_div  = bool(_safe(last, "rsi_bear_div")  or False)
        macd_div = bool(_safe(last, "macd_bear_div") or False)

    if rsi_div and macd_div:
        score += 2; notes.append("DIV_BOTH+"); has_div = True
    elif rsi_div or macd_div:
        div_name = "RSI_DIV" if rsi_div else "MACD_DIV"
        score += 1; notes.append(f"{div_name}+"); has_div = True
    else:
        notes.append("DIV-")

    if not has_div:
        return False, "COUNTER_NO_DIV", 0

    # Fibonacci golden zone
    fib_sc, fib_note = fib_confluence_score(direction, entry, df, atr)
    if fib_sc >= 2:
        score += 2; notes.append(f"FIB_GOLD+({fib_note})")
    elif fib_sc == 1:
        score += 1; notes.append(f"FIB_NEAR+({fib_note})")
    else:
        notes.append(f"FIB-({fib_note})")

    # Supply/Demand Zone
    snd_sc, snd_note = snd_confluence_score(direction, entry, df, atr)
    if snd_sc >= 1:
        score += 1; notes.append(f"SND+({snd_note})")
    else:
        notes.append(f"SND-({snd_note})")

    # SnR (bonus)
    snr_sc, snr_note = snr_confluence_score(direction, entry, df, atr)
    if snr_sc >= 1:
        score += 1; notes.append(f"SNR+({snr_note})")
    else:
        notes.append(f"SNR-({snr_note})")

    detail = " ".join(notes)
    return score >= min_counter_confluence, detail, score

def scan_setup_plan(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    enabled_tfs:          list[str],
    min_confirm_votes:    int   = 1,
    atr_min_pct:          float = 0.0006,
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    max_sl_points:        float = 50.0,
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    session_filter:       bool  = True,
) -> list[Signal]:
    """
    Scan setup plan dari kondisi M15+H1 atau H1+H4.
    Returns list Signal dengan is_setup_plan=True (bisa kosong).
    """
    enabled_tfs = [tf.upper() for tf in enabled_tfs]
    results: list[Signal] = []

    scan_pairs = []
    if "M15" in enabled_tfs and "H1" in enabled_tfs:
        scan_pairs.append(("M15", "M5",  "scalping",  "H1"))
    if "H1"  in enabled_tfs and "H4" in enabled_tfs:
        scan_pairs.append(("H1",  "M15", "intraday",  "H4"))

    now_utc = __import__("datetime").datetime.now(__import__("pytz").utc)

    for anchor_tf, exec_tf, trade_mode, required_htf in scan_pairs:
        df_anchor = data_by_tf.get(anchor_tf)
        df_htf    = data_by_tf.get(required_htf)

        if df_anchor is None or df_htf is None:
            continue
        if len(df_anchor) < 220:
            continue

        if session_filter and not is_active_session(now_utc, anchor_tf):
            continue

        htf_bias = _bias_from_tf(df_htf)
        if htf_bias is None:
            continue

        anchor_bias = _bias_from_tf(df_anchor)
        if anchor_bias is not None and anchor_bias != htf_bias:
            continue

        direction = "BUY" if htf_bias == "BULL" else "SELL"

        last      = _latest_closed(df_anchor)
        price_now = float(last["close"])
        atr       = _atr_proxy(df_anchor)
        sess      = session_name(now_utc)
        close_time = str(
            __import__("pandas").to_datetime(last["time"]).to_pydatetime().isoformat()
        )

        if atr <= 0 or atr < price_now * atr_min_pct:
            continue

        # Tentukan entry zone: utamakan Fibonacci, fallback ke EMA50
        ema50_val = _safe(last, "ema_50")

        fib_anchor:      float | None = None
        fib_anchor_name: str          = ""

        swing = last_swing(df_anchor, lookback=fib_lookback_for_tf(anchor_tf), direction=direction)
        if swing is not None:
            levels = fib_levels(swing[0], swing[1], swing[2])
            anchor_ref = ema50_val if ema50_val is not None else price_now
            candidates: list[tuple[float, str, float]] = []
            for name, px in levels.items():
                dist = abs(px - anchor_ref)
                if dist <= 1.5 * atr:
                    try:
                        lv = float(name.replace("fib_", ""))
                    except ValueError:
                        lv = 99.0
                    weight = 0.0 if lv in {0.382, 0.5, 0.618} else dist
                    candidates.append((weight, name, px))
            if candidates:
                candidates.sort()
                fib_anchor      = candidates[0][2]
                fib_anchor_name = candidates[0][1]

        if fib_anchor is not None:
            if direction == "BUY":
                pb_low  = fib_anchor - 0.25 * atr
                pb_high = fib_anchor + 0.25 * atr
            else:
                pb_low  = fib_anchor - 0.25 * atr
                pb_high = fib_anchor + 0.25 * atr
            pullback_price = fib_anchor
        elif ema50_val is not None:
            if direction == "BUY":
                pb_low  = ema50_val - 0.3 * atr
                pb_high = ema50_val + 0.5 * atr
            else:
                pb_low  = ema50_val - 0.5 * atr
                pb_high = ema50_val + 0.3 * atr
            pullback_price = ema50_val
        else:
            if direction == "BUY":
                pb_low  = price_now - 1.2 * atr
                pb_high = price_now - 0.5 * atr
            else:
                pb_low  = price_now + 0.5 * atr
                pb_high = price_now + 1.2 * atr
            pullback_price = (pb_low + pb_high) / 2

        # Koreksi jika zona pullback sudah lewat harga saat ini
        if direction == "BUY" and pb_high >= price_now:
            pb_high = price_now - 0.2 * atr
            pb_low  = price_now - 0.8 * atr
            pullback_price = pb_high
        elif direction == "SELL" and pb_low <= price_now:
            pb_low  = price_now + 0.2 * atr
            pb_high = price_now + 0.8 * atr
            pullback_price = pb_low

        plan = dynamic_atr_sltp(
            direction=direction, price_now=pullback_price, atr=atr,
            sl_atr_mult=sl_atr_mult, tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
            max_sl_points=max_sl_points,
        )
        if plan is None:
            plan = fixed_zone_sltp(
                direction=direction, price_now=pullback_price,
                entry_zone_pips=30, sl_pips=sl_pips,
                tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
                pip_size=pip_size,
            )
        if plan is None:
            continue

        plan.entry_low  = round(pb_low,  2)
        plan.entry_high = round(pb_high, 2)

        entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
        rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
        if rr is None or rr < 1.5:
            continue

        confirm_tfs = higher_timeframes(anchor_tf, enabled_tfs)
        _, bias_detail = _vote_bias(
            data_by_tf        = data_by_tf,
            confirm_tfs       = confirm_tfs,
            trigger_tf        = anchor_tf,
            min_confirm_votes = min_confirm_votes,
        )

        conf_score, conf_notes, conf_detail = _confluence_score(
            df        = df_anchor,
            direction = direction,
            entry     = price_now,
            atr       = atr,
            tf        = anchor_tf,
            is_scalping = (trade_mode == "scalping"),
            sl        = float(plan.sl),
            tp1_rr    = tp1_rr,
        )

        results.append(Signal(
            symbol     = symbol,
            tf         = anchor_tf,
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
            sl_method  = "dynamic_atr",
            atr_value  = float(atr),
            tp1_rr     = float(tp1_rr),
            tp2_rr     = float(tp2_rr),
            tp3_rr     = float(tp3_rr),

            trigger_score    = 0,
            trigger_max      = 6,
            confluence_score = conf_score,
            htf_bias         = bias_detail,

            trigger_notes     = f"SETUP_PLAN via {required_htf}:{htf_bias}" + (f" | Fib={fib_anchor_name}@{fib_anchor:.2f}" if fib_anchor is not None else " | zona EMA50"),
            confluence_notes  = conf_notes,
            pattern_names     = conf_detail["pattern_names"],
            fib_detail        = conf_detail["fib_detail"],
            snr_detail        = conf_detail["snr_detail"],
            snd_detail        = conf_detail["snd_detail"],
            divergence_detail = conf_detail["div_detail"],
            session_name      = sess,

            signal_mode   = "trend",
            trade_mode    = trade_mode,
            exec_tf       = exec_tf,
            is_setup_plan = True,
            reason        = f"SETUP_PLAN {anchor_tf} {direction} | HTF:{required_htf}:{htf_bias}",
        ))

    return results



def evaluate_any_tf_mta(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    trigger_tf:           str,
    enabled_tfs:          list[str],
    min_rr:               float = 1.5,
    min_confirm_votes:    int   = 1,
    min_trigger_score:    int   = 4,
    min_confluence_score: int   = 2,
    cooldown_bars:        int   = 3,
    atr_min_pct:          float = 0.0006,
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    max_sl_points:        float = 50.0,
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    session_filter:       bool  = True,
    counter_trend_enabled:   bool      = True,
    min_counter_confluence:  int       = 3,
    counter_trend_min_rr:    float     = 2.0,
    counter_trend_tfs:       list[str] | None = None,
    scalping_min_trigger_score:    int   = 3,
    scalping_min_confluence_score: int   = 1,
    scalping_sl_atr_mult:          float = 1.2,
    scalping_cooldown_bars:        int   = 5,
) -> Signal | None:
    """Evaluasi sinyal trading untuk satu (symbol, trigger_tf). Return Signal jika 5 gate lulus."""
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _reject(df_t, "INIT")

    # GATE 1: Validasi Awal
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

    _scalping_tfs = {"M5", "M15"}
    is_scalping   = trigger_tf in _scalping_tfs

    if is_scalping:
        base_trigger_score    = scalping_min_trigger_score
        base_confluence_score = scalping_min_confluence_score
        base_sl_atr_mult      = scalping_sl_atr_mult
        base_cooldown         = scalping_cooldown_bars
    else:
        base_trigger_score    = min_trigger_score
        base_confluence_score = min_confluence_score
        base_sl_atr_mult      = sl_atr_mult
        base_cooldown         = cooldown_bars

    market_cond = detect_market_condition(df_t)
    if market_cond == "volatile":
        eff_trigger_score    = max(1, base_trigger_score - 1)
        eff_confluence_score = max(1, base_confluence_score - 1)
        eff_sl_atr_mult      = base_sl_atr_mult * 1.3
    elif market_cond == "sideways":
        eff_trigger_score    = base_trigger_score + 1
        eff_confluence_score = base_confluence_score + 1
        eff_sl_atr_mult      = base_sl_atr_mult
    else:
        eff_trigger_score    = base_trigger_score
        eff_confluence_score = base_confluence_score
        eff_sl_atr_mult      = base_sl_atr_mult

    key        = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        tf_min_map = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}
        tf_min     = tf_min_map.get(trigger_tf, 5)
        bars_since = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars_since < base_cooldown:
            _reject(df_t, f"COOLDOWN({bars_since:.1f}bar)"); return None

    now_utc = datetime.now(pytz.utc)
    sess    = session_name(now_utc)
    if session_filter and not is_active_session(now_utc, trigger_tf):
        _reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # GATE 2: HTF Bias
    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = _vote_bias(
        data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
        trigger_tf=trigger_tf, min_confirm_votes=min_confirm_votes,
    )

    # GATE 3: Trigger Score
    direction:   str | None = None
    trig_score:  int        = 0
    trig_notes:  str        = ""
    _is_counter: bool       = False

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"
        ok, sc, nt = _trigger_score(df_t, dir_try, eff_trigger_score)
        if ok:
            direction, trig_score, trig_notes = dir_try, sc, nt
        else:
            _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{eff_trigger_score}[{nt}] cond={market_cond}")
            return None
    else:
        _ct_tfs = [t.upper() for t in (counter_trend_tfs or ["H1", "H4"])]
        if not counter_trend_enabled or trigger_tf not in _ct_tfs:
            _reject(df_t, f"BIAS_FAIL({bias_detail})")
            return None

        ct_direction: str | None = None
        ct_detail:    str        = ""
        ct_score:     int        = 0
        for try_dir in ["BUY", "SELL"]:
            ok_ct, detail_ct, score_ct = _is_counter_trend_valid(
                df=df_t, direction=try_dir, entry=price_now,
                atr=atr, min_counter_confluence=min_counter_confluence,
            )
            if ok_ct and score_ct > ct_score:
                ct_direction, ct_detail, ct_score = try_dir, detail_ct, score_ct

        if ct_direction is None:
            _reject(df_t, f"BIAS_FAIL+CT_FAIL({bias_detail})")
            return None

        direction   = ct_direction
        _is_counter = True
        ok_trig, trig_score, trig_full = _trigger_score(df_t, direction, min_score=1)
        trig_notes = f"{trig_full} [CT:{ct_detail} score={ct_score}]"
        if "EMA200-" in trig_full:
            _reject(df_t, f"CT_EMA200_FAIL({trig_full})")
            return None

    # GATE 4 & 5: SL/TP + Confluence + RR
    plan = dynamic_atr_sltp(
        direction=direction, price_now=price_now, atr=atr,
        sl_atr_mult=eff_sl_atr_mult, tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
        max_sl_points=max_sl_points,
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

    conf_score, conf_notes, conf_detail = _confluence_score(
        df=df_t, direction=direction, entry=price_now, atr=atr,
        tf=trigger_tf, is_scalping=is_scalping, sl=float(plan.sl), tp1_rr=tp1_rr,
    )
    if conf_score == -99:
        _reject(df_t, f"SNR_BLOCKED_SCALPING [{conf_notes}]")
        return None
    if conf_score < eff_confluence_score:
        _reject(df_t, f"CONFLUENCE_FAIL conf={conf_score}/{eff_confluence_score}[{conf_notes}] cond={market_cond}")
        return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
    _min_rr_eff = counter_trend_min_rr if _is_counter else min_rr
    if rr is None or rr < _min_rr_eff:
        _reject(df_t, f"RR_FAIL({rr} < {_min_rr_eff})"); return None

    _LAST_SIGNAL_TIME[key] = close_time_ts
    _reject(df_t, "OK")

    trade_mode, exec_tf = _detect_trade_mode(trigger_tf)

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
        trigger_notes    = f"{trig_notes} [mkt={market_cond}]" if market_cond != "normal" else trig_notes,
        confluence_notes = conf_notes,
        pattern_names    = conf_detail["pattern_names"],
        fib_detail       = conf_detail["fib_detail"],
        snr_detail       = conf_detail["snr_detail"],
        snd_detail       = conf_detail["snd_detail"],
        divergence_detail= conf_detail["div_detail"],
        session_name     = sess,
        signal_mode      = "counter_trend" if _is_counter else "trend",
        trade_mode       = trade_mode,
        exec_tf          = exec_tf,
        is_setup_plan    = False,
    )


