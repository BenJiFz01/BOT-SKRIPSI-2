"""indicators.py — Tambahkan semua indikator teknikal ke DataFrame OHLC."""

import numpy as np
import pandas as pd
import talib

from src.features.divergence import detect_macd_divergence, detect_rsi_divergence


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Hitung dan tambahkan kolom indikator ke DataFrame. Returns DataFrame yang sama (in-place)."""
    c = df["close"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)

    df["ema_20"]  = talib.EMA(c, timeperiod=20)
    df["ema_50"]  = talib.EMA(c, timeperiod=50)
    df["ema_200"] = talib.EMA(c, timeperiod=200)
    df["rsi_14"]  = talib.RSI(c, timeperiod=14)
    df["atr_14"]  = talib.ATR(h, l, c, timeperiod=14)

    macd, signal, hist = talib.MACD(c, fastperiod=12, slowperiod=26, signalperiod=9)
    df["macd"]     = macd
    df["signal"]   = signal
    df["macdhist"] = hist

    rsi = df["rsi_14"].to_numpy(dtype=float)
    df["rsi_bull_div"], df["rsi_bear_div"] = detect_rsi_divergence(c, rsi)
    df["macd_bull_div"], df["macd_bear_div"] = detect_macd_divergence(c, hist)

    # EMA cross (golden/death cross)
    ema50  = df["ema_50"].to_numpy(dtype=float)
    ema200 = df["ema_200"].to_numpy(dtype=float)
    golden = np.zeros(len(df), dtype=bool)
    death  = np.zeros(len(df), dtype=bool)
    for i in range(1, len(df)):
        if np.isnan(ema50[i]) or np.isnan(ema200[i]):
            continue
        if ema50[i] > ema200[i] and ema50[i - 1] <= ema200[i - 1]:
            golden[i] = True
        elif ema50[i] < ema200[i] and ema50[i - 1] >= ema200[i - 1]:
            death[i] = True
    df["golden_cross"] = golden
    df["death_cross"]  = death

    return df
