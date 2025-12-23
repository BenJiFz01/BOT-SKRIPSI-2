from __future__ import annotations

import pandas as pd
import talib

# Daftar pattern populer/umum (bullish>0, bearish<0, 0=none)
PATTERN_FUNCS = {
    # Reversal dasar
    "CDLENGULFING": talib.CDLENGULFING,
    "CDLHAMMER": talib.CDLHAMMER,
    "CDLINVERTEDHAMMER": talib.CDLINVERTEDHAMMER,
    "CDLSHOOTINGSTAR": talib.CDLSHOOTINGSTAR,
    "CDLHANGINGMAN": talib.CDLHANGINGMAN,

    # Star patterns
    "CDLMORNINGSTAR": talib.CDLMORNINGSTAR,
    "CDLEVENINGSTAR": talib.CDLEVENINGSTAR,
    "CDLMORNINGDOJISTAR": talib.CDLMORNINGDOJISTAR,
    "CDLEVENINGDOJISTAR": talib.CDLEVENINGDOJISTAR,

    # Doji family
    "CDLDOJI": talib.CDLDOJI,
    "CDLLONGLEGGEDDOJI": talib.CDLLONGLEGGEDDOJI,
    "CDLDRAGONFLYDOJI": talib.CDLDRAGONFLYDOJI,
    "CDLGRAVESTONEDOJI": talib.CDLGRAVESTONEDOJI,

    # Harami
    "CDLHARAMI": talib.CDLHARAMI,
    "CDLHARAMICROSS": talib.CDLHARAMICROSS,

    # Piercing / Dark cloud
    "CDLPIERCING": talib.CDLPIERCING,
    "CDLDARKCLOUDCOVER": talib.CDLDARKCLOUDCOVER,

    # Soldiers / Crows
    "CDL3WHITESOLDIERS": talib.CDL3WHITESOLDIERS,
    "CDL3BLACKCROWS": talib.CDL3BLACKCROWS,

    # Multi-candle reversal
    "CDL3INSIDE": talib.CDL3INSIDE,
    "CDL3OUTSIDE": talib.CDL3OUTSIDE,
    "CDL3LINESTRIKE": talib.CDL3LINESTRIKE,
    "CDL2CROWS": talib.CDL2CROWS,

    # Kicking / Tasuki gap (lebih jarang tapi oke)
    "CDLKICKING": talib.CDLKICKING,
    "CDLTASUKIGAP": talib.CDLTASUKIGAP,

    # Others yang cukup dikenal
    "CDLMARUBOZU": talib.CDLMARUBOZU,
    "CDLSPINNINGTOP": talib.CDLSPINNINGTOP,
}

def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()

    bull_cols = []
    bear_cols = []

    for name, fn in PATTERN_FUNCS.items():
        df[name] = fn(o, h, l, c)
        bull_cols.append((df[name] >= 100).astype(int))
        bear_cols.append((df[name] <= -100).astype(int))

    # agregasi
    df["pattern_bull_count"] = pd.concat(bull_cols, axis=1).sum(axis=1)
    df["pattern_bear_count"] = pd.concat(bear_cols, axis=1).sum(axis=1)
    df["pattern_score"] = df["pattern_bull_count"] - df["pattern_bear_count"]

    return df
