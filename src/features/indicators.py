from __future__ import annotations

import pandas as pd
import numpy as np
import talib


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tambahkan indikator inti untuk:
    - Bias HTF        : EMA50, EMA200
    - Trigger entry  : RSI, MACD
    - Risk management: ATR
    """
    df = df.copy()

    # --- PRICE ARRAYS ---
    close = df["close"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()

    # =====================
    # MOMENTUM INDICATORS
    # =====================
    df["rsi_14"] = talib.RSI(close, timeperiod=14)

    macd, macdsig, macdhist = talib.MACD(
        close,
        fastperiod=12,
        slowperiod=26,
        signalperiod=9
    )
    df["macd"] = macd
    df["macdsignal"] = macdsig
    df["macdhist"] = macdhist

    # =====================
    # TREND INDICATORS
    # =====================
    df["ema_20"] = talib.EMA(close, timeperiod=20)
    df["ema_50"] = talib.EMA(close, timeperiod=50)
    df["ema_200"] = talib.EMA(close, timeperiod=200)

    # =====================
    # VOLATILITY (RISK)
    # =====================
    df["atr_14"] = talib.ATR(
        high,
        low,
        close,
        timeperiod=14
    )

    # =====================
    # OPTIONAL: STRUCTURE FLAGS (buat skripsi)
    # =====================
    df["trend_bull"] = (df["ema_50"] > df["ema_200"]) & (df["close"] > df["ema_200"])
    df["trend_bear"] = (df["ema_50"] < df["ema_200"]) & (df["close"] < df["ema_200"])

    return df
