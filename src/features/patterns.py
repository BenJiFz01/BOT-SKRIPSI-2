"""patterns.py — Deteksi candlestick pattern via TA-Lib."""

import pandas as pd
import talib

PATTERN_FUNCS: dict[str, object] = {
    "CDLHAMMER":        talib.CDLHAMMER,
    "CDLINVERTEDHAMMER": talib.CDLINVERTEDHAMMER,
    "CDLENGULFING":     talib.CDLENGULFING,
    "CDLMORNINGSTAR":   talib.CDLMORNINGSTAR,
    "CDLEVENINGSTAR":   talib.CDLEVENINGSTAR,
    "CDLSHOOTINGSTAR":  talib.CDLSHOOTINGSTAR,
    "CDLDOJI":          talib.CDLDOJI,
    "CDLPIERCING":      talib.CDLPIERCING,
    "CDLDARKCLOUDCOVER": talib.CDLDARKCLOUDCOVER,
    "CDLHARAMI":        talib.CDLHARAMI,
    "CDL3WHITESOLDIERS": talib.CDL3WHITESOLDIERS,
    "CDL3BLACKCROWS":   talib.CDL3BLACKCROWS,
    "CDLMARUBOZU":      talib.CDLMARUBOZU,
    "CDLSPINNINGTOP":   talib.CDLSPINNINGTOP,
}

PATTERN_NEUTRAL = {"CDLDOJI", "CDLSPINNINGTOP"}


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan kolom pattern TA-Lib ke DataFrame. Returns DataFrame yang sama."""
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    bull_count = 0
    bear_count = 0

    for name, func in PATTERN_FUNCS.items():
        result = func(o, h, l, c)
        df[name] = result
        if name not in PATTERN_NEUTRAL:
            bull_count += (result > 0).astype(int)
            bear_count += (result < 0).astype(int)

    df["pattern_bull_count"] = bull_count
    df["pattern_bear_count"] = bear_count
    return df
