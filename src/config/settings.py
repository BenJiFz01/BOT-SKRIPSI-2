"""settings.py — Konfigurasi bot dari .env"""
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


def _normalize_tf(tf: str) -> str:
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
    # MT5
    mt5_login:         int
    mt5_password:      str
    mt5_server:        str
    mt5_terminal_path: str

    # Telegram
    telegram_token:   str
    telegram_chat_id: str

    # Umum
    symbols:      list[str]
    timeframes:   list[str]
    bars:         int
    poll_seconds: int

    # Gate threshold
    min_rr:               float
    min_confirm_votes:    int
    min_trigger_score:    int
    min_confluence_score: int
    cooldown_bars:        int
    atr_min_pct:          float

    market_transition_adx_block: float
    market_transition_adx_gray:  float

    scalping_h1_only:     bool
    intraday_require_d1:  bool

    # SL/TP ATR-based (DEPRECATED, legacy intraday)
    sl_atr_mult:   float
    tp1_rr:        float
    tp2_rr:        float
    tp3_rr:        float
    max_sl_points: float

    # SL/TP Fixed pip (fallback)
    sl_pips:  float
    tp1_pips: float
    tp2_pips: float
    tp3_pips: float
    pip_size: float

    # Pure ATR-based SL/TP (NEW)
    spread:                    float
    scalping_atr_len:          int
    scalping_sl_buffer_atr:    float
    scalping_min_spread_mult:  float
    scalping_max_atr_mult:     float
    intraday_atr_len:          int
    intraday_sl_atr_mult:      float
    intraday_sl_buffer_atr:    float
    intraday_min_spread_mult:  float
    intraday_max_atr_mult:     float
    intraday_tp1_rr:           float
    intraday_tp2_rr:           float
    intraday_tp3_rr:           float
    obstacle_min_rr_frac:      float

    # Session filter
    session_filter: bool

    # Counter trend
    counter_trend_enabled:  bool
    min_counter_confluence: int
    counter_trend_min_rr:   float
    counter_trend_tfs:      list[str]

    # Cap SL per TF
    max_sl_m5:  float
    max_sl_m15: float
    max_sl_h1:  float
    max_sl_h4:  float
    max_sl_d1:  float

    # Scalping
    scalping_min_trigger_score:    int
    scalping_min_confluence_score: int
    scalping_atr_min_points:       float
    scalping_sl_atr_mult:          float
    scalping_cooldown_bars:        int
    scalping_cooldown_bars_m5:     int
    scalping_cooldown_bars_m15:    int
    scalping_tp1_rr:               float
    scalping_tp2_rr:               float
    scalping_tp3_rr:               float
    scalping_tp1_atr_mult:         float
    scalping_min_rr:               float
    # Scalping CT min RR terpisah dari intraday
    scalping_counter_trend_min_rr: float
    scalping_overextend_atr_mult:  float
    scalping_pullback_enabled:     bool
    scalping_sweep_enabled:        bool
    scalping_fvg_enabled:          bool
    momentum_ema200_tolerance:     float
    range_rejection_enabled:       bool

    # Tuas keketatan
    ltf_veto_enabled:              bool
    flip_min_trigger:              int    # FLIP wajib trigger >= nilai ini (3 ketat / 2 longgar+struktur)
    flip_require_key_level:        bool   # FLIP wajib key level (SnR/SnD)
    h1_require_key_level:          bool   # H1 wajib key level
    scalping_pullback_min_trigger: int    # floor trigger jalur PULLBACK (default 2)
    range_quality_key_level:       bool   # RANGE/sideways: continuation wajib key level berkualitas


