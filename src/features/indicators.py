"""indicators.py — Kalkulasi indikator teknikal pada DataFrame OHLCV."""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib

from src.features.divergence import detect_rsi_divergence, detect_macd_divergence


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan RSI, MACD, EMA 20/50/200, ATR, EMA signals, dan divergence ke DataFrame."""
    df    = df.copy()
    close = df["close"].astype(float).to_numpy()
    high  = df["high"].astype(float).to_numpy()
    low   = df["low"].astype(float).to_numpy()

    # Indikator dasar
    df["rsi_14"]     = talib.RSI(close, timeperiod=14)
    macd, sig, hist  = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df["macd"]       = macd
    df["macdsignal"] = sig
    df["macdhist"]   = hist
    df["ema_20"]     = talib.EMA(close, timeperiod=20)
    df["ema_50"]     = talib.EMA(close, timeperiod=50)
    df["ema_200"]    = talib.EMA(close, timeperiod=200)
    df["atr_14"]     = talib.ATR(high, low, close, timeperiod=14)

    # EMA cross (golden/death cross)
    ema50, ema200 = df["ema_50"].to_numpy(), df["ema_200"].to_numpy()
    gc = np.zeros(len(df), dtype=bool)
    dc = np.zeros(len(df), dtype=bool)
    for i in range(1, len(df)):
        if any(np.isnan([ema50[i], ema200[i], ema50[i-1], ema200[i-1]])):
            continue
        if ema50[i] > ema200[i] and ema50[i-1] <= ema200[i-1]:
            gc[i] = True
        if ema50[i] < ema200[i] and ema50[i-1] >= ema200[i-1]:
            dc[i] = True
    df["golden_cross"] = gc
    df["death_cross"]  = dc

    # EMA alignment dan trend
    df["ema_bull_align"] = (df["ema_20"] > df["ema_50"]) & (df["ema_50"] > df["ema_200"])
    df["ema_bear_align"] = (df["ema_20"] < df["ema_50"]) & (df["ema_50"] < df["ema_200"])
    df["trend_bull"]     = (df["ema_50"] > df["ema_200"]) & (df["close"] > df["ema_200"])
    df["trend_bear"]     = (df["ema_50"] < df["ema_200"]) & (df["close"] < df["ema_200"])

    # Divergence
    rsi_bull, rsi_bear   = detect_rsi_divergence(close, df["rsi_14"].to_numpy())
    macd_bull, macd_bear = detect_macd_divergence(close, df["macdhist"].to_numpy())
    df["rsi_bull_div"]   = rsi_bull
    df["rsi_bear_div"]   = rsi_bear
    df["macd_bull_div"]  = macd_bull
    df["macd_bear_div"]  = macd_bear

    return df
