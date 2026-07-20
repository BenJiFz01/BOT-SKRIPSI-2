"""
session.py
==========
Filter sesi trading untuk XAU/USD.

Jam trading aktif (WIB / UTC+7):
    - London Open  : 14:00 - 23:00
    - New York     : 19:00 - 02:00 (+1 hari)
    - Overlap L+NY : 19:00 - 22:00  (volatilitas tertinggi)
    - Asian        : 02:00 - 08:00  (kualitas sinyal rendah)

Aturan session filter:
    - M5, M15, H1  : hanya aktif di London + New York session
    - H4, D1       : tidak difilter (mewakili trend makro, tidak sensitif sesi)
"""
from __future__ import annotations

from datetime import datetime, time

import pytz


_TZ_WIB = pytz.timezone("Asia/Jakarta")

# Timeframe yang tidak difilter sesi
_UNFILTERED_TFS = {"H4", "D1"}

# Jam sesi (WIB)
_LONDON_START = time(14, 0)
_LONDON_END   = time(23, 0)
_NY_START     = time(19, 0)
_NY_END       = time(2,  0)   # melewati tengah malam


def _to_wib(dt: datetime) -> datetime:
    """Konversi datetime ke WIB (UTC+7)."""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(_TZ_WIB)


def _in_london(t: time) -> bool:
    return _LONDON_START <= t <= _LONDON_END


def _in_ny(t: time) -> bool:
    """NY session melewati tengah malam: 19:00 - 02:00."""
    return t >= _NY_START or t <= _NY_END


def is_active_session(dt: datetime | None = None, tf: str = "M5") -> bool:
    """
    Cek apakah saat ini dalam sesi trading aktif untuk timeframe yang diberikan.

    Args:
        dt: Waktu referensi (UTC-aware). Default = sekarang.
        tf: Timeframe string, contoh "M5", "H4".

    Returns:
        True jika TF tidak difilter (H4/D1) ATAU jam saat ini dalam London/NY session.
    """
    if tf.upper() in _UNFILTERED_TFS:
        return True

    if dt is None:
        dt = datetime.now(pytz.utc)

    t = _to_wib(dt).time()
    return _in_london(t) or _in_ny(t)


def session_name(dt: datetime | None = None) -> str:
    """
    Nama sesi trading aktif saat ini (WIB).

    Returns:
        "Overlap L+NY", "London", "New York", "Asian", atau "Off".
    """
    if dt is None:
        dt = datetime.now(pytz.utc)

    t      = _to_wib(dt).time()
    in_l   = _in_london(t)
    in_n   = _in_ny(t)
    in_ov  = time(19, 0) <= t <= time(22, 0)

    if in_ov:
        return "Overlap L+NY"
    if in_l:
        return "London"
    if in_n:
        return "New York"
    if time(2, 0) <= t <= time(8, 0):
        return "Asian"
    return "Off"
