"""scheduler.py — Deteksi candle close per symbol per timeframe."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class CandleCloseEvent:
    symbol:      str
    tf:          str
    closed_time: pd.Timestamp


class CandleCloseWatcher:
    """Monitor candle close dengan membandingkan timestamp bar terakhir."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], pd.Timestamp] = {}

    def check(self, symbol: str, tf: str, df: pd.DataFrame) -> CandleCloseEvent | None:
        """
        Kembalikan CandleCloseEvent jika ada candle baru sejak pengecekan terakhir,
        None jika belum ada perubahan.
        """
        if len(df) < 2:
            return None
        key      = (symbol, tf)
        last_bar = pd.to_datetime(df.iloc[-2]["time"])
        if self._last.get(key) != last_bar:
            self._last[key] = last_bar
            return CandleCloseEvent(symbol=symbol, tf=tf, closed_time=last_bar)
        return None
