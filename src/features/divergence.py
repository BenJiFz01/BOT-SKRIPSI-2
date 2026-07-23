"""divergence.py — Deteksi RSI dan MACD Histogram divergence."""
from __future__ import annotations

import numpy as np


def _swing_lows(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    return [
        i for i in range(left, len(series) - right)
        if all(series[i] < series[i - j] for j in range(1, left + 1))
        and all(series[i] < series[i + j] for j in range(1, right + 1))
    ]


def _swing_highs(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    return [
        i for i in range(left, len(series) - right)
        if all(series[i] > series[i - j] for j in range(1, left + 1))
        and all(series[i] > series[i + j] for j in range(1, right + 1))
    ]


def detect_rsi_divergence(
    close:    np.ndarray,
    rsi:      np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Deteksi RSI divergence bullish dan bearish. Returns (bull_array, bear_array)."""
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc, wr = close[i - lookback: i + 1], rsi[i - lookback: i + 1]
        if np.any(np.isnan(wr)):
            continue

        pl, rl = _swing_lows(wc, left, right), _swing_lows(wr, left, right)
        if len(pl) >= 2 and len(rl) >= 2:
            p1, p2, r1, r2 = pl[-2], pl[-1], rl[-2], rl[-1]
            if wc[p2] < wc[p1] and wr[r2] > wr[r1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        ph, rh = _swing_highs(wc, left, right), _swing_highs(wr, left, right)
        if len(ph) >= 2 and len(rh) >= 2:
            p1, p2, r1, r2 = ph[-2], ph[-1], rh[-2], rh[-1]
            if wc[p2] > wc[p1] and wr[r2] < wr[r1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear


def detect_macd_divergence(
    close:    np.ndarray,
    macdhist: np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Deteksi MACD Histogram divergence bullish dan bearish. Returns (bull_array, bear_array)."""
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc, wm = close[i - lookback: i + 1], macdhist[i - lookback: i + 1]
        if np.any(np.isnan(wm)):
            continue

        pl, ml = _swing_lows(wc, left, right), _swing_lows(wm, left, right)
        if len(pl) >= 2 and len(ml) >= 2:
            p1, p2, m1, m2 = pl[-2], pl[-1], ml[-2], ml[-1]
            if wc[p2] < wc[p1] and wm[m2] > wm[m1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        ph, mh = _swing_highs(wc, left, right), _swing_highs(wm, left, right)
        if len(ph) >= 2 and len(mh) >= 2:
            p1, p2, m1, m2 = ph[-2], ph[-1], mh[-2], mh[-1]
            if wc[p2] > wc[p1] and wm[m2] < wm[m1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear
