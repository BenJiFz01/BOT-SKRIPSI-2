"""entry_setup.py — Klasifikasi setup trigger (LABEL ADITIF, display-only).

Menambah tag setup yang lebih spesifik pada sinyal LIVE yang SUDAH lolos semua
gate (trigger_score, confluence_score, gate, threshold TIDAK disentuh):

  BREAKOUT     — close menembus level swing terdekat dgn body candle kuat dan
                 range luas (konfirmasi tembus — bukan doji/stub).
  BREAK_RETEST — level swing sudah ditembus (breakout/breakdown), harga sekarang
                 RETEST level tsb — level baru jadi support/resistance sehingga
                 retest = zona entry konfirmasi.
  MOMENTUM     — rangkaian ≥ 2 candle kuat beruntun searah.

KONTRAT:
  - Murni LABELING. Tidak mempengaruhi trigger_score, confluence_score, gate,
    ataupun threshold apa pun di engine.
  - Kembalikan (mode, note); mode "" artinya tak ada pola spesifik → engine
    memakai mode dasarnya (CONTINUATION/PULLBACK/REVERSAL).
  - Hanya dipanggil di titik emit LIVE untuk kategorisasi display + conflict
    resolver (anti-duplikat).

PENTING: modul ini MANDIRI (tanpa dependensi swing_utils) supaya tidak bergantung
pada API fungsi swing yang bisa berubah; implementasi swing deteksi di-inline.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

_BREAKOUT_MIN_BODY_ATR   = 0.30    # body candle (dalam ATR) utk dianggap tembus
_BREAKOUT_MIN_RANGE_ATR  = 0.70    # range (high-low, dalam ATR) konfirmasi tembus
_BREAKOUT_LOOKBACK_HIGH  = 40      # cari swing high dalam N bar terakhir
_BREAKOUT_LOOKBACK_LOW   = 40      # cari swing low dalam N bar terakhir
_BREAKOUT_MIN_CHURN_BARS = 12      # swing level dianggap "baru" jika dalam N bar
_RETEST_ZONE_ATR         = 0.50    # jarak close ke level yg dianggap retest
_RETEST_LOOKBACK_BARS    = 30      # batas "baru saja ditembus" utk retest
_MOMENTUM_MIN_STREAK     = 2       # min candle kuat beruntun searah
_MOMENTUM_MIN_BODY_ATR   = 0.40    # body min per candle utk momentum


def _swing_high_prices_inline(df: pd.DataFrame) -> list[float]:
    """Swing high (fraktal) dari kolom high — list harga."""
    if len(df) < 12:
        return []
    h = df["high"].to_numpy(dtype=float)
    out: list[float] = []
    for i in range(2, len(h) - 2):
        if h[i] > h[i - 1] and h[i] > h[i - 2] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            out.append(float(h[i]))
    return out


def _swing_low_prices_inline(df: pd.DataFrame) -> list[float]:
    """Swing low (fraktal) dari kolom low — list harga."""
    if len(df) < 12:
        return []
    lo = df["low"].to_numpy(dtype=float)
    out: list[float] = []
    for i in range(2, len(lo) - 2):
        if lo[i] < lo[i - 1] and lo[i] < lo[i - 2] and lo[i] < lo[i + 1] and lo[i] < lo[i + 2]:
            out.append(float(lo[i]))
    return out


def _body_atr(row: pd.Series, atr: float) -> float:
    if atr <= 0:
        return 0.0
    return abs(float(row["close"]) - float(row["open"])) / atr


def _range_atr(row: pd.Series, atr: float) -> float:
    if atr <= 0:
        return 0.0
    return (float(row["high"]) - float(row["low"])) / atr


def classify_entry_setup(
    df: pd.DataFrame,
    direction: str,
    atr: float,
) -> tuple[str, str]:
    """Klasifikasikan setup trigger yang sudah lolos semua gate.

    Returns:
        (mode, note): mode ∈ {"BREAKOUT","BREAK_RETEST","MOMENTUM",""}
        note = deskripsi singkat ("" jika mode kosong).
        Prioritas: BREAKOUT > BREAK_RETEST > MOMENTUM > "".
    """
    if df is None or len(df) < 30 or atr <= 0:
        return ("", "")
    need = {"high", "low", "open", "close"}
    if not need.issubset(df.columns):
        return ("", "")

    last_close = float(df["close"].iloc[-1])
    body_a     = _body_atr(df.iloc[-1], atr)
    rng_a      = _range_atr(df.iloc[-1], atr)

    highs = _swing_high_prices_inline(df)
    lows  = _swing_low_prices_inline(df)

    # ---- 1) BREAKOUT: close menembus swing level terdekat dgn body+range kuat ----
    if direction == "BUY":
        broken = [lv for lv in highs if lv < last_close]
        if broken and body_a >= _BREAKOUT_MIN_BODY_ATR and rng_a >= _BREAKOUT_MIN_RANGE_ATR:
            level = max(broken)
            recent = [h for h in highs[-min(_BREAKOUT_MIN_CHURN_BARS, len(highs)):]]
            if level in recent:
                return (
                    "BREAKOUT",
                    f"Close {last_close:.2f} menembus swing high {level:.2f} "
                    f"(body {body_a:.2f}×Atr, range {rng_a:.2f}×Atr)",
                )
    elif direction == "SELL":
        broken = [lv for lv in lows if lv > last_close]
        if broken and body_a >= _BREAKOUT_MIN_BODY_ATR and rng_a >= _BREAKOUT_MIN_RANGE_ATR:
            level = min(broken)
            recent = [lo for lo in lows[-min(_BREAKOUT_MIN_CHURN_BARS, len(lows)):]]
            if level in recent:
                return (
                    "BREAKOUT",
                    f"Close {last_close:.2f} menembus swing low {level:.2f} "
                    f"(body {body_a:.2f}×Atr, range {rng_a:.2f}×Atr)",
                )

    # ---- 2) BREAK_RETEST: level sudah ditembus, sekarang retest level tsb ----
    zone = _RETEST_ZONE_ATR * atr
    if direction == "BUY":
        for lv in highs[-min(_RETEST_LOOKBACK_BARS, len(highs)):]:
            if lv < last_close and abs(last_close - lv) <= zone:
                return (
                    "BREAK_RETEST",
                    f"Retest swing high {lv:.2f} setelah breakout "
                    f"(jarak {abs(last_close-lv):.2f})",
                )
    elif direction == "SELL":
        for lv in lows[-min(_RETEST_LOOKBACK_BARS, len(lows)):]:
            if lv > last_close and abs(last_close - lv) <= zone:
                return (
                    "BREAK_RETEST",
                    f"Retest swing low {lv:.2f} setelah breakdown "
                    f"(jarak {abs(last_close-lv):.2f})",
                )

    # ---- 3) MOMENTUM: strek candle kuat searah beruntun ----
    streak = 0
    for i in range(len(df) - 1, 0, -1):
        row = df.iloc[i]
        if _body_atr(row, atr) < _MOMENTUM_MIN_BODY_ATR:
            break
        is_bull = float(row["close"]) > float(row["open"])
        is_bear = float(row["close"]) < float(row["open"])
        if direction == "BUY" and not is_bull:
            break
        if direction == "SELL" and not is_bear:
            break
        streak += 1

    if streak >= _MOMENTUM_MIN_STREAK:
        return (
            "MOMENTUM",
            f"{streak} candle kuat beruntun (min {_MOMENTUM_MIN_STREAK})",
        )

    return ("", "")
