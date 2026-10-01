"""─ Confluence score & counter-trend validation."""

from __future__ import annotations

import re

import pandas as pd

from src.engine.bias import _bias_from_tf
from src.engine.trigger import _get_active_patterns
from src.engine.utils import _latest_closed, _safe
from src.features.fair_value_gap import fvg_confluence_score
from src.features.fibonacci import fib_confluence_score
from src.features.liquidity_sweep import liquidity_sweep_score
from src.features.session import session_strictness
from src.features.zones_snd import snd_confluence_score
from src.features.zones_snr import snr_confluence_score


def _confluence_score(
    df:          pd.DataFrame,
    direction:   str,
    entry:       float,
    atr:         float,
    tf:          str  = "",
    is_scalping: bool = False,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
    now_utc:     datetime | None = None,   # untuk cek Asian session strictness
    sweep_enabled: bool = False,  # skalprik: liquidity sweep ikut skor (off → logging-only)
    fvg_enabled:   bool = False,  # skalprik: FVG ikut skor (off → logging-only)
) -> tuple[int, str, dict]:
    """Confluence Score Layer-2 — berbobot sesuai akurasi historis komponen.

    Bobot: Pattern/Fib/Div 1.5, SND 2.0, SNR weighted (0.3x/0.6x/1.0x), Sweep+FVG
    gabungan 1.0 (scalping saja, OFF → logging-only). Alignment 3+ TF +1.0. Skor
    float dibulatkan ke int di akhir; minimal threshold dikalibrasi utk skala ini.
    """
    _W_PATTERN   = 1.5   
    _W_FIB       = 1.5   
    _W_DIV       = 1.5   
    _W_SNR       = 0.5   # akurasi rendah
    _W_SND       = 1.0   # akurasi rendah
    _W_SWEEP_FVG = 1.0   # bonus Sweep+FVG gabungan, default logging-only
    direction = direction.upper()
    score: float = 0.0
    notes: list[str] = []
    detail: dict = {
        "pattern_names": "",
        "fib_detail":    "",
        "snr_detail":    "",
        "snd_detail":    "",
        "div_detail":    "",
        "sweep_detail":  "",
        "fvg_detail":    "",
    }
    last = _latest_closed(df)

    bull_count = int(_safe(last, "pattern_bull_count") or 0)
    bear_count = int(_safe(last, "pattern_bear_count") or 0)
    count = bull_count if direction == "BUY" else bear_count
    if count >= 2:
        score += 2 * _W_PATTERN; notes.append("Pattern++")
    elif count >= 1:
        score += 1 * _W_PATTERN; notes.append("Pattern+")
    else:
        notes.append("Pattern-")
    # Fallback: scan ulang dari PATTERN_FUNCS agar pattern_names konsisten dengan skor
    pattern_names = _get_active_patterns(direction, last)
    if not pattern_names and count > 0:
        from src.features.patterns import PATTERN_FUNCS
        for pname in PATTERN_FUNCS:
            val = _safe(last, pname)
            if val is None:
                continue
            if direction == "BUY" and val > 0:
                pattern_names.append(pname.replace("CDL", ""))
            elif direction == "SELL" and val < 0:
                pattern_names.append(pname.replace("CDL", ""))
    detail["pattern_names"] = ", ".join(pattern_names[:3]) if pattern_names else ""

    div_keys = {
        "BUY":  [("rsi_bull_div", "RSI"), ("macd_bull_div", "MACD")],
        "SELL": [("rsi_bear_div", "RSI"), ("macd_bear_div", "MACD")],
    }
    div_parts: list[str] = []
    for col, label in div_keys.get(direction, []):
        if bool(_safe(last, col) or False):
            div_parts.append(label)
    if div_parts:
        score += 1 * _W_DIV; notes.append("Div+")
    else:
        notes.append("Div-")
    detail["div_detail"] = "+".join(div_parts)

    if atr > 0:
        fib_sc, fib_note = fib_confluence_score(
            direction=direction, entry_price=entry, df=df, atr=atr,
            is_scalping=is_scalping, data_by_tf=data_by_tf,
        )
        score += fib_sc * _W_FIB
        notes.append(f"Fib+({fib_note})" if fib_sc > 0 else "Fib-")
        detail["fib_detail"] = fib_note if fib_sc > 0 else ""
    else:
        notes.append("Fib_SKIP")

    if atr > 0:
        snr_sc, snr_note = snr_confluence_score(
            direction=direction, entry_price=entry,
            df=df, atr=atr, sl=sl, tp1_rr=tp1_rr,
            tf=tf, is_scalping=is_scalping,
            data_by_tf=data_by_tf,
        )
        # SNR_BLOCKED → hard reject
        if "SNR_BLOCKED" in snr_note:
            detail["snr_detail"] = snr_note
            notes.append("SnR_BLOCKED")
            return -99, " ".join(notes), detail

        # SNR weighted by touch count
        if snr_sc > 0:
            _str_match = re.search(r"str=(\d+)", snr_note)
            _snr_strength = int(_str_match.group(1)) if _str_match else 99
            if _snr_strength < 35:
                snr_sc = snr_sc * 0.3  # 30% weight untuk 2-touch
                snr_note = snr_note.replace("SNR_OK", "SNR_WEAK")
                notes.append("SnR_WEAK(0.3x)")
            elif _snr_strength < 50:
                snr_sc = snr_sc * 0.6  # 60% weight untuk 3-4 touch
                notes.append("SnR_MED(0.6x)")
            else:
                notes.append("SnR+")  # 100% weight untuk 5+ touch
        else:
            notes.append("SnR-")

        score += snr_sc * _W_SNR
        detail["snr_detail"] = snr_note
    else:
        notes.append("SnR_SKIP")

    if atr > 0:
        snd_sc, snd_note = snd_confluence_score(
            direction=direction, entry_price=entry,
            df=df, atr=atr, tf=tf, is_scalping=is_scalping,
            data_by_tf=data_by_tf,
        )
        score += snd_sc * _W_SND
        notes.append("SnD+" if snd_sc > 0 else "SnD-")
        detail["snd_detail"] = snd_note if snd_sc > 0 else ""
    else:
        notes.append("SnD_SKIP")

    # Sweep+FVG: scalping entry-timing, default logging-only
    if is_scalping and atr > 0:
        sweep_sc, sweep_note = liquidity_sweep_score(
            direction=direction, entry=entry, df=df, atr=atr,
            tf=tf, is_scalping=is_scalping, data_by_tf=data_by_tf,
        )
        fvg_sc, fvg_note = fvg_confluence_score(
            direction=direction, entry_price=entry, df=df, atr=atr,
            is_scalping=is_scalping, data_by_tf=data_by_tf,
        )
        detail["sweep_detail"] = sweep_note if sweep_sc > 0 else ""
        detail["fvg_detail"]   = fvg_note  if fvg_sc  > 0 else ""
        notes.append(sweep_note if sweep_sc > 0 else "SWEEP-")
        notes.append(fvg_note if fvg_sc > 0 else "FVG-")
        # Sweep/FVG bonus only with key level present
        _has_key_level = (snr_sc > 0) or (snd_sc > 0)
        _detected = [
            name
            for name, flagged, present in (
                ("Sweep", sweep_enabled, sweep_sc > 0),
                ("FVG",   fvg_enabled,   fvg_sc  > 0),
            )
            if flagged and present
        ]
        if _detected and _has_key_level:
            _share = _W_SWEEP_FVG / len(_detected)
            for _name in _detected:
                score += _share
                notes.append(f"{_name}+{_share:.1f}x")
        elif _detected:
            notes.append("SWEEP_FVG_NO_KEY_LEVEL")
    else:
        notes.append("SWEEP_SKIP")
        notes.append("FVG_SKIP")

    # Asian (06:00-14:00 WIB) volatilitas rendah, fake breakout dominan: CONTINUATION
    # butuh +1 confluence & +1 trigger; sinyal tanpa key level (SNR/SND) direject.
    # Cek variabel skor, bukan string notes. now_utc dari close_time candle.
    asian_session = session_strictness(now_utc, tf=tf) == "RELAXED"
    
    if is_scalping and asian_session:
        has_key_level = (snr_sc > 0) or (snd_sc > 0)
        if not has_key_level:
            notes.append("ASIAN_NO_KEY_LEVEL")
            detail["snr_detail"] = detail.get("snr_detail", "") or "ASIAN_REJECT"
            return -99, " ".join(notes), detail
        
        # Asian CONTINUATION butuh score lebih tinggi (handled by caller via threshold adjustment)
        notes.append("ASIAN_SESSION")

    # Multi-TF alignment: 3+ TF setuju satu arah → +1.0. H1 signal + align H4+D1
    # → +0.5 (kompensasi H1 underperform: butuh backing HTF).
    if data_by_tf and len(data_by_tf) >= 3:
        aligned_count = 0
        h4_aligned = False
        d1_aligned = False
        
        for other_tf, other_df in data_by_tf.items():
            if other_tf == tf or len(other_df) < 200:
                continue
            other_bias = _bias_from_tf(other_df)
            expected_bias = "BULL" if direction == "BUY" else "BEAR"
            
            if other_bias == expected_bias:
                aligned_count += 1
                if other_tf == "H4":
                    h4_aligned = True
                elif other_tf == "D1":
                    d1_aligned = True
        
        if aligned_count >= 3:
            score += 1.0
            notes.append(f"MTF_ALIGN({aligned_count})")
        
        if tf == "H1" and h4_aligned and d1_aligned:
            score += 0.5
            notes.append("H1_HTF_BACKED")

    # Bonus golden ratio (0.618) — level psikologis/teknikal terkuat
    if "fib_detail" in detail and detail["fib_detail"]:
        fib_detail_str = detail["fib_detail"]
        if "0.618" in fib_detail_str or "61.8" in fib_detail_str:
            score += 0.5
            notes.append("FIB_GOLDEN")

    # Floor ke int — threshold tetap integer, tanpa "kredit lebih" dari bobot
    return int(score), " ".join(notes), detail


