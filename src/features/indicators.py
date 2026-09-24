"""indicators.py — Tambahkan indikator teknikal ke DataFrame OHLCV.

EMA/MA/MACD disesuaikan per TF; nama kolom tetap (ema_20, ema_50, ema_200, macd).
Fix 2026-09-17: D1 lama (50,200,200) → ema_50 == ema_200 alias identik sehingga
_bias_from_tf selalu NEUTRAL (D1 tak pernah ikut vote bias).
"""
import pandas as pd
import talib

from src.features.divergence import detect_macd_divergence, detect_rsi_divergence


_TF_IND_CONFIG: dict[str, tuple[int, int, int, int, int, int]] = {
    "M5":  (9,  21,  55,  8, 17, 9),
    "M15": (12, 34, 100,  8, 17, 9),
    "H1":  (21, 50, 100, 12, 26, 9),
    "H4":  (21, 55, 200, 12, 26, 9),
    "D1":  (50, 100, 200, 12, 26, 9),
}
_DEFAULT_CONFIG: tuple[int, int, int, int, int, int] = (20, 50, 200, 12, 26, 9)


def add_indicators(df: pd.DataFrame, tf: str = "") -> pd.DataFrame:
    tf_upper = tf.upper() if tf else ""
    fast, mid, slow, mf, ms, msig = _TF_IND_CONFIG.get(tf_upper, _DEFAULT_CONFIG)

    c = df["close"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)

    df["ema_20"]  = talib.EMA(c, timeperiod=fast)
    df["ema_50"]  = talib.EMA(c, timeperiod=mid)
    df["ema_200"] = talib.EMA(c, timeperiod=slow)

    # SMA periode dengan EMA per TF
    df["ma_20"]  = talib.SMA(c, timeperiod=fast)
    df["ma_50"]  = talib.SMA(c, timeperiod=mid)
    df["ma_200"] = talib.SMA(c, timeperiod=slow)

    df["rsi_14"] = talib.RSI(c, timeperiod=14)
    df["atr_14"] = talib.ATR(h, l, c, timeperiod=14)
    df["adx_14"] = talib.ADX(h, l, c, timeperiod=14)

   
    macd_line, macd_signal, hist = talib.MACD(c, fastperiod=mf, slowperiod=ms, signalperiod=msig)
    df["macd_line"]   = macd_line
    df["macd_signal"] = macd_signal
    df["macdhist"]    = hist

    if "tick_volume" in df.columns:
        vol = df["tick_volume"].to_numpy(dtype=float)
        df["vol_ma20"]  = talib.SMA(vol, timeperiod=20)
        df["vol_ratio"] = df["tick_volume"] / df["vol_ma20"].replace(0, float("nan"))
    else:
        df["vol_ma20"]  = float("nan")
        df["vol_ratio"] = float("nan")

    rsi = df["rsi_14"].to_numpy(dtype=float)
    df["rsi_bull_div"],  df["rsi_bear_div"]  = detect_rsi_divergence(c, rsi,  tf=tf)
    df["macd_bull_div"], df["macd_bear_div"] = detect_macd_divergence(c, hist, tf=tf)

    return df
