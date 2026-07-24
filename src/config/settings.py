"""settings.py — Konfigurasi bot dari .env"""
from __future__ import annotations

import os
from dataclasses import dataclass

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(override=True)

TF_MAP: dict[str, int] = {
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def normalize_tf(tf: str) -> str:
    tf = tf.strip().upper()
    if tf not in TF_MAP:
        raise ValueError(f"Timeframe tidak didukung: '{tf}'. Pilihan: {list(TF_MAP.keys())}")
    return tf


def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or str(v).strip() == "":
        raise ValueError(f"Env var wajib tidak ditemukan: {name}")
    return str(v).strip()


def _getf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} harus float, dapat: '{os.getenv(name)}'")


def _geti(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} harus int, dapat: '{os.getenv(name)}'")


def _getb(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    mt5_login:    int
    mt5_password: str
    mt5_server:   str

    telegram_token:   str
    telegram_chat_id: str

    symbols:      list[str]
    timeframes:   list[str]
    bars:         int
    poll_seconds: int

    min_rr:               float
    min_confirm_votes:    int
    min_trigger_score:    int
    min_confluence_score: int
    cooldown_bars:        int
    atr_min_pct:          float

    sl_atr_mult:   float
    tp1_rr:        float
    tp2_rr:        float
    tp3_rr:        float
    max_sl_points: float

    sl_pips:  float
    tp1_pips: float
    tp2_pips: float
    tp3_pips: float
    pip_size: float

    session_filter: bool

    counter_trend_enabled:  bool
    min_counter_confluence: int
    counter_trend_min_rr:   float
    counter_trend_tfs:      list[str]

    # Scalping mode threshold (M5/M15)
    scalping_min_trigger_score:    int
    scalping_min_confluence_score: int
    scalping_sl_atr_mult:          float
    scalping_cooldown_bars:        int
    scalping_max_sl_points:        float
    scalping_tp1_rr:               float
    scalping_tp2_rr:               float
    scalping_tp3_rr:               float

def load_settings() -> Settings:
    symbols = [s.strip() for s in _get("SYMBOLS", "XAUUSD").split(",") if s.strip()]
    tfs     = [normalize_tf(x) for x in _get("TIMEFRAMES", "M5,M15,H1,H4,D1").split(",") if x.strip()]

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
        min_confirm_votes    = _geti("MIN_CONFIRM_VOTES",     2),
        min_trigger_score    = _geti("MIN_TRIGGER_SCORE",     4),
        min_confluence_score = _geti("MIN_CONFLUENCE_SCORE",  2),
        cooldown_bars        = _geti("COOLDOWN_BARS",          3),
        atr_min_pct          = _getf("ATR_MIN_PCT",            0.0006),

        sl_atr_mult   = _getf("SL_ATR_MULT",    1.5),
        tp1_rr        = _getf("TP1_RR",         1.5),
        tp2_rr        = _getf("TP2_RR",         2.5),
        tp3_rr        = _getf("TP3_RR",         4.0),
        max_sl_points = _getf("MAX_SL_POINTS", 50.0),

        sl_pips  = _getf("SL_PIPS",   50.0),
        tp1_pips = _getf("TP1_PIPS",  70.0),
        tp2_pips = _getf("TP2_PIPS", 100.0),
        tp3_pips = _getf("TP3_PIPS", 140.0),
        pip_size = _getf("PIP_SIZE",   0.1),

        session_filter = _getb("SESSION_FILTER", True),

        counter_trend_enabled  = _getb("COUNTER_TREND_ENABLED",  True),
        min_counter_confluence = _geti("MIN_COUNTER_CONFLUENCE",   3),
        counter_trend_min_rr   = _getf("COUNTER_TREND_MIN_RR",    2.0),
        counter_trend_tfs      = [
            t.strip().upper()
            for t in _get("COUNTER_TREND_TFS", "H1,H4").split(",")
            if t.strip()
        ],

        scalping_min_trigger_score    = _geti("SCALPING_MIN_TRIGGER_SCORE",    3),
        scalping_min_confluence_score = _geti("SCALPING_MIN_CONFLUENCE_SCORE", 1),
        scalping_sl_atr_mult          = _getf("SCALPING_SL_ATR_MULT",          1.2),
        scalping_cooldown_bars        = _geti("SCALPING_COOLDOWN_BARS",        5),
        scalping_max_sl_points        = _getf("SCALPING_MAX_SL_POINTS",        5.0),
        scalping_tp1_rr               = _getf("SCALPING_TP1_RR",               1.5),
        scalping_tp2_rr               = _getf("SCALPING_TP2_RR",               2.0),
        scalping_tp3_rr               = _getf("SCALPING_TP3_RR",               2.5),
    )
