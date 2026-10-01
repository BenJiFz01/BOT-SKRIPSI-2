"""fair_value_gap.py — Deteksi FVG (3-candle imbalance, ICT).

Bullish: low[c3] > high[c1]; Bearish: high[c3] < low[c1]. Valid hanya jika belum
termitigasi dan age <= max_age_bars. Konfluensi terpisah, aktif hanya untuk scalping.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FvgConfig:
    min_gap_atr:  float   # gap minimum dalam kelipatan ATR (dibawah ini terlalu kecil)
    max_age_bars: int     # gap lebih tua dari ini diabaikan


_FVG_SCALPING = FvgConfig(min_gap_atr=0.3, max_age_bars=60)
_FVG_INTRADAY = FvgConfig(min_gap_atr=0.4, max_age_bars=100)

_NEAR_ENTRY_ATR = 1.5   # radius "dekat entry" (×ATR) untuk zona valid


def _atr_of(df: pd.DataFrame) -> float:
    if "atr_14" in df.columns:
        v = df["atr_14"].dropna()
        if len(v) > 0:
            val = float(v.iloc[-1])
            if val > 0:
                return val
    trs = (df["high"].tail(15) - df["low"].tail(15)).abs()
    return float(trs.mean()) if len(trs) > 0 else 0.0


def detect_fvg_zones(df: pd.DataFrame, cfg: FvgConfig) -> list[dict]:
    """Deteksi FVG 3-candle yang belum termitigasi.

    Hanya memakai bar tertutup (bar terakhir df = live candle, dilewati).
    Returns list of dict: {type, top, bottom, mid, gap_size, age_bars, strength}.
    """
    if len(df) < 6:
        return []

    closed = df.iloc[:-1] if len(df) > 2 else df
    data   = closed.reset_index(drop=True)
    n      = len(data)
    if n < 5:
        return []

    atr_local = _atr_of(data)
    if atr_local <= 0:
        return []

    lows  = data["low"].to_numpy(dtype=float)
    highs = data["high"].to_numpy(dtype=float)

    zones: list[dict] = []
    for i in range(2, n):
        if lows[i] > highs[i - 2]:
            gap_bot, gap_top = highs[i - 2], lows[i]
            ztype = "BULLISH"
        elif highs[i] < lows[i - 2]:
            gap_bot, gap_top = highs[i], lows[i - 2]
            ztype = "BEARISH"
        else:
            continue

        gap = gap_top - gap_bot
        if gap < cfg.min_gap_atr * atr_local:
            continue

        age = n - 1 - i
        if age > cfg.max_age_bars:
            continue

        # Mitigasi: ada candle setelah formasi yang menyentuh (overlap) gap
        filled = False
        for j in range(i + 1, n):
            if highs[j] >= gap_bot and lows[j] <= gap_top:
                filled = True
                break
        if filled:
            continue

        strength = 1
        if gap >= 2 * cfg.min_gap_atr * atr_local:
            strength += 1
        if age <= cfg.max_age_bars // 3:
            strength += 1

        zones.append({
            "type":      ztype,
            "top":       float(gap_top),
            "bottom":    float(gap_bot),
            "mid":       float((gap_top + gap_bot) / 2),
            "gap_size":  float(gap),
            "age_bars":  age,
            "strength":  strength,
        })
    return zones


def fvg_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    is_scalping: bool = True,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
) -> tuple[int, str]:
    """Skor konfluensi FVG: 0 atau 1.

    is_scalping menentukan konfigurasi gap (scalping vs intraday).
    `data_by_tf` untuk konsistensi tanda tangan — deteksi kini berbasis TF sinyal.
    """
    if atr <= 0:
        return 0, "FVG_SKIP"

    direction = direction.upper()
    cfg  = _FVG_SCALPING if is_scalping else _FVG_INTRADAY
    exp  = "BULLISH" if direction == "BUY" else "BEARISH"

    zones = detect_fvg_zones(df, cfg)
    if not zones:
        return 0, "FVG_NO_GAP"

    cands = [z for z in zones if z["type"] == exp]
    if not cands:
        return 0, "FVG_WRONG_SIDE"

    near       = _NEAR_ENTRY_ATR * atr
    near_cands = [z for z in cands if abs(entry_price - z["mid"]) <= near]
    if not near_cands:
        closest = min(cands, key=lambda z: abs(entry_price - z["mid"]))
        return 0, (f"FVG_FAR({closest['bottom']:.2f}-{closest['top']:.2f} "
                   f"dist={abs(entry_price - closest['mid']):.1f})")

    best = max(near_cands, key=lambda z: (z["strength"], -abs(entry_price - z["mid"])))
    # Prefiks FVG_OK wajib agar fvg_detail terbaca _COMP_KEYWORDS di signal_logger.get_stats()
    return 1, (f"FVG_OK({best['type']}({best['bottom']:.2f}-{best['top']:.2f} "
               f"gap={best['gap_size'] / atr:.1f}A age={best['age_bars']}b "
               f"str={best['strength']}))")