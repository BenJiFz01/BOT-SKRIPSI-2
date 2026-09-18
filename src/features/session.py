"""session.py — Filter sesi trading XAU/USD (WIB/UTC+7).

Filosofi filter sesi yang dipakai:
  - Asian (06:00-14:00 WIB) : TIDAK diblokir total — XAU/USD tetap bergerak
    di Asian terutama saat ada news Asia atau momentum dari overnight NY.
    Yang berbeda: scalping di Asian memerlukan konfirmasi level kunci (SNR/Fib)
    karena volatilitas lebih rendah dan fake breakout lebih sering.
    Flag "asian_mode" = True dikirim ke evaluator agar threshold lebih ketat.

  - London (14:00-23:00 WIB) : Aktif penuh, kondisi terbaik untuk XAU/USD.

  - New York (19:00-02:00 WIB) : Aktif penuh, overlap L+NY (19:00-23:00)
    adalah periode paling likuid dan volatile.

  - Off session (02:00-06:00 WIB): Diblokir untuk M5/M15 scalping —
    periode ini volume sangat rendah, spread lebar, dan noise dominan.
"""

from datetime import datetime, time

import pytz

from src.utils.time_utils import to_wib


_TZ_UTC = pytz.utc

# Timeframe yang tidak difilter sesi sama sekali
_UNFILTERED_TFS = {"H4", "D1"}

# ── Jam sesi (WIB / UTC+7) ────────────────────────────────────────────────────
_ASIAN_START  = time(6,  0)
_ASIAN_END    = time(14, 0)
_LONDON_START = time(14, 0)
_LONDON_END   = time(23, 0)
_NY_START     = time(19, 0)
_NY_END       = time(2,  0)    # melewati tengah malam

# Off session: 02:00-06:00 WIB — diblokir untuk scalping M5/M15
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
    Cek apakah saat ini dalam sesi trading aktif untuk timeframe yang diberikan.

    Args:
        dt : Waktu referensi (UTC-aware). Default = sekarang.
        tf : Timeframe string, contoh 'M5', 'H4'.

    Returns:
        True  jika TF tidak difilter (H4/D1), atau jam dalam sesi aktif.
        False hanya jika off session (02:00-06:00 WIB) untuk scalping M5/M15.

    Catatan:
        Asian session (06:00-14:00) TIDAK diblokir — bot tetap aktif.
        is_asian_session() bisa dipakai untuk mengetahui apakah sedang Asian
        agar evaluator bisa terapkan mode lebih selektif.
    """
    if tf.upper() in _UNFILTERED_TFS:
        return True

    if dt is None:
        dt = datetime.now(_TZ_UTC)

    t = to_wib(dt).time()

    # Blokir hanya off session (02:00-06:00 WIB) untuk M5/M15
    if tf.upper() in ("M5", "M15") and _in_off(t):
        return False

    # H1 juga diblokir di off session (spread lebar, volume rendah)
    if tf.upper() == "H1" and _in_off(t):
        return False

    return True


def is_asian_session(dt: datetime | None = None) -> bool:
    """
    Cek apakah saat ini dalam sesi Asian (06:00-14:00 WIB).
    Digunakan evaluator untuk terapkan mode lebih selektif di Asian:
    scalping hanya boleh jika ada level kunci (SNR/Fib), bukan pure momentum.
    """
    if dt is None:
        dt = datetime.now(_TZ_UTC)
    t = to_wib(dt).time()
    return _in_asian(t)


def session_name(dt: datetime | None = None) -> str:
    """
    Nama sesi trading aktif saat ini (WIB).

    Returns:
        'Overlap L+NY', 'London', 'New York', 'Asian', atau 'Off'.
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
    Kembalikan level keketatan filter untuk sesi saat ini.

    Returns:
        'NORMAL'  — London/NY/Overlap, kondisi optimal
        'RELAXED' — Asian, izinkan sinyal tapi prioritaskan level kunci
        'STRICT'  — transisi antar sesi, lebih hati-hati
        'BLOCKED' — off session, tidak ada sinyal

    Digunakan evaluator untuk menyesuaikan threshold confluence di Asian.
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