def load_settings() -> Settings:
    symbols = [s.strip() for s in _get("SYMBOLS", "XAUUSD").split(",") if s.strip()]
    tfs     = [_normalize_tf(x) for x in _get("TIMEFRAMES", "M5,M15,H1,H4,D1").split(",") if x.strip()]

    mt5_login = _geti("MT5_LOGIN", 0)
    if mt5_login <= 0:
        raise ValueError("Env var wajib tidak valid: MT5_LOGIN harus berupa angka positif")

    s = Settings(
        mt5_login         = mt5_login,
        mt5_password      = _get("MT5_PASSWORD"),
        mt5_server        = _get("MT5_SERVER"),
        mt5_terminal_path = _get("MT5_TERMINAL_PATH",
                                  r"C:\Program Files\MetaTrader 5\terminal64.exe"),

        telegram_token   = _get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id = _get("TELEGRAM_CHAT_ID"),

        symbols      = symbols,
        timeframes   = tfs,
        bars         = _geti("BARS",         800),
        poll_seconds = _geti("POLL_SECONDS", 5),

        min_rr               = _getf("MIN_RR",               1.5),
        min_confirm_votes    = _geti("MIN_CONFIRM_VOTES",     1),
        min_trigger_score    = _geti("MIN_TRIGGER_SCORE",     4),
        min_confluence_score = _geti("MIN_CONFLUENCE_SCORE",  2),
        cooldown_bars        = _geti("COOLDOWN_BARS",         3),
        atr_min_pct          = _getf("ATR_MIN_PCT",           0.0006),

        market_transition_adx_block = _getf("MARKET_TRANSITION_ADX_BLOCK", 15.0),
        market_transition_adx_gray  = _getf("MARKET_TRANSITION_ADX_GRAY",  25.0),

        scalping_h1_only    = _getb("SCALPING_H1_ONLY",   True),
        intraday_require_d1 = _getb("INTRADAY_REQUIRE_D1", True),

        sl_atr_mult   = _getf("SL_ATR_MULT",    1.5),
        tp1_rr        = _getf("TP1_RR",         1.5),
        tp2_rr        = _getf("TP2_RR",         2.5),
        tp3_rr        = _getf("TP3_RR",         4.0),
        max_sl_points = _getf("MAX_SL_POINTS", 50.0),

        sl_pips  = _getf("SL_PIPS",    50.0),
        tp1_pips = _getf("TP1_PIPS",   70.0),
        tp2_pips = _getf("TP2_PIPS",  100.0),
        tp3_pips = _getf("TP3_PIPS",  140.0),
        pip_size = _getf("PIP_SIZE",    0.1),

        spread                    = _getf("SPREAD",                    0.30),
        scalping_atr_len          = _geti("SCALPING_ATR_LEN",          14),
        scalping_sl_buffer_atr    = _getf("SCALPING_SL_BUFFER_ATR",    0.3),
        scalping_min_spread_mult  = _getf("SCALPING_MIN_SPREAD_MULT",  3.0),
        scalping_max_atr_mult     = _getf("SCALPING_MAX_ATR_MULT",     2.0),
        intraday_atr_len          = _geti("INTRADAY_ATR_LEN",          14),
        intraday_sl_atr_mult      = _getf("INTRADAY_SL_ATR_MULT",      1.5),
        intraday_sl_buffer_atr    = _getf("INTRADAY_SL_BUFFER_ATR",    0.5),
        intraday_min_spread_mult  = _getf("INTRADAY_MIN_SPREAD_MULT",  5.0),
        intraday_max_atr_mult     = _getf("INTRADAY_MAX_ATR_MULT",     2.5),
        intraday_tp1_rr           = _getf("INTRADAY_TP1_RR",           1.0),
        intraday_tp2_rr           = _getf("INTRADAY_TP2_RR",           2.0),
        intraday_tp3_rr           = _getf("INTRADAY_TP3_RR",           3.0),
        obstacle_min_rr_frac      = _getf("OBSTACLE_MIN_RR_FRAC",      0.8),

        session_filter = _getb("SESSION_FILTER", True),

        counter_trend_enabled  = _getb("COUNTER_TREND_ENABLED",  True),
        min_counter_confluence = _geti("MIN_COUNTER_CONFLUENCE",  3),
        counter_trend_min_rr   = _getf("COUNTER_TREND_MIN_RR",   2.0),
        counter_trend_tfs      = [
            t.strip().upper()
            for t in _get("COUNTER_TREND_TFS", "H1,H4").split(",") if t.strip()
        ],

        max_sl_m5  = _getf("MAX_SL_M5",   15.0),
        max_sl_m15 = _getf("MAX_SL_M15",  20.0),
        max_sl_h1  = _getf("MAX_SL_H1",   40.0),
        max_sl_h4  = _getf("MAX_SL_H4",   60.0),
        max_sl_d1  = _getf("MAX_SL_D1",  100.0),

        scalping_min_trigger_score    = _geti("SCALPING_MIN_TRIGGER_SCORE",    3),
        scalping_min_confluence_score = _geti("SCALPING_MIN_CONFLUENCE_SCORE", 2),
        scalping_atr_min_points       = _getf("SCALPING_ATR_MIN_POINTS",       4.0),
        scalping_sl_atr_mult          = _getf("SCALPING_SL_ATR_MULT",          1.2),
        scalping_cooldown_bars        = _geti("SCALPING_COOLDOWN_BARS",        5),
        scalping_cooldown_bars_m5     = _geti("SCALPING_COOLDOWN_BARS_M5",     6),
        scalping_cooldown_bars_m15    = _geti("SCALPING_COOLDOWN_BARS_M15",    5),
        scalping_tp1_rr               = _getf("SCALPING_TP1_RR",               1.0),
        scalping_tp2_rr               = _getf("SCALPING_TP2_RR",               1.5),
        scalping_tp3_rr               = _getf("SCALPING_TP3_RR",               2.0),
        scalping_tp1_atr_mult         = _getf("SCALPING_TP1_ATR_MULT",         0.0),
        scalping_min_rr               = _getf("SCALPING_MIN_RR",               1.0),
        scalping_counter_trend_min_rr = _getf("SCALPING_COUNTER_TREND_MIN_RR", 1.5),
        scalping_overextend_atr_mult  = _getf("SCALPING_OVEREXTEND_ATR_MULT",  1.2),
        scalping_pullback_enabled     = _getb("SCALPING_PULLBACK_ENABLED",     False),
        scalping_sweep_enabled        = _getb("SCALPING_LIQUIDITY_SWEEP_ENABLED", False),
        scalping_fvg_enabled          = _getb("SCALPING_FVG_ENABLED",            False),
        momentum_ema200_tolerance     = _getf("MOMENTUM_EMA200_TOLERANCE",       1.0),
        range_rejection_enabled       = _getb("RANGE_REJECTION_ENABLED",         True),
        ltf_veto_enabled              = _getb("LTF_VETO_ENABLED",                True),
        flip_min_trigger              = _geti("FLIP_MIN_TRIGGER",                3),
        flip_require_key_level        = _getb("FLIP_REQUIRE_KEY_LEVEL",          True),
        h1_require_key_level          = _getb("H1_REQUIRE_KEY_LEVEL",            True),
        scalping_pullback_min_trigger = _geti("SCALPING_PULLBACK_MIN_TRIGGER",    2),
        range_quality_key_level       = _getb("RANGE_QUALITY_KEY_LEVEL",          True),
    )
    
    scal_tp1 = _getf("SCALPING_TP1_RR", 1.0)
    scal_tp2 = _getf("SCALPING_TP2_RR", 1.5)
    scal_tp3 = _getf("SCALPING_TP3_RR", 2.0)
    intra_tp1 = s.intraday_tp1_rr
    intra_tp2 = s.intraday_tp2_rr
    intra_tp3 = s.intraday_tp3_rr
    obs_frac = s.obstacle_min_rr_frac
    
    if obs_frac <= 0.75:
        raise ValueError(
            f"OBSTACLE_MIN_RR_FRAC={obs_frac:.2f} terlalu rendah. "
            f"Untuk scalping (TP 1.0/1.5/2.0R), min_rr harus > 0.75 (0.75×1.5=1.125 < 1.0). "
            f"Untuk intraday (TP 1.0/2.0/3.0R), min_rr harus > 0.67. "
            f"Nilai rendah menyebabkan TP collision (tp2_adjusted == tp3_adjusted). "
            f"Gunakan >= 0.8 (default)."
        )
    
    if not (scal_tp1 < scal_tp2 < scal_tp3):
        raise ValueError(
            f"SCALPING TP order salah: TP1={scal_tp1} < TP2={scal_tp2} < TP3={scal_tp3} harus strict ascending"
        )
    
    if not (intra_tp1 < intra_tp2 < intra_tp3):
        raise ValueError(
            f"INTRADAY TP order salah: TP1={intra_tp1} < TP2={intra_tp2} < TP3={intra_tp3} harus strict ascending"
        )
    
    return s
