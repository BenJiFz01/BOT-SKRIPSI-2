from __future__ import annotations
import pandas as pd

def detect_base_zone(df: pd.DataFrame, window: int = 8, max_range_ratio: float = 0.003) -> tuple[float, float] | None:
    """
    Cari "base" terakhir: range (high-low) kecil dalam window terakhir.
    max_range_ratio contoh 0.003 = 0.3% dari harga.
    Return: (zone_low, zone_high)
    """
    if len(df) < window + 5:
        return None

    w = df.iloc[-window:].copy()
    zone_high = float(w["high"].max())
    zone_low = float(w["low"].min())

    mid = (zone_high + zone_low) / 2.0
    if mid <= 0:
        return None

    rng_ratio = (zone_high - zone_low) / mid
    if rng_ratio <= max_range_ratio:
        return zone_low, zone_high

    return None

def in_zone(price: float, zone_low: float, zone_high: float, tolerance: float = 0.0) -> bool:
    return (zone_low - tolerance) <= price <= (zone_high + tolerance)
