"""session.py — Filter sesi trading XAU/USD (WIB/UTC+7).

Asian (06:00-14:00) tidak diblokir tapi butuh konfirmasi level kunci (SNR/Fib).
London dan NY aktif penuh (titik terbaik overlap 19:00-23:00). Off (02:00-06:00)
diblokir untuk scalping M5/M15 — volume rendah, spread lebar, noise dominan.
"""

from datetime import datetime, time

import pytz

from src.utils.time_utils import to_wib


_TZ_UTC = pytz.utc

# Timeframe yang tidak difilter sesi sama sekali
_UNFILTERED_TFS = {"D1"}

# Jam sesi (WIB / UTC+7)
_ASIAN_START  = time(6,  0)
_ASIAN_END    = time(14, 0)
_LONDON_START = time(14, 0)
_LONDON_END   = time(23, 0)
_NY_START     = time(19, 0)
_NY_END       = time(2,  0)    # melewati tengah malam

_OFF_START = time(2,  0)
_OFF_END   = time(6,  0)


def _in_asian(t: time) -> bool:
    return _ASIAN_START <= t < _ASIAN_END


def _in_london(t: time) -> bool:
    return _LONDON_START <= t <= _LONDON_END


def _in_ny(t: time) -> bool:
    """NY session melewati tengah malam: 19:00-02:00."""
    return t >= _NY_START or t <= _NY_END


def _in_off(t: time) -> bool:
    """Off session: 02:00-06:00 WIB — volume sangat rendah."""
    return _OFF_START < t < _OFF_END


def is_active_session(dt: datetime | None = None, tf: str = "M5") -> bool:
    """
    Cek sesi aktif untuk timeframe: True jika TF tak difilter (D1) atau dalam
    jam sesi; False hanya saat off session (02:00-06:00 WIB) untuk M5/M15/H1/H4.
    Asian (06:00-14:00) TIDAK diblokir — lihat is_asian_session() untuk mode selektif.
    """
    if tf.upper() in _UNFILTERED_TFS:
        return True

    if dt is None:
        dt = datetime.now(_TZ_UTC)

    t = to_wib(dt).time()

    # Off session diblokir untuk semua intraday (H4 termasuk, kasus loss 22/09)
    if tf.upper() in ("M5", "M15", "H1", "H4") and _in_off(t):
        return False

    return True


def is_asian_session(dt: datetime | None = None) -> bool:
    """
    Cek apakah dalam sesi Asian (06:00-14:00 WIB). Dipakai evaluator untuk mode
    lebih selektif: scalping hanya boleh jika ada level kunci (SNR/Fib).
    """
    if dt is None:
        dt = datetime.now(_TZ_UTC)
    t = to_wib(dt).time()
    return _in_asian(t)


def session_name(dt: datetime | None = None) -> str:
    """
    Nama sesi trading aktif saat ini (WIB): 'Overlap L+NY', 'London',
    'New York', 'Asian', atau 'Off'.
    """
    if dt is None:
        dt = datetime.now(_TZ_UTC)

    t    = to_wib(dt).time()
    in_a = _in_asian(t)
    in_l = _in_london(t)
    in_n = _in_ny(t)

    if time(19, 0) <= t <= time(23, 0):
        return "Overlap L+NY"
    if in_l:
        return "London"
    if in_n:
        return "New York"
    if in_a:
        return "Asian"
    return "Off"


def session_strictness(dt: datetime | None = None, tf: str = "M5") -> str:
    """
    Keketatan filter sesi: NORMAL (London/NY/Overlap), RELAXED (Asian, prioritaskan
    level kunci), STRICT (transisi), BLOCKED (off session). Dipakai evaluator untuk
    menyesuaikan threshold confluence di Asian.
    """
    if dt is None:
        dt = datetime.now(_TZ_UTC)
    t = to_wib(dt).time()

    if _in_off(t):
        return "BLOCKED"
    if _in_asian(t):
        return "RELAXED"   # aktif tapi preferensi level kunci
    if time(19, 0) <= t <= time(23, 0):
        return "NORMAL"    # overlap terbaik
    if _in_london(t) or _in_ny(t):
        return "NORMAL"
    return "STRICT"        # transisi
