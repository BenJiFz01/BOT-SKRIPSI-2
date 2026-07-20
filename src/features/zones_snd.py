"""
zones_snd.py
============
Deteksi zona Supply & Demand berbasis "base zone" (area konsolidasi).

Logika:
    Base zone adalah area di mana candle bergerak dalam range sempit
    sebelum terjadi pergerakan impulsif — ini area akumulasi/distribusi
    institusional (Supply/Demand zone).

    Skor +1 jika entry berada di dalam zona.
    Skor +2 jika entry di zona dan di sisi yang lebih dalam (lebih value).
"""
from __future__ import annotations

import pandas as pd


def detect_base_zone(
    df:              pd.DataFrame,
    window:          int   = 8,
    max_range_ratio: float = 0.003,
) -> tuple[float, float] | None:
    """
    Deteksi base zone (zona konsolidasi sempit) di `window` candle terakhir.

    Args:
        window:          Jumlah candle yang diperiksa.
        max_range_ratio: Batas rasio range/midprice agar dianggap "sempit".

    Returns:
        (zone_low, zone_high) atau None jika tidak ada zona.
    """
    if len(df) < window + 5:
        return None

    w   = df.iloc[-window:]
    zh  = float(w["high"].max())
    zl  = float(w["low"].min())
    mid = (zh + zl) / 2.0

    if mid <= 0 or (zh - zl) / mid > max_range_ratio:
        return None

    return zl, zh


def snd_confluence_score(
    direction:       str,
    entry_price:     float,
    df:              pd.DataFrame,
    atr:             float,
    window:          int   = 8,
    max_range_ratio: float = 0.003,
    near_factor:     float = 0.5,
) -> tuple[int, str]:
    """
    Hitung skor konfluensi Supply & Demand zone (0, 1, atau 2).

    Skor:
        0 = tidak ada zona atau entry jauh dari zona
        1 = entry di dalam zona
        2 = entry di dalam zona DAN di sisi yang lebih dalam (lebih value)

    Returns:
        (score, label) contoh: (2, "SND_DEMAND(3308.50-3313.00)")
    """
    if atr <= 0:
        return 0, "SND_SKIP"

    recent = df.iloc[-window * 3:] if len(df) > window * 3 else df
    zone   = detect_base_zone(recent, window, max_range_ratio)

    if zone is None:
        return 0, "SND_NO_ZONE"

    zl, zh    = zone
    tolerance = near_factor * atr

    if not ((zl - tolerance) <= entry_price <= (zh + tolerance)):
        return 0, f"SND_FAR({zl:.2f}-{zh:.2f})"

    mid   = (zl + zh) / 2.0
    score = 1

    # Skor lebih tinggi jika entry di sisi yang lebih "value"
    if (direction.upper() == "BUY"  and mid < entry_price) or \
       (direction.upper() == "SELL" and mid > entry_price):
        score = 2

    label = "SND_DEMAND" if direction.upper() == "BUY" else "SND_SUPPLY"
    return score, f"{label}({zl:.2f}-{zh:.2f})"
