"""patterns.py — Deteksi 27 candlestick pattern via TA-Lib."""
from __future__ import annotations

import pandas as pd
import talib


PATTERN_FUNCS = {
    "CDLENGULFING":      talib.CDLENGULFING,
    "CDLHAMMER":         talib.CDLHAMMER,
    "CDLINVERTEDHAMMER": talib.CDLINVERTEDHAMMER,
    "CDLSHOOTINGSTAR":   talib.CDLSHOOTINGSTAR,
    "CDLHANGINGMAN":     talib.CDLHANGINGMAN,
    "CDLMORNINGSTAR":     talib.CDLMORNINGSTAR,
    "CDLEVENINGSTAR":     talib.CDLEVENINGSTAR,
    "CDLMORNINGDOJISTAR": talib.CDLMORNINGDOJISTAR,
    "CDLEVENINGDOJISTAR": talib.CDLEVENINGDOJISTAR,
    "CDLDOJI":           talib.CDLDOJI,
    "CDLLONGLEGGEDDOJI": talib.CDLLONGLEGGEDDOJI,
    "CDLDRAGONFLYDOJI":  talib.CDLDRAGONFLYDOJI,
    "CDLGRAVESTONEDOJI": talib.CDLGRAVESTONEDOJI,
    "CDLHARAMI":         talib.CDLHARAMI,
    "CDLHARAMICROSS":    talib.CDLHARAMICROSS,
    "CDLPIERCING":       talib.CDLPIERCING,
    "CDLDARKCLOUDCOVER": talib.CDLDARKCLOUDCOVER,
    "CDL3WHITESOLDIERS": talib.CDL3WHITESOLDIERS,
    "CDL3BLACKCROWS":    talib.CDL3BLACKCROWS,
    "CDL3INSIDE":        talib.CDL3INSIDE,
    "CDL3OUTSIDE":       talib.CDL3OUTSIDE,
    "CDL3LINESTRIKE":    talib.CDL3LINESTRIKE,
    "CDL2CROWS":         talib.CDL2CROWS,
    "CDLKICKING":        talib.CDLKICKING,
    "CDLTASUKIGAP":      talib.CDLTASUKIGAP,
    "CDLMARUBOZU":       talib.CDLMARUBOZU,
    "CDLSPINNINGTOP":    talib.CDLSPINNINGTOP,
}

# Pattern netral — menunjukkan ketidakpastian, tidak masuk bull/bear count
# Tetap dideteksi dan ditampilkan di notif tapi tidak menambah skor
PATTERN_NEUTRAL = {
    "CDLDOJI",
    "CDLLONGLEGGEDDOJI",
    "CDLDRAGONFLYDOJI",
    "CDLGRAVESTONEDOJI",
    "CDLSPINNINGTOP",
    "CDLHARAMI",
    "CDLHARAMICROSS",
}


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan kolom candlestick pattern ke DataFrame. Returns DataFrame baru dengan kolom pattern + agregasi."""
    df = df.copy()
    o  = df["open"].astype(float).to_numpy()
    h  = df["high"].astype(float).to_numpy()
    l  = df["low"].astype(float).to_numpy()
    c  = df["close"].astype(float).to_numpy()

    bull_cols = []
    bear_cols = []

    for name, fn in PATTERN_FUNCS.items():
        df[name] = fn(o, h, l, c)
        if name not in PATTERN_NEUTRAL:
            bull_cols.append((df[name] >= 100).astype(int))
            bear_cols.append((df[name] <= -100).astype(int))

    df["pattern_bull_count"] = pd.concat(bull_cols, axis=1).sum(axis=1) if bull_cols else 0
    df["pattern_bear_count"] = pd.concat(bear_cols, axis=1).sum(axis=1) if bear_cols else 0
    df["pattern_score"]      = df["pattern_bull_count"] - df["pattern_bear_count"]

    return df
