"""scheduler.py — Deteksi candle close berdasarkan perubahan time bar terakhir."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CandleCloseEvent:
    symbol:      str
    tf:          str
    closed_time: pd.Timestamp


class CandleCloseWatcher:
    """Memantau perubahan bar terakhir per (symbol, timeframe)."""

    def __init__(self) -> None:
        self._last_bar_time: dict[tuple[str, str], pd.Timestamp] = {}

    def check(self, symbol: str, tf: str, df: pd.DataFrame) -> CandleCloseEvent | None:
        """
        Cek apakah ada candle baru sejak pengecekan terakhir.
        Returns CandleCloseEvent jika ada candle baru, None jika belum.
        """
        last_time = df["time"].iloc[-1]
        key       = (symbol, tf)

        if key not in self._last_bar_time:
            self._last_bar_time[key] = last_time
            return None

        if last_time > self._last_bar_time[key]:
            self._last_bar_time[key] = last_time
            closed_time = df["time"].iloc[-2]
            return CandleCloseEvent(symbol=symbol, tf=tf, closed_time=closed_time)

        return None
