"""
market_data.py
==============
Pengambilan data OHLCV dari MetaTrader 5.
"""
from __future__ import annotations

import MetaTrader5 as mt5
import pandas as pd
from loguru import logger

from src.config.timeframes import TF_MAP


def fetch_ohlc(symbol: str, tf: str, n_bars: int) -> pd.DataFrame:
    """
    Ambil data OHLCV dari MT5.

    Args:
        symbol: Nama instrumen, contoh "XAUUSD".
        tf:     Timeframe string, contoh "M5", "H1".
        n_bars: Jumlah candle yang diambil.

    Returns:
        DataFrame dengan kolom: time, open, high, low, close, volume.

    Raises:
        RuntimeError jika data tidak tersedia.
    """
    timeframe = TF_MAP[tf]
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)

    if rates is None:
        raise RuntimeError(
            f"copy_rates_from_pos gagal untuk {symbol} {tf}: {mt5.last_error()}"
        )
    if len(rates) == 0:
        raise RuntimeError(f"Tidak ada data untuk {symbol} {tf}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df


def ensure_symbol(symbol: str) -> None:
    """Pastikan simbol tersedia di Market Watch MT5."""
    if not mt5.symbol_select(symbol, True):
        logger.warning(f"symbol_select gagal untuk {symbol}: {mt5.last_error()}")
