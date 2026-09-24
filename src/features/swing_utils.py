"""swing_utils.py — Fungsi swing high/low terpadu untuk seluruh engine."""

import numpy as np
import pandas as pd


# Array-based — dipakai divergence.py (bekerja di atas numpy array).

def swing_lows_idx(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    """
    Kembalikan daftar indeks swing low dari numpy array.
    Swing low = nilai lebih kecil dari semua `left` nilai sebelum dan `right` nilai sesudahnya.
    """
    return [
        i for i in range(left, len(series) - right)
        if all(series[i] < series[i - j] for j in range(1, left + 1))
        and all(series[i] < series[i + j] for j in range(1, right + 1))
    ]


def swing_highs_idx(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    """
    Kembalikan daftar indeks swing high dari numpy array.
    Swing high = nilai lebih besar dari semua `left` nilai sebelum dan `right` nilai sesudahnya.
    """
    return [
        i for i in range(left, len(series) - right)
        if all(series[i] > series[i - j] for j in range(1, left + 1))
        and all(series[i] > series[i + j] for j in range(1, right + 1))
    ]


# DataFrame-based (pivot) — dipakai fibonacci.py untuk pencarian swing (index, harga).

def pivot_highs(df: pd.DataFrame, window: int = 3) -> list[tuple[int, float]]:
    """Cari pivot high dari DataFrame OHLC.

    Pakai operator strict (>) — mencegah dobel-hit di candle dengan high sama persis,
    konsisten dengan swing_high_prices() dan fungsi swing lainnya di file ini.
    Returns: list of (bar_index, high_price) diurutkan ascending.
    """
    highs = df["high"].values
    result = []
    for i in range(window, len(highs) - window):
        if all(highs[i] > highs[i - j] for j in range(1, window + 1)) and \
           all(highs[i] > highs[i + j] for j in range(1, window + 1)):
            result.append((i, float(highs[i])))
    return result


def pivot_lows(df: pd.DataFrame, window: int = 3) -> list[tuple[int, float]]:
    """Cari pivot low dari DataFrame OHLC.

    Pakai operator strict (<) — konsisten dengan swing_low_prices().
    Returns: list of (bar_index, low_price) diurutkan ascending.
    """
    lows = df["low"].values
    result = []
    for i in range(window, len(lows) - window):
        if all(lows[i] < lows[i - j] for j in range(1, window + 1)) and \
           all(lows[i] < lows[i + j] for j in range(1, window + 1)):
            result.append((i, float(lows[i])))
    return result


# Price-list — dipakai zones_snr.py untuk S/R clustering.

def swing_high_prices(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[float]:
    """
    Kembalikan list harga swing high dari DataFrame OHLC.
    Dioptimasi untuk S/R detection (butuh nilai harga, bukan indeks).
    """
    if len(df) < left + right + 5:
        return []
    h = df["high"].to_numpy(dtype=float)
    result = []
    for i in range(left, len(df) - right):
        if all(h[i] > h[i - j] for j in range(1, left + 1)) and \
           all(h[i] > h[i + j] for j in range(1, right + 1)):
            result.append(float(h[i]))
    return result


def swing_low_prices(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[float]:
    """
    Kembalikan list harga swing low dari DataFrame OHLC.
    Dioptimasi untuk S/R detection (butuh nilai harga, bukan indeks).
    """
    if len(df) < left + right + 5:
        return []
    lo = df["low"].to_numpy(dtype=float)
    result = []
    for i in range(left, len(lo) - right):
        if all(lo[i] < lo[i - j] for j in range(1, left + 1)) and \
           all(lo[i] < lo[i + j] for j in range(1, right + 1)):
            result.append(float(lo[i]))
    return result


# Idx+Price — dipakai zones_snr.py untuk menghitung age_bars.
# Tidak mengganti swing_high_prices/low_prices agar tidak break caller lama.

def swing_high_idx_prices(
    df: pd.DataFrame, left: int = 3, right: int = 3
) -> list[tuple[int, float]]:
    """Kembalikan list (bar_index, price) swing high. bar_index = posisi dalam df."""
    if len(df) < left + right + 5:
        return []
    h = df["high"].to_numpy(dtype=float)
    result: list[tuple[int, float]] = []
    for i in range(left, len(df) - right):
        if all(h[i] > h[i - j] for j in range(1, left + 1)) and \
           all(h[i] > h[i + j] for j in range(1, right + 1)):
            result.append((i, float(h[i])))
    return result


def swing_low_idx_prices(
    df: pd.DataFrame, left: int = 3, right: int = 3
) -> list[tuple[int, float]]:
    """Kembalikan list (bar_index, price) swing low. bar_index = posisi dalam df."""
    if len(df) < left + right + 5:
        return []
    lo = df["low"].to_numpy(dtype=float)
    result: list[tuple[int, float]] = []
    for i in range(left, len(lo) - right):
        if all(lo[i] < lo[i - j] for j in range(1, left + 1)) and \
           all(lo[i] < lo[i + j] for j in range(1, right + 1)):
            result.append((i, float(lo[i])))
    return result
