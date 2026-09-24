"""─ Market condition detector & Market State (pemilih jalur entry)."""

from __future__ import annotations

import pandas as pd

from src.engine.bias import _bias_from_tf
from src.engine.utils import _atr_proxy, _latest_closed, _safe
from src.features.entry_setup import classify_entry_setup


def detect_market_condition(df: pd.DataFrame, atr_period: int = 20) -> str:
    """Deteksi market: volatile (ATR >1.5×rata2), sideways (ADX<20 atau ATR <0.7×rata2), else normal."""
    col = "atr_14" if "atr_14" in df.columns else None
    if col is None or len(df) < atr_period + 3:
        return "normal"
    series = df[col].dropna()
    if len(series) < atr_period + 2:
        return "normal"

    current_atr = float(series.iloc[-2])
    avg_atr     = float(series.iloc[-(atr_period + 2):-2].mean())
    if avg_atr <= 0:
        return "normal"

    ratio = current_atr / avg_atr
    if ratio > 1.5:
        return "volatile"

    # ADX rendah = tren lemah, override ke sideways
    if "adx_14" in df.columns:
        adx_val = df["adx_14"].iloc[-2]
        if pd.notna(adx_val) and float(adx_val) < 20:
            return "sideways"

    if ratio < 0.7:
        return "sideways"
    return "normal"

def _decisive_adx(
    trigger_tf: str,
    data_by_tf: dict,
    block: float,
    gray: float,
) -> tuple[str | None, int]:
    """ADX TF penentu tren (H1 utk M5/M15, H4 utk H1): <block → block; block..gray → +1 confluence."""
    _dec_tf, _dec_adx = _decisive_adx_value(trigger_tf, data_by_tf)
    if _dec_adx is None:
        return None, 0
    if _dec_adx < block:
        return f"MARKET_TRANSITION(adx_{_dec_tf}={_dec_adx:.1f})", 0
    if _dec_adx < gray:
        return None, 1
    return None, 0


def _decisive_adx_value(
    trigger_tf: str,
    data_by_tf: dict,
) -> tuple[str | None, float | None]:
    """TF penentu tren + nilai ADX-nya (H1 utk M5/M15, H4 utk H1). """
    _dec_map = {"M5": "H1", "M15": "H1", "H1": "H4"}
    _dec_tf  = _dec_map.get(trigger_tf.upper())
    if _dec_tf is None:
        return None, None
    _dec_df  = data_by_tf.get(_dec_tf)
    _dec_adx = None
    if _dec_df is not None and "adx_14" in _dec_df.columns and len(_dec_df) > 2:
        _raw = _dec_df["adx_14"].iloc[-2]
        if pd.notna(_raw):
            _dec_adx = float(_raw)
    return _dec_tf, _dec_adx


def _momentum_streak(df: pd.DataFrame, direction: str, atr: float) -> int:
    """Jumlah body-atr dari N candle tertutup terakhir yang searah bias (>=0.4xATR).
    Candle kuat lawan arah (>=0.2xATR) mematahkan streak."""
    if len(df) < 10 or atr <= 0:
        return 0
    streak = 0
    for _, row in list(df.iloc[-9:-1].iterrows())[::-1]:
        o = _safe(row, "open")
        c = _safe(row, "close")
        if o is None or c is None:
            continue
        b = (c - o) / atr
        if (direction == "BUY" and b > 0.4) or (direction == "SELL" and b < -0.4):
            streak += 1
        elif abs(b) >= 0.2:
            break
    return streak


def _impulse_atr(df: pd.DataFrame, direction: str, atr: float) -> float:
    """Jarak close terakhir dari low/high 20-bar (dalam ATR) — kekuatan impuls."""
    if len(df) < 22 or atr <= 0:
        return 0.0
    close = _safe(df.iloc[-2], "close")
    if close is None:
        return 0.0
    if direction == "BUY":
        low20 = float(df["low"].iloc[-22:-2].min())
        return (close - low20) / atr
    high20 = float(df["high"].iloc[-22:-2].max())
    return (high20 - close) / atr


