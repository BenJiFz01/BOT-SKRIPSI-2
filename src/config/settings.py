from __future__ import annotations
from dataclasses import dataclass
import os
from dotenv import load_dotenv
from .timeframes import normalize_tf

load_dotenv()

def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or str(v).strip() == "":
        raise ValueError(f"Missing env var: {name}")
    return v

@dataclass(frozen=True)
class Settings:
    mt5_login: int
    mt5_password: str
    mt5_server: str

    telegram_token: str
    telegram_chat_id: str

    symbols: list[str]
    timeframes: list[str]
    bars: int
    poll_seconds: int
    min_rr: float

def load_settings() -> Settings:
    symbols = [s.strip() for s in _get("SYMBOLS", "XAUUSD").split(",") if s.strip()]
    tfs = [normalize_tf(x) for x in _get("TIMEFRAMES", "M15,H1").split(",") if x.strip()]

    return Settings(
        mt5_login=int(_get("MT5_LOGIN")),
        mt5_password=_get("MT5_PASSWORD"),
        mt5_server=_get("MT5_SERVER"),
        telegram_token=_get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
        symbols=symbols,
        timeframes=tfs,
        bars=int(_get("BARS", "300")),
        poll_seconds=int(_get("POLL_SECONDS", "2")),
        min_rr=float(_get("MIN_RR", "1.5")),
    )
