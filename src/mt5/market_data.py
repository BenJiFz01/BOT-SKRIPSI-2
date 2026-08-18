"""market_data.py — Ambil data OHLCV dari MetaTrader 5."""

import pandas as pd
import MetaTrader5 as mt5

from src.config.settings import TF_MAP


def fetch_ohlc(symbol: str, tf: str, n_bars: int = 500) -> pd.DataFrame:
    """Ambil n_bars candle dari MT5 untuk symbol dan timeframe. Raise RuntimeError jika gagal."""
    tf_id = TF_MAP.get(tf.upper())
    if tf_id is None:
        raise ValueError(f"Timeframe tidak dikenal: {tf}")
    rates = mt5.copy_rates_from_pos(symbol, tf_id, 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Tidak ada data MT5 untuk {symbol} {tf}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def ensure_symbol(symbol: str) -> None:
    """Pastikan simbol tersedia di Market Watch MT5."""
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Gagal memilih simbol {symbol}: {mt5.last_error()}")
