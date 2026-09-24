import numpy as np
import pandas as pd
import talib

PATTERN_FUNCS: dict[str, object] = {
    "CDLHAMMER":         talib.CDLHAMMER,
    "CDLINVERTEDHAMMER": talib.CDLINVERTEDHAMMER,
    "CDLENGULFING":      talib.CDLENGULFING,
    "CDLMORNINGSTAR":    talib.CDLMORNINGSTAR,
    "CDLEVENINGSTAR":    talib.CDLEVENINGSTAR,
    "CDLSHOOTINGSTAR":   talib.CDLSHOOTINGSTAR,
    "CDLDOJI":           talib.CDLDOJI,
    "CDLPIERCING":       talib.CDLPIERCING,
    "CDLDARKCLOUDCOVER": talib.CDLDARKCLOUDCOVER,
    "CDLHARAMI":         talib.CDLHARAMI,
    "CDL3WHITESOLDIERS": talib.CDL3WHITESOLDIERS,
    "CDL3BLACKCROWS":    talib.CDL3BLACKCROWS,
    "CDLMARUBOZU":       talib.CDLMARUBOZU,
    "CDLSPINNINGTOP":    talib.CDLSPINNINGTOP,
}

PATTERN_NEUTRAL = {"CDLDOJI", "CDLSPINNINGTOP"}
# Filter body-size
_MIN_BODY_RATIO   = 0.40   
_BODY_LOOKBACK    = 10    
_SKIP_BODY_FILTER = {"CDLDOJI", "CDLSPINNINGTOP"} 


def _body_size_ok(o: np.ndarray, c: np.ndarray) -> np.ndarray:
    body     = np.abs(c - o)
    avg_body = (
        pd.Series(body)
        .rolling(_BODY_LOOKBACK, min_periods=1)
        .mean()
        .shift(1)
        .to_numpy()
    )
    with np.errstate(invalid="ignore"):
        ok = body >= (_MIN_BODY_RATIO * avg_body)
    ok = np.where(np.isnan(avg_body), True, ok)
    return ok

def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    body_ok    = _body_size_ok(o, c)
    bull_count = 0
    bear_count = 0

    for name, func in PATTERN_FUNCS.items():
        result = func(o, h, l, c)

        if name not in _SKIP_BODY_FILTER:
            result = np.where(body_ok, result, 0)

        df[name] = result

        if name not in PATTERN_NEUTRAL:
            bull_count += (result > 0).astype(int)
            bear_count += (result < 0).astype(int)

    df["pattern_bull_count"] = bull_count
    df["pattern_bear_count"] = bear_count
    return df
