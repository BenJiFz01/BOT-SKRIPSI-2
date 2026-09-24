"""market_data.py — Ambil data OHLCV dari MetaTrader 5.

PENTING — MT5 copy_rates mengembalikan timestamp zona waktu SERVER (bukan UTC);
ofset diambil dari mt5.terminal_info().timezone, override via env MT5_SERVER_UTC_OFFSET_HOURS.
"""

import os

import pandas as pd
import MetaTrader5 as mt5

from src.config.settings import TF_MAP

_OFFSET: int | None = None


def _server_utc_offset_seconds() -> int:
    """Offset zona waktu server MT5 terhadap UTC dalam detik (cache)."""
    global _OFFSET
    if _OFFSET is not None:
        return _OFFSET

    env = os.getenv("MT5_SERVER_UTC_OFFSET_HOURS")
    if env:
        try:
            _OFFSET = int(float(env) * 3600)
            return _OFFSET
        except ValueError:
            pass

    try:
        info = mt5.terminal_info()
        _OFFSET = int(getattr(info, "timezone", 0)) if info else 0
    except Exception:
        _OFFSET = 0
    return _OFFSET


def fetch_ohlc(symbol: str, tf: str, n_bars: int = 500) -> pd.DataFrame:
    """Ambil n_bars candle dari MT5 untuk symbol dan timeframe. Raise RuntimeError jika gagal.

    Timestamp dikonversi ke UTC-naive agar engine (session, cooldown, WIB) konsisten.
    """
    tf_id = TF_MAP.get(tf.upper())
    if tf_id is None:
        raise ValueError(f"Timeframe tidak dikenal: {tf}")
    rates = mt5.copy_rates_from_pos(symbol, tf_id, 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Tidak ada data MT5 untuk {symbol} {tf}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    offset = _server_utc_offset_seconds()
    if offset:
        df["time"] = df["time"] - pd.to_timedelta(offset, unit="s")
    return df


def ensure_symbol(symbol: str) -> None:
    """Pastikan simbol tersedia di Market Watch MT5."""
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Gagal memilih simbol {symbol}: {mt5.last_error()}")
