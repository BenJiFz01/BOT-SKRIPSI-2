from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple
import pandas as pd

@dataclass
class CandleCloseEvent:
    symbol: str
    tf: str
    closed_time: pd.Timestamp

class CandleCloseWatcher:
    """
    Menandai candle 'terakhir yang sudah close' berdasarkan time bar terakhir.
    Jika bar terakhir berubah -> berarti ada bar baru -> bar sebelumnya sudah close.
    """
    def __init__(self) -> None:
        self._last_bar_time: Dict[Tuple[str, str], pd.Timestamp] = {}

    def check(self, symbol: str, tf: str, df: pd.DataFrame) -> CandleCloseEvent | None:
        # df harus sudah urut time naik
        last_time = df["time"].iloc[-1]
        key = (symbol, tf)

        if key not in self._last_bar_time:
            self._last_bar_time[key] = last_time
            return None

        prev_time = self._last_bar_time[key]
        if last_time > prev_time:
            # bar baru muncul -> bar sebelumnya closed
            self._last_bar_time[key] = last_time
            closed_time = df["time"].iloc[-2]
            return CandleCloseEvent(symbol=symbol, tf=tf, closed_time=closed_time)

        return None
