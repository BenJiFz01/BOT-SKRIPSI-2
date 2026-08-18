"""divergence.py — Deteksi RSI dan MACD Histogram divergence."""

import numpy as np

from src.features.swing_utils import swing_highs_idx, swing_lows_idx


def _detect_divergence(
    close:     np.ndarray,
    indicator: np.ndarray,
    lookback:  int = 50,
    left:      int = 3,
    right:     int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Deteksi divergence bullish dan bearish secara generik.

    Bullish divergence : harga membuat lower low, indikator membuat higher low.
    Bearish divergence : harga membuat higher high, indikator membuat lower high.

    Returns (bull_array, bear_array) — boolean array sepanjang `close`.
    """
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc = close[i - lookback: i + 1]
        wi = indicator[i - lookback: i + 1]
        if np.any(np.isnan(wi)):
            continue

        # Bullish: price lower low + indicator higher low
        pl = swing_lows_idx(wc, left, right)
        il = swing_lows_idx(wi, left, right)
        if len(pl) >= 2 and len(il) >= 2:
            p1, p2 = pl[-2], pl[-1]
            r1, r2 = il[-2], il[-1]
            if wc[p2] < wc[p1] and wi[r2] > wi[r1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        # Bearish: price higher high + indicator lower high
        ph = swing_highs_idx(wc, left, right)
        ih = swing_highs_idx(wi, left, right)
        if len(ph) >= 2 and len(ih) >= 2:
            p1, p2 = ph[-2], ph[-1]
            r1, r2 = ih[-2], ih[-1]
            if wc[p2] > wc[p1] and wi[r2] < wi[r1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear


def detect_rsi_divergence(
    close:    np.ndarray,
    rsi:      np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Deteksi RSI divergence bullish dan bearish. Returns (bull_array, bear_array)."""
    return _detect_divergence(close, rsi, lookback, left, right)


def detect_macd_divergence(
    close:    np.ndarray,
    macdhist: np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Deteksi MACD Histogram divergence bullish dan bearish. Returns (bull_array, bear_array)."""
    return _detect_divergence(close, macdhist, lookback, left, right)
