"""
scheduler.py
============
Deteksi candle close berdasarkan perubahan time bar terakhir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd


@dataclass
class CandleCloseEvent:
    """Event yang dipicu saat sebuah candle selesai (close)."""
    symbol:      str
    tf:          str
    closed_time: pd.Timestamp


class CandleCloseWatcher:
    """
    Memantau perubahan bar terakhir per (symbol, timeframe).

    Cara kerja:
        Setiap kali bar terakhir berubah (time-nya lebih baru), berarti
        bar sebelumnya sudah closed. Event dikembalikan dengan waktu bar
        yang baru saja closed.
    """

    def __init__(self) -> None:
        self._last_bar_time: Dict[Tuple[str, str], pd.Timestamp] = {}

    def check(
        self,
        symbol: str,
        tf:     str,
        df:     pd.DataFrame,
    ) -> CandleCloseEvent | None:
        """
        Periksa apakah ada candle baru sejak pengecekan terakhir.

        Args:
            symbol: Nama instrumen.
            tf:     Timeframe string.
            df:     DataFrame OHLCV yang sudah diurutkan ascending.

        Returns:
            CandleCloseEvent jika ada candle baru, None jika belum.
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
