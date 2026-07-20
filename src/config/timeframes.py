"""
timeframes.py
=============
Mapping nama timeframe string ke konstanta MetaTrader 5.
"""
from __future__ import annotations

import MetaTrader5 as mt5


TF_MAP: dict[str, int] = {
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def normalize_tf(tf: str) -> str:
    """
    Normalisasi string timeframe ke uppercase dan validasi.

    Raises:
        ValueError jika timeframe tidak didukung.
    """
    tf = tf.strip().upper()
    if tf not in TF_MAP:
        raise ValueError(f"Timeframe tidak didukung: '{tf}'. Pilihan: {list(TF_MAP.keys())}")
    return tf