def _market_state(
    df:               pd.DataFrame,
    trigger_tf:       str,
    data_by_tf:       dict,
    adx_block:        float,
    adx_gray:         float,
) -> tuple[str, str]:
    """Market State Detector (2026-09-24) — klasifikasi kondisi pasar untuk dispatch logic.

    Return (state, note) dengan prioritas:
      TRANSITION > BREAKOUT > HIGH_MOMENTUM > TREND_BULL/BEAR > RANGE > CLEAN.
    Basis: ADX penentu (H1 utk M5/M15, H4 utk H1) + bias TF sinyal + streak momentum +
    probe breakout + ekspansi ATR. Murni klasifikasi — GATE & threshold menyesuaikan di
    pemanggil, fungsi ini TIDAK meloloskan/menolak sinyal.

    Dispatcher engine menukar jalur entry per state (CLEAN → pakai perilaku lama).
    """
    dec_tf, dec_adx = _decisive_adx_value(trigger_tf, data_by_tf)
    atr   = _atr_proxy(df)
    last  = _latest_closed(df) if len(df) >= 2 else None
    close = _safe(last, "close") if last is not None else None

    sig_adx = None
    if "adx_14" in df.columns and len(df) > 2:
        _v = df["adx_14"].iloc[-2]
        if pd.notna(_v):
            sig_adx = float(_v)

    # TRANSITION: ADX penentu < block = tren kehabisan tenaga; continuation diblokir
    # engine (reversal/breakout jalur ketat; reversal off secara default).
    if dec_adx is not None and dec_adx < adx_block:
        return ("TRANSITION", f"dec_adx_{dec_tf}={dec_adx:.1f},sig_adx={sig_adx if sig_adx is not None else -1:.1f}")

    bias = _bias_from_tf(df)
    if bias is None:
        # RANGE hanya bila struktur signal-TF benar-benar sideways (ADX rendah).
        if sig_adx is not None and sig_adx < adx_block:
            return ("RANGE", f"no_bias,sig_adx={sig_adx:.1f}")
        if sig_adx is None or sig_adx < adx_gray:
            return ("RANGE", f"no_bias,sig_adx={sig_adx if sig_adx is not None else -1:.1f}")
        return ("CLEAN", "no_bias")

    direction = "BUY" if bias == "BULL" else "SELL"
    notes: list[str] = [f"bias={bias}"]

    # BREAKOUT: close menembus swing terdekat + body & range kuat (reuse classifier
    # yg sama persis dgn label display — kini jadi STATE, bukan hanya label).
    if close is not None and atr > 0:
        try:
            _bo, _bo_note = classify_entry_setup(df, direction, atr)
        except Exception:
            _bo, _bo_note = "", ""
        if _bo == "BREAKOUT" and dec_adx is not None and dec_adx >= adx_block:
            return ("BREAKOUT", f"{dec_tf}_adx={dec_adx:.1f},{_bo_note}")

    _streak = _momentum_streak(df, direction, atr)
    _imp    = _impulse_atr(df, direction, atr)
    notes.append(f"streak={_streak},imp={_imp:.2f}")

    # HIGH_MOMENTUM: tren terkonfirmasi + dorongan kuat (streak ≥2 / impuls ≥1.8×ATR).
    if dec_adx is not None and dec_adx >= adx_gray and (_streak >= 2 or _imp >= 1.8):
        _vol = detect_market_condition(df) == "volatile"
        notes.append(f"vol={_vol}")
        if _vol or _streak >= 2:
            return ("HIGH_MOMENTUM", ",".join(notes))
        return ("TREND_BULL" if direction == "BUY" else "TREND_BEAR", ",".join(notes))

    # TREND: tren terkonfirmasi, tenang atau streak kecil.
    if dec_adx is not None and dec_adx >= adx_block:
        return ("TREND_BULL" if direction == "BUY" else "TREND_BEAR", ",".join(notes))

    return ("CLEAN", ",".join(notes))
