"""fibonacci.py — Kalkulasi level Fibonacci Retracement dan skor konfluensi."""
from __future__ import annotations

import pandas as pd


FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_STRONG = {0.382, 0.5, 0.618}
FIB_WEAK   = {0.236, 0.786}  # level terlalu lemah, tidak dihitung sebagai confluence

_FIB_LOOKBACK: dict[str, int] = {
    "M1":  300,
    "M5":  200,
    "M15": 150,
    "M30": 120,
    "H1":  120,
    "H4":  80,
    "D1":  60,
    "W1":  40,
}
_FIB_LOOKBACK_DEFAULT = 100


def fib_lookback_for_tf(tf: str) -> int:
    """Kembalikan lookback bar yang sesuai untuk TF tertentu."""
    return _FIB_LOOKBACK.get(tf.upper(), _FIB_LOOKBACK_DEFAULT)


def last_swing(
    df:        pd.DataFrame,
    lookback:  int = 100,
    direction: str = "UP",
) -> tuple[float, float, str] | None:
    """
    Cari swing yang relevan untuk arah sinyal.
    BUY butuh swing UP (low sebelum high), SELL butuh swing DOWN (high sebelum low).
    Returns (swing_low, swing_high, direction) atau None.
    """
    if len(df) < lookback + 5:
        return None

    w        = df.iloc[-lookback:].copy()
    idx_hi   = w["high"].idxmax()
    idx_lo   = w["low"].idxmin()
    swing_lo = float(w.loc[idx_lo, "low"])
    swing_hi = float(w.loc[idx_hi, "high"])
    swing_dir = "UP" if idx_lo < idx_hi else "DOWN"

    direction = direction.upper()
    if direction == "BUY"  and swing_dir != "UP":
        return None
    if direction == "SELL" and swing_dir != "DOWN":
        return None

    atr_col = df["atr_14"].iloc[-2] if "atr_14" in df.columns else None
    if atr_col is not None and pd.notna(atr_col) and float(atr_col) > 0:
        if (swing_hi - swing_lo) < 2.0 * float(atr_col):
            return None

    return swing_lo, swing_hi, swing_dir


def fib_levels(swing_low: float, swing_high: float, direction: str) -> dict[str, float]:
    """
    Hitung harga di setiap level Fibonacci retracement.
    UP: level dari high ke bawah (support BUY). DOWN: dari low ke atas (resistance SELL).
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


def nearest_fib(price: float, levels: dict[str, float]) -> tuple[str, float] | None:
    """Kembalikan nama dan harga level Fibonacci terdekat dengan price."""
    if not levels:
        return None
    key = min(levels.keys(), key=lambda k: abs(levels[k] - price))
    return key, float(levels[key])


def fib_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    lookback:    int   = 0,
    tf:          str   = "",
    near_factor: float = 0.75,
) -> tuple[int, str]:
    """
    Skor konfluensi Fibonacci (0, 1, atau 2).
    +2 untuk level kuat (38.2/50/61.8%), +1 lainnya.
    Lookback: otomatis dari tf → lookback eksplisit → default 100.
    """
    if atr <= 0:
        return 0, "FIB_SKIP"

    # Pilih lookback
    if tf:
        lb = fib_lookback_for_tf(tf)
    elif lookback > 0:
        lb = lookback
    else:
        lb = _FIB_LOOKBACK_DEFAULT

    sw = last_swing(df, lb, direction=direction)
    if sw is None:
        return 0, "FIB_NO_SWING"

    levels = fib_levels(*sw[:2], sw[2])
    if not levels:
        return 0, "FIB_NO_LEVEL"

    near = nearest_fib(entry_price, levels)
    if near is None:
        return 0, "FIB_NO_LEVEL"

    name, px = near
    dist = abs(entry_price - px)
    if dist > near_factor * atr:
        return 0, f"FIB_FAR({name}={px:.2f} dist={dist:.1f})"

    try:
        lv_num = float(name.replace("fib_", ""))
        # Level lemah (0.236, 0.786) tidak dihitung — terlalu sering false
        if lv_num in FIB_WEAK:
            return 0, f"FIB_WEAK({name}={px:.2f})"
        if lv_num in FIB_STRONG:
            return 2, f"FIB_STRONG({name}={px:.2f})"
    except ValueError:
        pass

    return 1, f"FIB_NEAR({name}={px:.2f})"
