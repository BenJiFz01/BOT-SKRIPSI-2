"""zones_snd.py — Deteksi zona Supply & Demand berbasis base zone."""
from __future__ import annotations

import pandas as pd


_WINDOWS = [10, 15, 20, 30]
_MAX_RANGE_BY_WINDOW = {10: 0.005, 15: 0.006, 20: 0.008, 30: 0.010}


def detect_base_zone(
    df:              pd.DataFrame,
    window:          int   = 20,
    max_range_ratio: float = 0.008,
) -> tuple[float, float] | None:
    """Deteksi zona konsolidasi di window candle terakhir. Returns (zone_low, zone_high) atau None."""
    if len(df) < window + 5:
        return None
    w   = df.iloc[-window:]
    zh  = float(w["high"].max())
    zl  = float(w["low"].min())
    mid = (zh + zl) / 2.0
    if mid <= 0 or (zh - zl) / mid > max_range_ratio:
        return None
    return zl, zh


def detect_base_zone_multi(df: pd.DataFrame) -> tuple[float, float] | None:
    """Coba beberapa ukuran window, kembalikan zona pertama yang ditemukan."""
    for w in _WINDOWS:
        zone = detect_base_zone(df, window=w, max_range_ratio=_MAX_RANGE_BY_WINDOW[w])
        if zone is not None:
            return zone
    return None


def snd_confluence_score(
    direction:       str,
    entry_price:     float,
    df:              pd.DataFrame,
    atr:             float,
    window:          int   = 20,
    max_range_ratio: float = 0.008,
    near_factor:     float = 0.5,
    use_multi:       bool  = True,
) -> tuple[int, str]:
    """
    Skor konfluensi Supply & Demand zone (0, 1, atau 2).
    +1 entry di dalam/dekat zona. +2 jika di sisi value (BUY=bawah mid, SELL=atas mid).
    """
    if atr <= 0:
        return 0, "SND_SKIP"

    zone = detect_base_zone_multi(df) if use_multi else detect_base_zone(df, window, max_range_ratio)
    if zone is None:
        return 0, "SND_NO_ZONE"

    zl, zh    = zone
    tolerance = near_factor * atr
    if not ((zl - tolerance) <= entry_price <= (zh + tolerance)):
        return 0, f"SND_FAR({zl:.2f}-{zh:.2f})"

    mid   = (zl + zh) / 2.0
    score = 1
    if (direction.upper() == "BUY" and entry_price <= mid) or \
       (direction.upper() == "SELL" and entry_price >= mid):
        score = 2

    label = "SND_DEMAND" if direction.upper() == "BUY" else "SND_SUPPLY"
    return score, f"{label}({zl:.2f}-{zh:.2f})"
