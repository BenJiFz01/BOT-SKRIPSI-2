"""fibonacci.py — Kalkulasi level Fibonacci Retracement dan skor konfluensi."""

import pandas as pd

from src.features.swing_utils import pivot_highs, pivot_lows


FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_STRONG = {0.382, 0.5, 0.618}
FIB_WEAK   = {0.236, 0.786}   # level terlalu lemah, tidak dihitung sebagai confluence

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
    Cari swing TERBARU yang relevan untuk arah sinyal menggunakan pivot point detection.

    BUY  butuh swing UP  (pivot low terbaru → pivot high terbaru setelahnya).
    SELL butuh swing DOWN (pivot high terbaru → pivot low terbaru setelahnya).

    Minimal ukuran swing = 2×ATR agar tidak terlalu kecil.

    Returns (swing_low, swing_high, direction) atau None.
    """
    if len(df) < lookback + 5:
        return None

    direction = direction.upper()
    w = df.iloc[-lookback:].reset_index(drop=True)

    # Ambil ATR untuk filter swing minimum
    atr_val = 0.0
    if "atr_14" in df.columns:
        v = df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            atr_val = float(v)

    # Window pivot — lebih kecil untuk TF kecil agar lebih responsif
    pivot_window = 3 if len(w) < 100 else 5

    p_highs = pivot_highs(w, window=pivot_window)
    p_lows  = pivot_lows(w,  window=pivot_window)

    if not p_highs or not p_lows:
        # Fallback: pakai high/low absolut dari lookback terbaru yang lebih kecil
        w2 = df.iloc[-min(lookback, 50):].copy()
        idx_hi = w2["high"].idxmax()
        idx_lo = w2["low"].idxmin()
        swing_lo  = float(w2.loc[idx_lo, "low"])
        swing_hi  = float(w2.loc[idx_hi, "high"])
        swing_dir = "UP" if idx_lo < idx_hi else "DOWN"
        if direction == "BUY"  and swing_dir != "UP":   return None
        if direction == "SELL" and swing_dir != "DOWN":  return None
        if atr_val > 0 and (swing_hi - swing_lo) < 2.0 * atr_val:
            return None
        return swing_lo, swing_hi, swing_dir

    if direction == "BUY":
        # Swing UP: cari pivot low terbaru, lalu cari pivot high setelahnya
        for lo_idx, lo_val in reversed(p_lows):
            highs_after = [(hi_idx, hi_val) for hi_idx, hi_val in p_highs if hi_idx > lo_idx]
            if not highs_after:
                continue
            hi_idx, hi_val = max(highs_after, key=lambda x: x[1])
            if atr_val > 0 and (hi_val - lo_val) < 2.0 * atr_val:
                continue
            return lo_val, hi_val, "UP"

    elif direction == "SELL":
        # Swing DOWN: cari pivot high terbaru, lalu cari pivot low setelahnya
        for hi_idx, hi_val in reversed(p_highs):
            lows_after = [(lo_idx, lo_val) for lo_idx, lo_val in p_lows if lo_idx > hi_idx]
            if not lows_after:
                continue
            lo_idx, lo_val = min(lows_after, key=lambda x: x[1])
            if atr_val > 0 and (hi_val - lo_val) < 2.0 * atr_val:
                continue
            return lo_val, hi_val, "DOWN"

    return None


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


def _nearest_fib(price: float, levels: dict[str, float]) -> tuple[str, float] | None:
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

    near = _nearest_fib(entry_price, levels)
    if near is None:
        return 0, "FIB_NO_LEVEL"

    name, px = near
    dist = abs(entry_price - px)
    if dist > near_factor * atr:
        return 0, f"FIB_FAR({name}={px:.2f} dist={dist:.1f})"

    try:
        lv_num = float(name.replace("fib_", ""))
        # fib_0 / fib_1 = ujung swing — bukan zona retracement, tidak dihitung
        if lv_num in {0.0, 1.0}:
            return 0, f"FIB_ENDPOINT({name}={px:.2f})"
        # Level lemah tidak dihitung — terlalu sering false signal
        if lv_num in FIB_WEAK:
            return 0, f"FIB_WEAK({name}={px:.2f})"
        if lv_num in FIB_STRONG:
            return 2, f"FIB_STRONG({name}={px:.2f})"
    except ValueError:
        pass

    return 1, f"FIB_NEAR({name}={px:.2f})"
