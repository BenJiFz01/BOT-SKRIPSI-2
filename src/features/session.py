"""session.py — Filter sesi trading XAU/USD (WIB/UTC+7)."""

from datetime import datetime, time

import pytz

from src.utils.time_utils import to_wib


_TZ_UTC = pytz.utc

# Timeframe yang tidak difilter sesi
_UNFILTERED_TFS = {"H4", "D1"}

# Jam sesi (WIB)
_ASIAN_START  = time(6,  0)
_ASIAN_END    = time(14, 0)   # nyambung langsung ke London
_LONDON_START = time(14, 0)
_LONDON_END   = time(23, 0)
_NY_START     = time(19, 0)
_NY_END       = time(2,  0)   # melewati tengah malam


def _in_asian(t: time) -> bool:
    return _ASIAN_START <= t <= _ASIAN_END


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
        True jika TF tidak difilter (H4/D1) ATAU jam saat ini dalam
        Asian / London / NY session.
    """
    if tf.upper() in _UNFILTERED_TFS:
        return True

    if dt is None:
        dt = datetime.now(_TZ_UTC)

    t = to_wib(dt).time()
    return _in_asian(t) or _in_london(t) or _in_ny(t)


def session_name(dt: datetime | None = None) -> str:
    """
    Nama sesi trading aktif saat ini (WIB).

    Returns:
        "Overlap L+NY", "London", "New York", "Asian", atau "Off".
    """
    if dt is None:
        dt = datetime.now(_TZ_UTC)

    t    = to_wib(dt).time()
    in_a = _in_asian(t)
    in_l = _in_london(t)
    in_n = _in_ny(t)

    if time(19, 0) <= t <= time(22, 0):
        return "Overlap L+NY"
    if in_l:
        return "London"
    if in_n:
        return "New York"
    if in_a:
        return "Asian"
    return "Off"
