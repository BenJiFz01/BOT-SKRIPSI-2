"""swing_utils.py — Deteksi swing point terpusat.

Sebelumnya duplikat di:
  - divergence.py  : _swing_lows / _swing_highs (array numpy)
  - fibonacci.py   : _find_pivot_highs / _find_pivot_lows (DataFrame)
  - zones_snr.py   : swing_points (DataFrame → list[float])

Modul ini menyediakan satu implementasi tunggal untuk tiap kebutuhan.
"""

import numpy as np
import pandas as pd


# ── Array-based (numpy) ──────────────────────────────────────────────────────
# Digunakan oleh divergence.py — bekerja di atas numpy array.

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


# ── DataFrame-based (pivot) ──────────────────────────────────────────────────
# Digunakan oleh fibonacci.py — kembalikan (index, harga) untuk pencarian swing.

def pivot_highs(df: pd.DataFrame, window: int = 3) -> list[tuple[int, float]]:
    """
    Cari pivot high dari DataFrame OHLC.
    Returns: list of (bar_index, high_price) diurutkan ascending.
    """
    highs = df["high"].values
    result = []
    for i in range(window, len(highs) - window):
        if all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
            result.append((i, float(highs[i])))
    return result


def pivot_lows(df: pd.DataFrame, window: int = 3) -> list[tuple[int, float]]:
    """
    Cari pivot low dari DataFrame OHLC.
    Returns: list of (bar_index, low_price) diurutkan ascending.
    """
    lows = df["low"].values
    result = []
    for i in range(window, len(lows) - window):
        if all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
            result.append((i, float(lows[i])))
    return result


# ── Price-list (S/R clustering) ───────────────────────────────────────────────
# Digunakan oleh zones_snr.py — kembalikan list harga swing untuk clustering.

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
