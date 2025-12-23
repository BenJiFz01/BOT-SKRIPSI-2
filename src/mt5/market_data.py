from __future__ import annotations
import MetaTrader5 as mt5
import pandas as pd
from loguru import logger
from src.config.timeframes import TF_MAP

def fetch_ohlc(symbol: str, tf: str, n_bars: int) -> pd.DataFrame:
    timeframe = TF_MAP[tf]
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
    if rates is None:
        raise RuntimeError(f"copy_rates_from_pos returned None for {symbol} {tf}: {mt5.last_error()}")
    if len(rates) == 0:
        raise RuntimeError(f"No rates returned for {symbol} {tf}")

    df = pd.DataFrame(rates)
    # MT5 time is in seconds epoch
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df

def ensure_symbol(symbol: str) -> None:
    selected = mt5.symbol_select(symbol, True)
    if not selected:
        logger.warning(f"symbol_select failed for {symbol}: {mt5.last_error()}")
