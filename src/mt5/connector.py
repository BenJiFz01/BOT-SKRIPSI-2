"""connector.py — Koneksi ke terminal MetaTrader 5.

Path terminal dikonfigurasi via env MT5_TERMINAL_PATH (default: C:\\Program Files\\MetaTrader 5\\terminal64.exe).
"""

import os

import MetaTrader5 as mt5


def connect(login: int, password: str, server: str, terminal_path: str = "") -> object:
    path = (
        terminal_path
        or os.environ.get("MT5_TERMINAL_PATH", "")
        or r"C:\Program Files\MetaTrader 5\terminal64.exe"
    )

    if not os.path.isfile(path):
        raise RuntimeError(f"MT5 terminal tidak ditemukan: {path}")
    if not mt5.initialize(path=path, portable=True):
        raise RuntimeError(f"MT5 initialize gagal: {mt5.last_error()}")
    if not mt5.login(login=login, password=password, server=server):
        raise RuntimeError(f"MT5 login gagal: {mt5.last_error()}")

    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"MT5 account_info gagal: {mt5.last_error()}")
    return info

def is_connected() -> bool:
    """Cek apakah terminal MT5 aktif dan terhubung ke server broker."""
    try:
        t = mt5.terminal_info()
        if t is None or not getattr(t, "connected", False):
            return False
        acc = mt5.account_info()
        return acc is not None and getattr(acc, "login", 0) > 0
    except Exception:
        return False


def ensure_connected(
    login: int,
    password: str,
    server: str,
    terminal_path: str = "",
    max_retries: int = 3,
    retry_delay: float = 3.0,
) -> bool:
    """Pastikan koneksi MT5 aktif; jika terputus/freeze, lakukan reconnect otomatis."""
    if is_connected():
        return True

    import time
    for attempt in range(1, max_retries + 1):
        try:
            shutdown()
            time.sleep(1.0)
            connect(login, password, server, terminal_path)
            if is_connected():
                return True
        except Exception:
            pass
        if attempt < max_retries:
            time.sleep(retry_delay)
    return False


def shutdown() -> None:
    """Tutup koneksi MT5 dengan aman."""
    try:
        mt5.shutdown()
    except Exception:
        pass