def _is_counter_trend_valid(
    df:                     pd.DataFrame,
    direction:              str,
    entry:                  float,
    atr:                    float,
    tf:                     str  = "",
    min_counter_confluence: int  = 3,
    is_scalping:            bool = True,
    data_by_tf:             dict[str, pd.DataFrame] | None = None,
) -> tuple[bool, str, int]:
    """Validasi counter trend: Divergence wajib (primary reversal signal), lalu Fib, SND, SNR."""
    score = 0
    notes: list[str] = []
    last  = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

    # Divergence (MANDATORY untuk counter-trend - primary reversal signal)
    if direction == "BUY":
        rsi_div  = bool(_safe(last, "rsi_bull_div")  or False)
        macd_div = bool(_safe(last, "macd_bull_div") or False)
    else:
        rsi_div  = bool(_safe(last, "rsi_bear_div")  or False)
        macd_div = bool(_safe(last, "macd_bear_div") or False)

    if not (rsi_div or macd_div):
        return False, "NO_DIVERGENCE", 0

    if rsi_div and macd_div:
        score += 2; notes.append("DIV_BOTH+")
    elif rsi_div or macd_div:
        score += 1; notes.append("RSI_DIV+" if rsi_div else "MACD_DIV+")
    else:
        notes.append("DIV-")

    # Fibonacci — Bug #1+#3 fix: pass is_scalping + data_by_tf
    fib_sc, fib_note = fib_confluence_score(
        direction=direction, entry_price=entry, df=df, atr=atr,
        is_scalping=is_scalping, data_by_tf=data_by_tf,
    )
    if fib_sc >= 2:
        score += 2; notes.append(f"FIB_GOLD+({fib_note})")
    elif fib_sc == 1:
        score += 1; notes.append(f"FIB_NEAR+({fib_note})")
    else:
        notes.append(f"FIB-({fib_note})")

    # SND — Bug #1 fix: pass tf + data_by_tf
    snd_sc, snd_note = snd_confluence_score(
        direction=direction, entry_price=entry,
        df=df, atr=atr, tf=tf, is_scalping=is_scalping,
        data_by_tf=data_by_tf,
    )
    if snd_sc >= 1:
        score += 1; notes.append(f"SND+({snd_note})")
    else:
        notes.append(f"SND-({snd_note})")

    snr_sc, snr_note = snr_confluence_score(
        direction=direction, entry_price=entry,
        df=df, atr=atr, tf=tf, is_scalping=is_scalping,
        data_by_tf=data_by_tf,
    )
    if snr_sc >= 1:
        score += 1; notes.append(f"SNR+({snr_note})")
    else:
        notes.append(f"SNR-({snr_note})")

    return score >= min_counter_confluence, " ".join(notes), score
