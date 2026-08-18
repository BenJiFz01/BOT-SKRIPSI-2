"""confluence.py — Confluence Score Layer-2."""

import pandas as pd

from src.engine.helpers import latest_closed, safe
from src.features.fibonacci import fib_confluence_score
from src.features.zones_snr import snr_confluence_score
from src.features.zones_snd import snd_confluence_score


def _active_patterns(direction: str, last_row: pd.Series) -> list[str]:
    """Kembalikan nama candlestick pattern aktif di candle terakhir."""
    from src.features.patterns import PATTERN_FUNCS
    names: list[str] = []
    for name in PATTERN_FUNCS:
        val = safe(last_row, name)
        if val is None:
            continue
        if direction == "BUY" and val >= 100:
            names.append(name.replace("CDL", ""))
        elif direction == "SELL" and val <= -100:
            names.append(name.replace("CDL", ""))
    return names


def confluence_score(
    df:          pd.DataFrame,
    direction:   str,
    entry:       float,
    atr:         float,
    tf:          str  = "",
    is_scalping: bool = False,
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
    last = latest_closed(df)

    # Pattern
    bull_n = int(safe(last, "pattern_bull_count") or 0)
    bear_n = int(safe(last, "pattern_bear_count") or 0)
    count  = bull_n if direction == "BUY" else bear_n
    if count >= 2:
        score += 2; notes.append("Pattern++")
    elif count >= 1:
        score += 1; notes.append("Pattern+")
    else:
        notes.append("Pattern-")
    detail["pattern_names"] = ", ".join(_active_patterns(direction, last)[:3])

    # Divergence
    div_map = {
        "BUY":  [("rsi_bull_div", "RSI_DIV"), ("macd_bull_div", "MACD_DIV")],
        "SELL": [("rsi_bear_div", "RSI_DIV"), ("macd_bear_div", "MACD_DIV")],
    }
    div_parts: list[str] = []
    for col, label in div_map.get(direction, []):
        if bool(safe(last, col) or False):
            div_parts.append(label)
    if div_parts:
        score += 1; notes.append("Div+")
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

    # SnR
    if atr > 0:
        snr_sc, snr_note = snr_confluence_score(direction, entry, df, atr, sl=sl, tp1_rr=tp1_rr)
        if is_scalping and "SNR_BLOCKED" in snr_note:
            score -= 999
            detail["snr_detail"] = snr_note
            notes.append("SnR_BLOCKED(hard)")
        else:
            score += snr_sc
            detail["snr_detail"] = snr_note
            notes.append("SnR+" if snr_sc > 0 else "SnR-")
    else:
        notes.append("SnR_SKIP")

    # SnD
    if atr > 0:
        snd_sc, snd_note = snd_confluence_score(direction, entry, df, atr)
        score += snd_sc
        notes.append("SnD+" if snd_sc > 0 else "SnD-")
        detail["snd_detail"] = snd_note if snd_sc > 0 else ""
    else:
        notes.append("SnD_SKIP")

    return score, " ".join(notes), detail
