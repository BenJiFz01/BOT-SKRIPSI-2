"""
fibonacci.py
============
Kalkulasi level Fibonacci Retracement dan skor konfluensi.

Logika:
    1. Cari swing high & low dalam lookback candle terakhir.
    2. Hitung level retracement (23.6%, 38.2%, 50%, 61.8%, 78.6%).
    3. Cek apakah harga entry berada dekat salah satu level.
    4. Level kuat (38.2%, 50%, 61.8%) memberi skor +2, level lainnya +1.
"""
from __future__ import annotations

import pandas as pd


FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_STRONG = {0.382, 0.5, 0.618}


def last_swing(
    df:       pd.DataFrame,
    lookback: int = 80,
) -> tuple[float, float, str] | None:
    """
    Cari swing high dan swing low terakhir dalam `lookback` candle.

    Returns:
        (swing_low, swing_high, direction) atau None jika data tidak cukup.
        direction = "UP" jika swing low lebih dulu, "DOWN" jika swing high lebih dulu.
    """
    if len(df) < lookback + 5:
        return None

    w       = df.iloc[-lookback:].copy()
    idx_hi  = w["high"].idxmax()
    idx_lo  = w["low"].idxmin()

    return (
        float(w.loc[idx_lo, "low"]),
        float(w.loc[idx_hi, "high"]),
        "UP" if idx_lo < idx_hi else "DOWN",
    )


def fib_levels(
    swing_low:  float,
    swing_high: float,
    direction:  str,
) -> dict[str, float]:
    """
    Hitung harga di setiap level Fibonacci.

    Args:
        direction: "UP" = retracement dari atas ke bawah,
                   "DOWN" = retracement dari bawah ke atas.

    Returns:
        Dict nama_level -> harga, contoh: {"fib_0.618": 3311.50, ...}
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    levels: dict[str, float] = {}
    if direction == "UP":
        for lv in FIB_LEVELS:
            levels[f"fib_{lv}"] = swing_high - diff * lv
        levels["fib_0"] = swing_high
        levels["fib_1"] = swing_low
    else:
        for lv in FIB_LEVELS:
            levels[f"fib_{lv}"] = swing_low + diff * lv
        levels["fib_0"] = swing_low
        levels["fib_1"] = swing_high

    return levels


def nearest_fib(
    price:  float,
    levels: dict[str, float],
) -> tuple[str, float] | None:
    """Kembalikan nama dan harga level Fibonacci yang paling dekat dengan `price`."""
    if not levels:
        return None
    key = min(levels.keys(), key=lambda k: abs(levels[k] - price))
    return key, float(levels[key])


def fib_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    lookback:    int   = 80,
    near_factor: float = 0.5,
) -> tuple[int, str]:
    """
    Hitung skor konfluensi Fibonacci (0, 1, atau 2).

    Skor:
        0 = entry jauh dari level Fibonacci
        1 = dekat level biasa (23.6%, 78.6%)
        2 = dekat level kuat (38.2%, 50%, 61.8%)

    Args:
        near_factor: Threshold kedekatan = near_factor * ATR.

    Returns:
        (score, label) contoh: (2, "FIB_STRONG(fib_0.618=3311.50)")
    """
    if atr <= 0:
        return 0, "FIB_SKIP"

    sw = last_swing(df, lookback)
    if sw is None:
        return 0, "FIB_NO_SWING"

    levels = fib_levels(*sw[:2], sw[2])
    near   = nearest_fib(entry_price, levels)
    if near is None:
        return 0, "FIB_NO_LEVEL"

    name, px = near
    if abs(entry_price - px) > near_factor * atr:
        return 0, f"FIB_FAR({name}={px:.2f})"

    try:
        lv_num = float(name.replace("fib_", ""))
        if lv_num in FIB_STRONG:
            return 2, f"FIB_STRONG({name}={px:.2f})"
    except ValueError:
        pass

    return 1, f"FIB_NEAR({name}={px:.2f})"
