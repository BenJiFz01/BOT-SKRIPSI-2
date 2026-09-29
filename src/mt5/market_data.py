"""market_data.py — Ambil data OHLCV dari MetaTrader 5.

PENTING — MT5 copy_rates mengembalikan timestamp zona waktu SERVER (bukan UTC);
ofset dideteksi otomatis dari jam tick server vs UTC nyata, override via env
MT5_SERVER_UTC_OFFSET_HOURS (dalam jam, mis. 3 untuk UTC+3).
"""

import os
import time

import pandas as pd
import MetaTrader5 as mt5

from src.config.settings import TF_MAP

_OFFSET: int | None = None


def _server_utc_offset_seconds(symbol: str) -> int:
    """Offset zona waktu server MT5 terhadap UTC dalam detik (cache).

    Prioritas: env MT5_SERVER_UTC_OFFSET_HOURS, lalu estimasi dari selisih
    mt5.symbol_info_tick().time (unix server) dengan time.time() (unix UTC),
    dibulatkan ke kelipatan 30 menit agar mengakomodasi zona :30.
    """
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
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and getattr(tick, "time", 0):
            diff = int(tick.time) - int(time.time())
            # Server timezone hampir selalu kelipatan 30 menit; buang jitter/latensi tick.
            _OFFSET = round(diff / 1800) * 1800
            return _OFFSET
    except Exception:
        pass
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
    offset = _server_utc_offset_seconds(symbol)
    if offset:
        df["time"] = df["time"] - pd.to_timedelta(offset, unit="s")
    return df


def ensure_symbol(symbol: str) -> None:
    """Pastikan simbol tersedia di Market Watch MT5."""
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Gagal memilih simbol {symbol}: {mt5.last_error()}")
