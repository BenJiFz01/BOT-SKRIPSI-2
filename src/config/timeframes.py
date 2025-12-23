from __future__ import annotations
import MetaTrader5 as mt5

TF_MAP = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

def normalize_tf(tf: str) -> str:
    tf = tf.strip().upper()
    if tf not in TF_MAP:
        raise ValueError(f"Unsupported timeframe: {tf}. Use one of {list(TF_MAP.keys())}")
    return tf
