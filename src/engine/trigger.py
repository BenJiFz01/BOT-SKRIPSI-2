"""─ Trigger score & setup entry (continuation/pullback/momentum/range)."""

from __future__ import annotations

import pandas as pd

from src.engine.utils import _atr_proxy, _latest_closed, _safe


def _trigger_score(
    df:                 pd.DataFrame,
    direction:          str,
    min_score:          int = 4,
    ema200_tolerance_mult: float = 0.2,
) -> tuple[bool, int, str]:
    """Trigger Score Layer-1 (maks 6): EMA200, EMA50 pullback, EMA alignment, RSI, MACD, Candle.

    ema200_tolerance_mult: lebar band EMA200 (×ATR). Momentum lane memakai nilai lebih
    besar (default 1.0 via MOMENTUM_EMA200_TOLERANCE) agar tren kuat yang TIDAK menarik
    kembali ke EMA200 tetap bisa masuk — anti-chase (OVEREXTENSION & LATE_ENTRY) tetap
    jalan terpisah di gate berikutnya.
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

    # EMA200 — wajib
    if ema200 is not None:
        tolerance = ema200_tolerance_mult * atr if atr > 0 else 0.0
        in_band   = abs(close - ema200) <= tolerance  
        on_side   = (direction == "BUY"  and close > ema200 - tolerance) or \
                    (direction == "SELL" and close < ema200 + tolerance)
        if on_side or in_band:
            score += 1; notes.append("EMA200+")
        else:
            notes.append("EMA200-")
            return False, score, " ".join(notes)
    else:
        notes.append("EMA200_NA")

    # EMA50 pullback (dalam 1.5×ATR)
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

    # RSI
    if rsi is not None and rsi_p is not None:
        if (direction == "BUY"  and rsi < 65 and rsi > rsi_p) or \
           (direction == "SELL" and rsi > 35 and rsi < rsi_p):
            score += 1; notes.append(f"RSI+({rsi:.0f})")
        else:
            notes.append(f"RSI-({rsi:.0f})")

    # MACD histogram
    if mhist is not None and mhist_p is not None:
        if (direction == "BUY"  and mhist > mhist_p) or \
           (direction == "SELL" and mhist < mhist_p):
            score += 1; notes.append("MACD+")
        else:
            notes.append("MACD-")

    # Candle
    if open_ is not None:
        if (direction == "BUY"  and close > open_) or \
           (direction == "SELL" and close < open_):
            score += 1; notes.append("CDL+")
        else:
            notes.append("CDL-")

    return score >= min_score, score, " ".join(notes)


def _scalp_pullback_setup(
    df:        pd.DataFrame,
    direction: str,
    atr:       float,
) -> tuple[bool, str]:
    """Set-up pullback/rebound scalping: pause contra-tren sementara di dalam tren,
    masuk SEARAH tren setelah rebound — bukan "buy the dip".

    Gerbang wajib: trend_tf (bias HTF + EMA20>EMA50 + impuls >=1×ATR), zone (body
    menembus EMA20 dalam 0.8×ATR), deep (retracement 25-70%; >78.6% = reversal),
    structure (body tak menembus swing). Konfirmasi min 2/4: rejection (pin/engulf/
    sweep), rsi, momentum, div. Hanya bar tertutup dipakai."""
    direction = direction.upper()
    if len(df) < 40:
        return False, "TOO_FEW_BARS"

    last  = _latest_closed(df)
    prev  = df.iloc[-3] if len(df) > 3 else last
    close = _safe(last, "close")
    open_ = _safe(last, "open")
    high  = _safe(last, "high")
    low   = _safe(last, "low")
    e20   = _safe(last, "ema_20")
    e50   = _safe(last, "ema_50")
    rsi   = _safe(last, "rsi_14")
    rsi_p = _safe(prev, "rsi_14")
    mhist = _safe(last, "macdhist")
    mp    = _safe(prev, "macdhist")
    e20_prev  = _safe(df.iloc[-3], "ema_20")
    prev_open = _safe(df.iloc[-3], "open")
    if any(v is None for v in [close, open_, high, low, e20, e50, rsi, rsi_p, mhist, mp, e20_prev, prev_open]) or atr <= 0:
        return False, "DATA_INCOMPLETE"

    rng = high - low

    w_imp  = df.iloc[-9:-3]
    w_pb   = df.iloc[-3:-1]
    imp_high = float(w_imp["high"].max())
    imp_low  = float(w_imp["low"].min())
    imp_ext  = imp_high - imp_low
    body_raw = pd.concat([w_pb["open"], w_pb["close"]])
    body_low  = float(body_raw.min())

    if direction == "BUY":
        pb_low     = float(w_pb["low"].min())
        trend_tf   = e20 > e50 and close > e50 and e20 > e20_prev and imp_ext >= atr
        zone       = body_low < e20 and body_low <= e20 + 0.4 * atr and (e20 - body_low) <= 1.0 * atr
        retr       = (imp_high - body_low) / imp_ext if imp_ext > 0 else 0.0
        structure  = body_low > imp_low
        lower_wick = min(open_, close) - low
        sweep      = pb_low < imp_low and body_low >= imp_low and close > imp_low
        c_rej      = sweep or (close > open_ and rng > 0 and (lower_wick >= 0.4 * rng or close > prev_open))
        c_rsi      = rsi > rsi_p and 35 < rsi < 68
        c_mom      = mhist > mp
        c_div      = any(bool(_safe(r, "rsi_bull_div") or False) for _, r in w_pb.iterrows()) or \
                     any(bool(_safe(r, "macd_bull_div") or False) for _, r in w_pb.iterrows())
    else:
        body_high  = float(body_raw.max())
        pb_high    = float(w_pb["high"].max())
        trend_tf   = e20 < e50 and close < e50 and e20 < e20_prev and imp_ext >= atr
        zone       = body_high > e20 and body_high >= e20 - 0.4 * atr and (body_high - e20) <= 1.0 * atr
        retr       = (body_high - imp_low) / imp_ext if imp_ext > 0 else 0.0
        structure  = body_high < imp_high
        upper_wick = high - max(open_, close)
        sweep      = pb_high > imp_high and body_high <= imp_high and close < imp_high
        c_rej      = sweep or (close < open_ and rng > 0 and (upper_wick >= 0.4 * rng or close < prev_open))
        c_rsi      = rsi < rsi_p and 32 < rsi < 65
        c_mom      = mhist < mp
        c_div      = any(bool(_safe(r, "rsi_bear_div") or False) for _, r in w_pb.iterrows()) or \
                     any(bool(_safe(r, "macd_bear_div") or False) for _, r in w_pb.iterrows())

    deep     = 0.23 <= retr <= 0.786   # 2026-09-24: 25-70% -> 23-78.6% (batas fib sebelum reversal)
    rej_gate = ("trend_tf", trend_tf), ("zone", zone), ("deep", deep), ("structure", structure)
    for name, ok in rej_gate:
        if not ok:
            return False, name

    checks = {"rejection": c_rej, "rsi": c_rsi, "momentum": c_mom, "div": c_div}
    score  = sum(checks.values())
    detail = ",".join(f"{k}{'+' if v else '-'}" for k, v in checks.items())
    if score >= 2:
        return True, detail
    return False, f"{detail} score={score}/4"


def _range_rejection_setup(
    df:  pd.DataFrame,
    atr: float,
) -> tuple[str | None, str, int]:
    """RANGE lane (2026-09-24): sideways + rejection, tanpa gate tren.

    Sekadar candle rejection (pin/engulf/sweep) + RSI + momentum di kedua arah — pilih
    arah dgn skor tertinggi, min 2 dari 3. Key level (SnR/SnD) BUKAN di sini tapi di
    GATE 5: tanpa key level, konfluensi tak sampai 2 (dan ASIAN langsung reject).
    Returns (direction|None, note, score)."""
    if df is None or len(df) < 30 or atr <= 0:
        return None, "TOO_FEW_BARS", 0
    need = {"open", "close", "high", "low"}
    if not need.issubset(df.columns):
        return None, "DATA_INCOMPLETE", 0

    last  = _latest_closed(df)
    prev  = df.iloc[-3] if len(df) > 3 else last
    open_ = _safe(last, "open")
    close = _safe(last, "close")
    high  = _safe(last, "high")
    low   = _safe(last, "low")
    rsi   = _safe(last, "rsi_14")
    rsi_p = _safe(prev, "rsi_14")
    mhist = _safe(last, "macdhist")
    mp    = _safe(prev, "macdhist")
    prev_open = _safe(prev, "open")
    if any(v is None for v in [open_, close, high, low, rsi, rsi_p, mhist, mp, prev_open]):
        return None, "DATA_INCOMPLETE", 0

    rng = high - low
    if rng <= 0:
        return None, "ZERO_RANGE", 0
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)

    def _score_dir(d: str) -> int:
        if d == "BUY":
            c_rej = close > open_ and (lower_wick >= 0.4 * rng or close > prev_open)
            c_rsi = 30 <= rsi <= 68 and rsi > rsi_p
        else:
            c_rej = close < open_ and (upper_wick >= 0.4 * rng or close < prev_open)
            c_rsi = 32 <= rsi <= 70 and rsi < rsi_p
        c_mom = (mhist > mp) if d == "BUY" else (mhist < mp)
        return sum([c_rej, c_rsi, c_mom])

    sc_b, sc_s = _score_dir("BUY"), _score_dir("SELL")
    if sc_b >= sc_s and sc_b >= 2:
        return "BUY", f"rej_ok score={sc_b}/3", sc_b
    if sc_s >= 2:
        return "SELL", f"rej_ok score={sc_s}/3", sc_s
    return None, f"score_buy={sc_b},score_sell={sc_s}/3", 0


def _has_key_level(conf_notes: str) -> bool:
    """True jika ada SnR/SnD positif di notes konfluensi (varian WEAK/MED/OK)."""
    return any(k in conf_notes for k in ("SnR+", "SnR_WEAK", "SnR_MED", "SnD+"))


def _get_active_patterns(direction: str, last_row: pd.Series) -> list[str]:
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
