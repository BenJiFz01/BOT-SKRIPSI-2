import MetaTrader5 as mt5
import os

TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"  # sesuaikan

def shutdown():
    try:
        mt5.shutdown()
    except Exception:
        pass

def connect(login: int, password: str, server: str):
    if not os.path.isfile(TERMINAL_PATH):
        raise RuntimeError(f"MT5 terminal not found: {TERMINAL_PATH}")

    # 1) init terminal dulu TANPA login
    if not mt5.initialize(path=TERMINAL_PATH, portable=True):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    # 2) login TERPISAH
    if not mt5.login(login=login, password=password, server=server):
        raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")

    return info
