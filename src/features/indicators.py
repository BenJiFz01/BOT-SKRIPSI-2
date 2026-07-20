"""
indicators.py
=============
Kalkulasi indikator teknikal pada DataFrame OHLCV.

Indikator yang ditambahkan:
    - RSI (14)
    - MACD (12, 26, 9): macd, macdsignal, macdhist
    - EMA 20, 50, 200
    - ATR (14)
    - Golden Cross / Death Cross (EMA50 vs EMA200)
    - EMA Bull/Bear Alignment (EMA20 > EMA50 > EMA200 atau sebaliknya)
    - Trend Bull/Bear
    - RSI Divergence (bullish & bearish)
    - MACD Histogram Divergence (bullish & bearish)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


# ── Swing point detection ─────────────────────────────────────────────

def _swing_lows(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    """Cari indeks swing low pada array."""
    result = []
    for i in range(left, len(series) - right):
        if (all(series[i] < series[i - j] for j in range(1, left + 1)) and
                all(series[i] < series[i + j] for j in range(1, right + 1))):
            result.append(i)
    return result


def _swing_highs(series: np.ndarray, left: int = 3, right: int = 3) -> list[int]:
    """Cari indeks swing high pada array."""
    result = []
    for i in range(left, len(series) - right):
        if (all(series[i] > series[i - j] for j in range(1, left + 1)) and
                all(series[i] > series[i + j] for j in range(1, right + 1))):
            result.append(i)
    return result


# ── Divergence detection ──────────────────────────────────────────────

def _detect_rsi_divergence(
    close:    np.ndarray,
    rsi:      np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Deteksi RSI divergence (bullish & bearish).

    Bullish divergence : harga buat lower low, RSI buat higher low.
    Bearish divergence : harga buat higher high, RSI buat lower high.

    Returns:
        (bull_array, bear_array) — boolean array sepanjang `close`.
    """
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc = close[i - lookback: i + 1]
        wr = rsi[i - lookback: i + 1]
        if np.any(np.isnan(wr)):
            continue

        # Bullish divergence
        pl = _swing_lows(wc, left, right)
        rl = _swing_lows(wr, left, right)
        if len(pl) >= 2 and len(rl) >= 2:
            p1, p2 = pl[-2], pl[-1]
            r1, r2 = rl[-2], rl[-1]
            if wc[p2] < wc[p1] and wr[r2] > wr[r1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        # Bearish divergence
        ph = _swing_highs(wc, left, right)
        rh = _swing_highs(wr, left, right)
        if len(ph) >= 2 and len(rh) >= 2:
            p1, p2 = ph[-2], ph[-1]
            r1, r2 = rh[-2], rh[-1]
            if wc[p2] > wc[p1] and wr[r2] < wr[r1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear


def _detect_macd_divergence(
    close:    np.ndarray,
    macdhist: np.ndarray,
    lookback: int = 50,
    left:     int = 3,
    right:    int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Deteksi MACD Histogram divergence (bullish & bearish).

    Returns:
        (bull_array, bear_array) — boolean array sepanjang `close`.
    """
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc = close[i - lookback: i + 1]
        wm = macdhist[i - lookback: i + 1]
        if np.any(np.isnan(wm)):
            continue

        # Bullish divergence
        pl = _swing_lows(wc, left, right)
        ml = _swing_lows(wm, left, right)
        if len(pl) >= 2 and len(ml) >= 2:
            p1, p2 = pl[-2], pl[-1]
            m1, m2 = ml[-2], ml[-1]
            if wc[p2] < wc[p1] and wm[m2] > wm[m1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        # Bearish divergence
        ph = _swing_highs(wc, left, right)
        mh = _swing_highs(wm, left, right)
        if len(ph) >= 2 and len(mh) >= 2:
            p1, p2 = ph[-2], ph[-1]
            m1, m2 = mh[-2], mh[-1]
            if wc[p2] > wc[p1] and wm[m2] < wm[m1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear


# ── Main function ─────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tambahkan semua kolom indikator teknikal ke DataFrame.

    Input DataFrame harus memiliki kolom: open, high, low, close.

    Returns:
        DataFrame baru dengan kolom indikator tambahan.
    """
    df    = df.copy()
    close = df["close"].astype(float).to_numpy()
    high  = df["high"].astype(float).to_numpy()
    low   = df["low"].astype(float).to_numpy()

    # ── Indikator dasar ───────────────────────────────────────────────
    df["rsi_14"]     = talib.RSI(close, timeperiod=14)
    macd, sig, hist  = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df["macd"]       = macd
    df["macdsignal"] = sig
    df["macdhist"]   = hist
    df["ema_20"]     = talib.EMA(close, timeperiod=20)
    df["ema_50"]     = talib.EMA(close, timeperiod=50)
    df["ema_200"]    = talib.EMA(close, timeperiod=200)
    df["atr_14"]     = talib.ATR(high, low, close, timeperiod=14)

    # ── EMA cross signals ─────────────────────────────────────────────
    ema50  = df["ema_50"].to_numpy()
    ema200 = df["ema_200"].to_numpy()
    gc = np.zeros(len(df), dtype=bool)
    dc = np.zeros(len(df), dtype=bool)
    for i in range(1, len(df)):
        if any(np.isnan([ema50[i], ema200[i], ema50[i - 1], ema200[i - 1]])):
            continue
        if ema50[i] > ema200[i] and ema50[i - 1] <= ema200[i - 1]:
            gc[i] = True
        if ema50[i] < ema200[i] and ema50[i - 1] >= ema200[i - 1]:
            dc[i] = True
    df["golden_cross"] = gc
    df["death_cross"]  = dc

    # ── EMA alignment & trend ─────────────────────────────────────────
    df["ema_bull_align"] = (df["ema_20"] > df["ema_50"]) & (df["ema_50"] > df["ema_200"])
    df["ema_bear_align"] = (df["ema_20"] < df["ema_50"]) & (df["ema_50"] < df["ema_200"])
    df["trend_bull"]     = (df["ema_50"] > df["ema_200"]) & (df["close"] > df["ema_200"])
    df["trend_bear"]     = (df["ema_50"] < df["ema_200"]) & (df["close"] < df["ema_200"])

    # ── Divergence ────────────────────────────────────────────────────
    rsi_bull, rsi_bear   = _detect_rsi_divergence(close, df["rsi_14"].to_numpy())
    macd_bull, macd_bear = _detect_macd_divergence(close, df["macdhist"].to_numpy())

    df["rsi_bull_div"]  = rsi_bull
    df["rsi_bear_div"]  = rsi_bear
    df["macd_bull_div"] = macd_bull
    df["macd_bear_div"] = macd_bear

    return df
