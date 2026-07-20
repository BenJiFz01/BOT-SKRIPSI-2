"""
settings.py
===========
Konfigurasi aplikasi dari environment variables (.env).

Semua parameter bisa dikustomisasi via file .env di root project.
Lihat .env.example untuk daftar lengkap dan penjelasan tiap parameter.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .timeframes import normalize_tf

load_dotenv(override=True)


# ── Helper pembaca env vars ───────────────────────────────────────────

def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or str(v).strip() == "":
        raise ValueError(f"Environment variable wajib tidak ditemukan: {name}")
    return str(v).strip()


def _getf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} harus angka desimal, dapat: '{os.getenv(name)}'")


def _geti(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} harus angka bulat, dapat: '{os.getenv(name)}'")


def _getb(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ── Dataclass konfigurasi ─────────────────────────────────────────────

@dataclass(frozen=True)
class Settings:
    # MetaTrader 5
    mt5_login:    int
    mt5_password: str
    mt5_server:   str

    # Telegram
    telegram_token:   str
    telegram_chat_id: str

    # Instrumen & data
    symbols:      list[str]
    timeframes:   list[str]
    bars:         int
    poll_seconds: int

    # Gate threshold keputusan
    min_rr:               float
    min_confirm_votes:    int
    min_trigger_score:    int
    min_confluence_score: int
    cooldown_bars:        int
    atr_min_pct:          float

    # SL/TP berbasis ATR (primary)
    sl_atr_mult: float
    tp1_rr:      float
    tp2_rr:      float
    tp3_rr:      float

    # SL/TP fixed pip (fallback)
    sl_pips:  float
    tp1_pips: float
    tp2_pips: float
    tp3_pips: float
    pip_size: float

    # Session filter
    session_filter: bool


def load_settings() -> Settings:
    """Baca semua konfigurasi dari .env dan kembalikan objek Settings."""
    symbols = [s.strip() for s in _get("SYMBOLS", "XAUUSD").split(",") if s.strip()]
    tfs     = [
        normalize_tf(x)
        for x in _get("TIMEFRAMES", "M5,M15,H1,H4,D1").split(",")
        if x.strip()
    ]

    return Settings(
        mt5_login    = _geti("MT5_LOGIN", 0),
        mt5_password = _get("MT5_PASSWORD"),
        mt5_server   = _get("MT5_SERVER"),

        telegram_token   = _get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id = _get("TELEGRAM_CHAT_ID"),

        symbols      = symbols,
        timeframes   = tfs,
        bars         = _geti("BARS", 800),
        poll_seconds = _geti("POLL_SECONDS", 5),

        min_rr               = _getf("MIN_RR",               1.5),
        min_confirm_votes    = _geti("MIN_CONFIRM_VOTES",    1),
        min_trigger_score    = _geti("MIN_TRIGGER_SCORE",    4),
        min_confluence_score = _geti("MIN_CONFLUENCE_SCORE", 2),
        cooldown_bars        = _geti("COOLDOWN_BARS",         3),
        atr_min_pct          = _getf("ATR_MIN_PCT",           0.0006),

        sl_atr_mult = _getf("SL_ATR_MULT", 1.5),
        tp1_rr      = _getf("TP1_RR",      1.5),
        tp2_rr      = _getf("TP2_RR",      2.5),
        tp3_rr      = _getf("TP3_RR",      4.0),

        sl_pips  = _getf("SL_PIPS",  50.0),
        tp1_pips = _getf("TP1_PIPS", 70.0),
        tp2_pips = _getf("TP2_PIPS", 100.0),
        tp3_pips = _getf("TP3_PIPS", 140.0),
        pip_size = _getf("PIP_SIZE", 0.1),

        session_filter = _getb("SESSION_FILTER", True),
    )
