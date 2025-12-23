from __future__ import annotations
import pandas as pd

FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

def last_swing(df: pd.DataFrame, lookback: int = 80) -> tuple[float, float, str] | None:
    """
    Ambil swing terakhir secara sederhana:
    - cari high & low pada window lookback
    - tentukan arah swing berdasarkan mana yang terjadi terakhir
    Return: (swing_low, swing_high, direction) direction in {"UP", "DOWN"}
    """
    if len(df) < lookback + 5:
        return None

    w = df.iloc[-lookback:].copy()
    idx_high = w["high"].idxmax()
    idx_low = w["low"].idxmin()

    swing_high = float(w.loc[idx_high, "high"])
    swing_low = float(w.loc[idx_low, "low"])

    # arah swing ditentukan dari urutan kejadian low/high
    direction = "UP" if idx_low < idx_high else "DOWN"
    return swing_low, swing_high, direction

def fib_levels(swing_low: float, swing_high: float, direction: str) -> dict[str, float]:
    """
    Untuk swing UP: fib retracement dihitung dari high turun ke low
    Untuk swing DOWN: fib retracement dihitung dari low naik ke high
    """
    diff = swing_high - swing_low
    levels = {}

    if diff <= 0:
        return levels

    if direction == "UP":
        # retracement dari swing_high turun
        for lv in FIB_LEVELS:
            levels[f"fib_{lv}"] = swing_high - diff * lv
        levels["fib_0"] = swing_high
        levels["fib_1"] = swing_low
    else:
        # retracement dari swing_low naik
        for lv in FIB_LEVELS:
            levels[f"fib_{lv}"] = swing_low + diff * lv
        levels["fib_0"] = swing_low
        levels["fib_1"] = swing_high

    return levels

def nearest_fib(price: float, levels: dict[str, float]) -> tuple[str, float] | None:
    if not levels:
        return None
    k = min(levels.keys(), key=lambda x: abs(levels[x] - price))
    return k, float(levels[k])
