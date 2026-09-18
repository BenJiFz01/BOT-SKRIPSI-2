"""time_utils.py — Utilitas konversi waktu terpusat (WIB / UTC+7).

Semua konversi ke WIB di project ini menggunakan modul ini.
Sebelumnya tersebar di: session.py, templates.py, signal_logger.py,
laporan_excel.py, signal_tracker.py.
"""

from datetime import datetime, timedelta, timezone


# Konstanta timezone WIB (UTC+7) — dipakai oleh semua modul
TZ_WIB = timezone(timedelta(hours=7))


def now_wib() -> datetime:
    """Kembalikan datetime sekarang dalam WIB."""
    return datetime.now(tz=TZ_WIB)


def now_wib_str() -> str:
    """Kembalikan timestamp WIB sekarang dalam format ISO tanpa suffix timezone."""
    return now_wib().strftime("%Y-%m-%dT%H:%M:%S")


def to_wib(dt: datetime) -> datetime:
    """
    Konversi datetime ke WIB.
    Jika dt naive (tanpa tzinfo), diasumsikan UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_WIB)


def iso_to_wib_str(iso_str: str, fmt: str = "%Y-%m-%d %H:%M WIB") -> str:
    """
    Konversi string ISO datetime ke string WIB yang dapat dibaca.

    Args:
        iso_str: String datetime format ISO, misal '2024-01-15T08:30:00+00:00'.
        fmt:     Format output. Default: '%Y-%m-%d %H:%M WIB'.

    Returns:
        String waktu dalam WIB, atau iso_str asli jika parsing gagal.

    Aturan konversi:
      - Ada offset timezone (mis. '...T05:15:00+00:00') → dikonversi ke WIB.
      - Naive tanpa offset → diasumsikan sudah WIB (diisi tzinfo WIB), diformat apa adanya.
    """
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_WIB)
        else:
            dt = dt.astimezone(TZ_WIB)
        return dt.strftime(fmt)
    except ValueError:
        # Fallback untuk format lama yang gagal di fromisoformat (mis. separator spasi/std).
        try:
            dt = datetime.fromisoformat(iso_str[:19])
            return dt.replace(tzinfo=TZ_WIB).strftime(fmt)
        except Exception:
            return iso_str[:19]
    except Exception:
        return iso_str[:19]


def iso_to_wib_excel(iso_str: str) -> str:
    """
    Konversi ISO timestamp ke format WIB untuk tampilan Excel.
    Format: 'DD/MM/YYYY HH:MM WIB'.
    """
    return iso_to_wib_str(iso_str, fmt="%d/%m/%Y %H:%M WIB")


def parse_dt_safe(s: str) -> datetime:
    """
    Parse string datetime dengan aman. Jika gagal, kembalikan waktu sekarang WIB.
    Mendukung format ISO dengan atau tanpa suffix 'Z'.
    """
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_WIB)
        return dt
    except Exception:
        return now_wib()
