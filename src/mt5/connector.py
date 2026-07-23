"""connector.py — Koneksi ke terminal MetaTrader 5."""
from __future__ import annotations

import os

import MetaTrader5 as mt5


TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


def connect(login: int, password: str, server: str):
    """
    Inisialisasi dan login ke MT5.
    Raises RuntimeError jika terminal tidak ditemukan, gagal initialize, atau login gagal.
    """
    if not os.path.isfile(TERMINAL_PATH):
        raise RuntimeError(f"MT5 terminal tidak ditemukan: {TERMINAL_PATH}")
    if not mt5.initialize(path=TERMINAL_PATH, portable=True):
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
