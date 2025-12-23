from __future__ import annotations
import pandas as pd

def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[float], list[float]]:
    """
    Pivot swing sederhana:
    - swing high jika high lebih besar dari left candle sebelum & right candle sesudah
    - swing low jika low lebih kecil dari left candle sebelum & right candle sesudah
    """
    highs, lows = [], []
    if len(df) < left + right + 5:
        return highs, lows

    h = df["high"].to_list()
    l = df["low"].to_list()

    for i in range(left, len(df) - right):
        is_high = all(h[i] > h[i - j] for j in range(1, left + 1)) and all(h[i] > h[i + j] for j in range(1, right + 1))
        is_low  = all(l[i] < l[i - j] for j in range(1, left + 1)) and all(l[i] < l[i + j] for j in range(1, right + 1))

        if is_high:
            highs.append(float(h[i]))
        if is_low:
            lows.append(float(l[i]))

    return highs, lows

def nearest_level(price: float, levels: list[float]) -> float | None:
    if not levels:
        return None
    return min(levels, key=lambda x: abs(x - price))

def in_zone(price: float, level: float, tolerance: float) -> bool:
    return abs(price - level) <= tolerance
