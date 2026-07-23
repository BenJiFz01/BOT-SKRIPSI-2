"""zones_snr.py — Deteksi Support & Resistance berbasis swing point historis."""
from __future__ import annotations

import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[float], list[float]]:
    """Cari swing high dan swing low. Returns: (highs, lows)."""
    highs: list[float] = []
    lows:  list[float] = []
    if len(df) < left + right + 5:
        return highs, lows
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    for i in range(left, len(df) - right):
        if all(h[i] > h[i-j] for j in range(1, left+1)) and all(h[i] > h[i+j] for j in range(1, right+1)):
            highs.append(float(h[i]))
        if all(l[i] < l[i-j] for j in range(1, left+1)) and all(l[i] < l[i+j] for j in range(1, right+1)):
            lows.append(float(l[i]))
    return highs, lows


def cluster_levels(levels: list[float], tolerance: float) -> list[float]:
    """Gabungkan level berdekatan (dalam tolerance) menjadi rata-ratanya."""
    if not levels:
        return []
    sorted_lvl = sorted(levels)
    clusters: list[list[float]] = []
    current = [sorted_lvl[0]]
    for lv in sorted_lvl[1:]:
        if lv - current[-1] <= tolerance:
            current.append(lv)
        else:
            clusters.append(current)
            current = [lv]
    clusters.append(current)
    return [float(np.mean(c)) for c in clusters]


def nearest_level(price: float, levels: list[float]) -> float | None:
    """Kembalikan level yang paling dekat dengan price."""
    return min(levels, key=lambda x: abs(x - price)) if levels else None


def has_clear_road(
    direction:    str,
    entry_price:  float,
    sl:           float,
    tp1_rr:       float,
    resistances:  list[float],
    supports:     list[float],
    atr:          float,
    block_factor: float = 0.9,
) -> bool:
    """
    Validasi tidak ada S/R kuat menghalangi sebelum TP1.
    BUY: cek resistance antara entry dan 90% jarak TP1.
    SELL: cek support antara entry dan 90% jarak TP1.
    """
    if atr <= 0:
        return True
    sl_dist    = abs(entry_price - sl)
    block_zone = block_factor * sl_dist * tp1_rr
    min_dist   = 0.3 * atr
    if direction.upper() == "BUY":
        return not any(entry_price + min_dist < r <= entry_price + block_zone for r in resistances)
    return not any(entry_price - block_zone <= s < entry_price - min_dist for s in supports)


def snr_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
    lookback:    int   = 200,
    near_factor: float = 0.5,
) -> tuple[int, str]:
    """
    Skor konfluensi S/R (0-2).
    +1 jika entry dekat S/R relevan, 0 jika clear road terhambat.
    """
    if atr <= 0:
        return 0, "SNR_SKIP"

    recent = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = swing_points(recent)
    ctol = atr * 0.3
    resistances = cluster_levels(highs, ctol)
    supports    = cluster_levels(lows,  ctol)
    near_thr    = near_factor * atr
    direction   = direction.upper()

    nr = nearest_level(entry_price, resistances)
    ns = nearest_level(entry_price, supports)
    level_str = " ".join(filter(None, [f"S~{ns:.2f}" if ns else "", f"R~{nr:.2f}" if nr else ""]))

    if sl > 0 and not has_clear_road(direction, entry_price, sl, tp1_rr, resistances, supports, atr):
        return 0, f"SNR_BLOCKED({level_str})"

    score = 0
    if direction == "BUY":
        sups = [s for s in supports if s <= entry_price]
        if sups and abs(entry_price - max(sups)) <= near_thr:
            score = 1
    else:
        res = [r for r in resistances if r >= entry_price]
        if res and abs(min(res) - entry_price) <= near_thr:
            score = 1

    detail = f"SNR_OK({level_str})" if score > 0 else f"SNR_FAR({level_str})"
    return score, detail
