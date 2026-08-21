"""scheduler.py — Deteksi candle close per symbol per timeframe."""

import pandas as pd


class CandleCloseWatcher:
    """Monitor candle close dengan membandingkan timestamp bar terakhir."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], pd.Timestamp] = {}

    def check(self, symbol: str, tf: str, df: pd.DataFrame) -> pd.Timestamp | None:
        """
        Kembalikan timestamp candle yang baru close jika ada perubahan,
        None jika belum ada candle baru sejak pengecekan terakhir.
        """
        if len(df) < 2:
            return None
        key      = (symbol, tf)
        last_bar = pd.to_datetime(df.iloc[-2]["time"])
        if self._last.get(key) != last_bar:
            self._last[key] = last_bar
            return last_bar
        return None
