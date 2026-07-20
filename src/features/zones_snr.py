"""
zones_snr.py
============
Deteksi Support & Resistance berbasis swing point historis.

Logika:
    1. Cari swing high (kandidat resistance) dan swing low (kandidat support)
       dalam lookback candle terakhir.
    2. Kluster level yang berdekatan menjadi satu zona.
    3. Skor konfluensi: +1 jika entry dekat support/resistance yang relevan.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def swing_points(
    df:    pd.DataFrame,
    left:  int = 3,
    right: int = 3,
) -> tuple[list[float], list[float]]:
    """
    Cari semua swing high dan swing low pada DataFrame.

    Returns:
        (highs, lows) — list harga swing high dan swing low.
    """
    highs: list[float] = []
    lows:  list[float] = []

    if len(df) < left + right + 5:
        return highs, lows

    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)

    for i in range(left, len(df) - right):
        if (all(h[i] > h[i - j] for j in range(1, left + 1)) and
                all(h[i] > h[i + j] for j in range(1, right + 1))):
            highs.append(float(h[i]))
        if (all(l[i] < l[i - j] for j in range(1, left + 1)) and
                all(l[i] < l[i + j] for j in range(1, right + 1))):
            lows.append(float(l[i]))

    return highs, lows


def cluster_levels(levels: list[float], tolerance: float) -> list[float]:
    """
    Gabungkan level-level yang berdekatan (dalam `tolerance`) menjadi rata-ratanya.

    Returns:
        List harga cluster (rata-rata per grup).
    """
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
    """Kembalikan level yang paling dekat dengan `price`."""
    if not levels:
        return None
    return min(levels, key=lambda x: abs(x - price))


def snr_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    lookback:    int   = 200,
    near_factor: float = 0.5,
) -> int:
    """
    Hitung skor konfluensi Support & Resistance (0 atau 1).

    BUY:  +1 jika entry dekat support, +1 lagi jika tidak ada resistance di atas yang terlalu dekat.
    SELL: +1 jika entry dekat resistance, +1 lagi jika tidak ada support di bawah yang terlalu dekat.

    Returns:
        Skor konfluensi (0 atau 1, maksimal 1 per fungsi ini).
    """
    if atr <= 0:
        return 0

    recent      = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = swing_points(recent)
    ctol        = atr * 0.3
    resistances = cluster_levels(highs, ctol)
    supports    = cluster_levels(lows,  ctol)
    near_thr    = near_factor * atr
    score       = 0
    direction   = direction.upper()

    if direction == "BUY":
        # Entry dekat support di bawah
        sups = [s for s in supports if s <= entry_price]
        if sups and abs(entry_price - max(sups)) <= near_thr:
            score += 1
    else:  # SELL
        # Entry dekat resistance di atas
        res = [r for r in resistances if r >= entry_price]
        if res and abs(min(res) - entry_price) <= near_thr:
            score += 1

    return score
