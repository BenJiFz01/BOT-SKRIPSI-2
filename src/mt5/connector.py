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

def shutdown() -> None:
    """Tutup koneksi MT5 dengan aman."""
    try:
        mt5.shutdown()
    except Exception:
        pass
