"""trigger.py — Trigger Score Layer-1 dan validasi counter trend."""

import pandas as pd

from src.engine.helpers import atr_proxy, latest_closed, safe
from src.features.fibonacci import fib_confluence_score
from src.features.zones_snr import snr_confluence_score
from src.features.zones_snd import snd_confluence_score


def trigger_score(df: pd.DataFrame, direction: str, min_score: int = 4) -> tuple[bool, int, str]:
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

    last  = latest_closed(df)
    prev  = df.iloc[-3] if len(df) > 3 else last
    close = safe(last, "close")
    if close is None:
        return False, 0, "NO_CLOSE"

    open_   = safe(last, "open")
    ema20   = safe(last, "ema_20")
    ema50   = safe(last, "ema_50")
    ema200  = safe(last, "ema_200")
    rsi     = safe(last, "rsi_14")
    rsi_p   = safe(prev, "rsi_14")
    mhist   = safe(last, "macdhist")
    mhist_p = safe(prev, "macdhist")
    atr     = atr_proxy(df)

    # Hard reject RSI ekstrem
    if rsi is not None:
        if direction == "SELL" and rsi < 35:
            return False, 0, f"RSI_OVERSOLD({rsi:.0f})"
        if direction == "BUY" and rsi > 65:
            return False, 0, f"RSI_OVERBOUGHT({rsi:.0f})"

    # EMA200 — wajib
    if ema200 is not None:
        ok = (direction == "BUY" and close > ema200) or (direction == "SELL" and close < ema200)
        if ok:
            score += 1; notes.append("EMA200+")
        else:
            return False, score, "EMA200-(wajib)"
    else:
        notes.append("EMA200_NA")

    # EMA50 pullback dalam 1.5×ATR
    if ema50 is not None and atr > 0:
        if abs(close - ema50) <= 1.5 * atr:
            score += 1; notes.append("EMA50+")
        else:
            notes.append("EMA50-")

    # EMA alignment
    if all(v is not None for v in [ema20, ema50, ema200]):
        aligned = (direction == "BUY" and ema20 > ema50 > ema200) or \
                  (direction == "SELL" and ema20 < ema50 < ema200)
        if aligned:
            score += 1; notes.append("ALIGN+")
        else:
            notes.append("ALIGN-")

    # RSI arah (dengan relaksasi saat momentum impulsif)
    momentum_strong = (
        mhist is not None and mhist_p is not None and open_ is not None
        and ((direction == "BUY" and mhist > mhist_p and close > open_)
             or (direction == "SELL" and mhist < mhist_p and close < open_))
    )
    if rsi is not None and rsi_p is not None:
        normal_ok = (
            (direction == "BUY"  and rsi < 65 and rsi > rsi_p)
            or (direction == "SELL" and rsi > 35 and rsi < rsi_p)
        )
        mom_ok = momentum_strong and (
            (direction == "BUY"  and rsi < 75 and rsi > rsi_p)
            or (direction == "SELL" and rsi > 25 and rsi < rsi_p)
        )
        if normal_ok or mom_ok:
            score += 1
            notes.append(f"{'RSI+MOM' if (mom_ok and not normal_ok) else 'RSI+'}({rsi:.0f})")
        else:
            notes.append(f"RSI-({rsi:.0f})")

    # MACD histogram
    if mhist is not None and mhist_p is not None:
        ok = (direction == "BUY" and mhist > mhist_p) or (direction == "SELL" and mhist < mhist_p)
        if ok:
            score += 1; notes.append("MACD+")
        else:
            notes.append("MACD-")

    # Candle konfirmasi
    if open_ is not None:
        ok = (direction == "BUY" and close > open_) or (direction == "SELL" and close < open_)
        if ok:
            score += 1; notes.append("CDL+")
        else:
            notes.append("CDL-")

    return score >= min_score, score, " ".join(notes)


def counter_trend_valid(
    df:            pd.DataFrame,
    direction:     str,
    entry:         float,
    atr:           float,
    min_confluence: int  = 3,
    is_scalping:   bool  = False,
) -> tuple[bool, str, int]:
    """
    Validasi sinyal counter trend.
    Wajib: Fibonacci level kuat + Divergence RSI/MACD + EMA200 mendukung.
    Returns (valid, detail, score).
    """
    score = 0
    notes: list[str] = []
    last  = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

    # EMA200 proximity check
    ema200 = safe(last, "ema_200")
    close  = safe(last, "close")
    if ema200 is not None and close is not None:
        dist = abs(close - ema200)
        ok = (close <= ema200 + 2.0 * atr) if direction == "SELL" else (close >= ema200 - 2.0 * atr)
        if not ok:
            return False, f"CT_EMA200_FAR(dist={dist:.2f})", 0
        if dist <= 0.5 * atr:
            score += 1; notes.append("EMA200_ZONE+")

    # Fibonacci wajib
    fib_sc, fib_note = fib_confluence_score(direction, entry, df, atr)
    if fib_sc >= 2:
        score += 2; notes.append(f"FIB_STRONG+({fib_note})")
    elif fib_sc == 1:
        score += 1; notes.append(f"FIB_NEAR+({fib_note})")
    else:
        return False, f"CT_NO_FIB({fib_note})", 0

    # Divergence wajib
    if direction == "BUY":
        rsi_div  = bool(safe(last, "rsi_bull_div")  or False)
        macd_div = bool(safe(last, "macd_bull_div") or False)
    else:
        rsi_div  = bool(safe(last, "rsi_bear_div")  or False)
        macd_div = bool(safe(last, "macd_bear_div") or False)

    if rsi_div and macd_div:
        score += 2; notes.append("DIV_BOTH+")
    elif rsi_div or macd_div:
        score += 1; notes.append("RSI_DIV+" if rsi_div else "MACD_DIV+")
    else:
        return False, "CT_NO_DIV", 0

    # SnR: wajib untuk scalping, bonus untuk intraday
    snr_sc, snr_note = snr_confluence_score(direction, entry, df, atr)
    if is_scalping:
        if snr_sc >= 1:
            score += 1; notes.append(f"SNR+({snr_note})")
        else:
            return False, f"CT_NO_SNR_SCALPING({snr_note})", 0
    elif snr_sc >= 1:
        score += 1; notes.append(f"SNR+({snr_note})")
    else:
        notes.append(f"SNR-({snr_note})")

    # SnD bonus
    snd_sc, snd_note = snd_confluence_score(direction, entry, df, atr)
    if snd_sc >= 1:
        score += 1; notes.append(f"SND+({snd_note})")
    else:
        notes.append(f"SND-({snd_note})")

    # RSI ekstrem — bonus
    rsi_val = safe(last, "rsi_14")
    if rsi_val is not None:
        if direction == "SELL" and float(rsi_val) >= 65:
            score += 1; notes.append(f"RSI_OB+({rsi_val:.0f})")
        elif direction == "BUY" and float(rsi_val) <= 35:
            score += 1; notes.append(f"RSI_OS+({rsi_val:.0f})")

    eff_min = (min_confluence + 1) if is_scalping else min_confluence
    return score >= eff_min, " ".join(notes), score
