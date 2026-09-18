"""anytf_mta_engine.py — Rule-Based Decision Engine (Multi-Timeframe Analysis).

5 gate: Validasi -> HTF Bias -> Trigger Score -> Confluence Score -> SL/TP & RR.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz

from src.features.fibonacci import (
    fib_confluence_score, fib_levels, fib_lookback_for_tf, last_swing,
)
from src.features.session import is_active_session, is_asian_session, session_name, session_strictness
from src.features.zones_snr import snr_confluence_score
from src.features.zones_snd import snd_confluence_score
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp, swing_based_sltp
from src.strategy.multi_timeframe import higher_timeframes

_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}

# ── Circuit breaker DISABLED ──────────────────────────────────────────────────
# Circuit breaker di-nonaktifkan untuk memaksimalkan data collection.
# Sinyal akan masuk terus tanpa pause berdasarkan consecutive loss.
# Functions tetap ada untuk backward compatibility tapi tidak digunakan.

_CONSEC_LOSS: dict[str, dict] = {}
_CONSEC_LOSS_DATE: dict[str, str] = {}


def record_loss(symbol: str) -> None:
    """Disabled - kept for backward compatibility."""
    pass


def reset_consec_loss(symbol: str) -> None:
    """Disabled - kept for backward compatibility."""
    pass


def get_consec_loss_count(symbol: str) -> int:
    """Always return 0 - circuit breaker disabled."""
    return 0

# ── Cooldown persistence ──────────────────────────────────────────────────────
_COOLDOWN_PATH = Path("logs/cooldown_state.json")


def _load_cooldown_state() -> None:
    """Baca cooldown_state.json saat startup ke _LAST_SIGNAL_TIME.
    Semua timestamp disimpan sebagai tz-naive (UTC) agar konsisten
    dengan close_time_ts dari MT5 yang juga tz-naive.
    """
    if not _COOLDOWN_PATH.exists():
        return
    try:
        data = json.loads(_COOLDOWN_PATH.read_text(encoding="utf-8"))
        for key_str, ts_str in data.items():
            parts = key_str.split("|")
            if len(parts) == 2:
                ts = pd.to_datetime(ts_str)
                # Normalisasi ke tz-naive
                if ts.tzinfo is not None:
                    ts = ts.tz_convert("UTC").tz_localize(None)
                _LAST_SIGNAL_TIME[(parts[0], parts[1])] = ts
    except Exception:
        pass


def _save_cooldown_state() -> None:
    """Simpan _LAST_SIGNAL_TIME ke cooldown_state.json.
    Semua timestamp disimpan sebagai string ISO UTC tz-naive.
    """
    try:
        _COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for (sym, tf), ts in _LAST_SIGNAL_TIME.items():
            # Pastikan selalu tz-naive saat disimpan
            ts_naive = ts.tz_localize(None) if ts.tzinfo is not None else ts
            data[f"{sym}|{tf}"] = ts_naive.isoformat()
        tmp = _COOLDOWN_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_COOLDOWN_PATH)
    except Exception:
        pass


# Load cooldown state saat modul pertama kali diimport (saat bot startup)
_load_cooldown_state()


def detect_market_condition(df: pd.DataFrame, atr_period: int = 20) -> str:
    """Deteksi kondisi market: volatile / sideways / normal.

    Gabungkan ATR ratio dan ADX:
    - ATR tinggi (>1.5× rata-rata) → volatile
    - ADX rendah (<20) → sideways (tren lemah), override ATR normal
    - ATR rendah (<0.7× rata-rata) → sideways
    - Sisanya → normal
    """
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


def calc_rr(direction: str, entry: float, sl: float, tp: float) -> float | None:
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
    except Exception:
        return None
    d = direction.upper().strip()
    if d == "BUY":
        risk, reward = entry - sl, tp - entry
    elif d == "SELL":
        risk, reward = sl - entry, entry - tp
    else:
        return None
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _atr_proxy(df: pd.DataFrame, n: int = 14) -> float:
    if "atr_14" in df.columns:
        v = df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            return float(v)
    if len(df) < 3:
        return 0.0
    w = df.iloc[-n:] if len(df) > n else df
    v = (w["high"].astype(float) - w["low"].astype(float)).mean()
    return float(v) if pd.notna(v) and v > 0 else 0.0


def _latest_closed(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-2]


def _safe(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    return None if (v is None or pd.isna(v)) else float(v)


def _reject(df: pd.DataFrame, reason: str) -> None:
    df.attrs["reject_reason"] = reason


def _bias_from_tf(df: pd.DataFrame) -> str | None:
    if len(df) < 200:
        return None

    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema20  = _safe(last, "ema_20")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")

    if any(v is None for v in [close, ema50, ema200]):
        return None

    is_bull = close > ema200 and ema50 > ema200  
    is_bear = close < ema200 and ema50 < ema200  

    if not (is_bull or is_bear):
        return None

    gap_pct = abs(ema50 - ema200) / close  

    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()

    slope_ok = False
    if len(ema50_recent) >= 3:
        diffs   = ema50_recent.diff().dropna()
        n_total = len(diffs)
        if is_bull and (diffs > 0).sum() / n_total >= 0.5:
            slope_ok = True
        if is_bear and (diffs < 0).sum() / n_total >= 0.5:
            slope_ok = True
    else:
        slope_ok = True

    if gap_pct >= 0.0005 and slope_ok:
        candidate = "BULL" if is_bull else "BEAR"
    elif atr := _atr_proxy(df):
        if is_bull and close > ema200 + atr:
            candidate = "BULL"
        elif is_bear and close < ema200 - atr:
            candidate = "BEAR"
        else:
            candidate = None
    else:
        candidate = None

    return candidate


def _bias_why_neutral(df: pd.DataFrame) -> str:
    """Diagnostik kenapa _bias_from_tf mengembalikan None — dipakai di log
    detail vote bias supaya 'D1→NEUTRAL' bisa dibedakan: konfig lama (ema_50==ema_200)
    vs market memang flat. Hindari '()' di dalam return (pemangkasan di main.py)."""
    if len(df) < 200:
        return "bars_kurang_200"
    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")
    if any(v is None for v in [close, ema50, ema200]):
        return "kolom_MA_tidak_lengkap"
    if abs(ema50 - ema200) <= abs(close) * 1e-6:
        return f"ema50_sama_ema200_kode_lama e50={ema50:.2f}"
    is_bull = close > ema200 and ema50 > ema200
    is_bear = close < ema200 and ema50 < ema200
    if not (is_bull or is_bear):
        return f"harga_antara_MA c={close:.0f} e50={ema50:.0f} e200={ema200:.0f}"
    gap_pct = abs(ema50 - ema200) / close
    if gap_pct < 0.0005:
        return f"gap_MA_kecil {gap_pct*100:.3f}pct"
    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()
    if len(ema50_recent) >= 3:
        diffs = ema50_recent.diff().dropna()
        n     = float(len(diffs))
        slope_too_weak = (is_bull and (diffs > 0).sum() / n < 0.5) or \
                         (is_bear and (diffs < 0).sum() / n < 0.5)
        if slope_too_weak:
            return f"slope_ema50_lemah {diffs.iloc[-1]:+.2f}/bar"
    return "unknown"


def _momentum_recovery_bias(
    df_scalp: pd.DataFrame,
    df_h1:    pd.DataFrame | None,
) -> tuple[str | None, str]:
    """Deteksi momentum recovery untuk scalping (M5/M15) saat H1 NEUTRAL.

    Diubah dari "5 syarat wajib semua" → sistem skor min 3/4,
    konsisten dengan pendekatan _trigger_score (X dari N, bukan wajib N/N).

    Gerbang wajib (gugur total jika gagal):
      - EMA20 vs EMA50 → menentukan arah momentum jangka pendek

    Skor (min 3 dari 4 harus terpenuhi):
      1. slope  — EMA50 slope searah ≥60% dari 5 candle terakhir
      2. impulse — harga sudah bergerak >1.5×ATR dari low/high 20 candle
      3. rsi    — RSI searah dan bergerak searah dari candle sebelumnya
      4. h1_ok  — EMA50 H1 tidak aktif berlawanan arah (threshold 80%)

    Mengembalikan (bias, detail) sehingga detail bisa di-log di _vote_bias.
    Detail format: "slope+,impulse-,rsi+,h1_ok+" untuk diagnostik.
    """
    if len(df_scalp) < 30:
        return None, "TOO_FEW_BARS"

    last = _latest_closed(df_scalp)
    prev = df_scalp.iloc[-3] if len(df_scalp) > 3 else last

    close = _safe(last, "close")
    ema20 = _safe(last, "ema_20")
    ema50 = _safe(last, "ema_50")
    rsi   = _safe(last, "rsi_14")
    rsi_p = _safe(prev, "rsi_14")
    atr   = _atr_proxy(df_scalp)

    if any(v is None for v in [close, ema20, ema50, rsi, rsi_p]) or atr <= 0:
        return None, "DATA_INCOMPLETE"

    # ── Gerbang wajib: arah momentum ─────────────────────────────────────────
    ema20_bull = ema20 > ema50
    ema20_bear = ema20 < ema50
    if not (ema20_bull or ema20_bear):
        return None, "NO_MOMENTUM_DIR"
    is_bull = ema20_bull

    # ── EMA50 slope ───────────────────────────────────────────────────────────
    try:
        idx         = df_scalp.index.get_loc(last.name) if hasattr(last, "name") and last.name in df_scalp.index else -2
        ema50_slice = df_scalp["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_slice = df_scalp["ema_50"].iloc[-7:-2].dropna()

    slope_ok = False
    if len(ema50_slice) >= 3:
        diffs    = ema50_slice.diff().dropna()
        n        = len(diffs)
        slope_ok = ((diffs > 0).sum() / n >= 0.6) if is_bull else ((diffs < 0).sum() / n >= 0.6)

    # ── Impulse ───────────────────────────────────────────────────────────────
    low_20  = float(df_scalp["low"].iloc[-22:-2].min())  if len(df_scalp) >= 22 else float(df_scalp["low"].iloc[:-2].min())
    high_20 = float(df_scalp["high"].iloc[-22:-2].max()) if len(df_scalp) >= 22 else float(df_scalp["high"].iloc[:-2].max())
    impulse_ok = (close > low_20 + 1.5 * atr) if is_bull else (close < high_20 - 1.5 * atr)

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_ok = (rsi > 50 and rsi > rsi_p) if is_bull else (rsi < 50 and rsi < rsi_p)

    # ── H1 tidak aktif berlawanan arah ───────────────────────────────────────
    # Toleransi: cukup satu syarat yang boleh gagal (skor >=3 dari 4),
    # sehingga jika H1 masih agak turun tapi 3 syarat lain solid, tetap lolos.
    h1_ok = True
    if df_h1 is not None and len(df_h1) >= 10:
        try:
            h1_last   = _latest_closed(df_h1)
            h1_idx    = df_h1.index.get_loc(h1_last.name) if hasattr(h1_last, "name") and h1_last.name in df_h1.index else -2
            h1_ema50s = df_h1["ema_50"].iloc[max(0, h1_idx - 4): h1_idx + 1].dropna()
            if len(h1_ema50s) >= 4:
                h1_diffs = h1_ema50s.diff().dropna()
                h1_n     = len(h1_diffs)
                if is_bull  and (h1_diffs < 0).sum() / h1_n >= 0.8:
                    h1_ok = False
                if not is_bull and (h1_diffs > 0).sum() / h1_n >= 0.8:
                    h1_ok = False
        except Exception:
            pass

    # ── Skor: min 3 dari 4 ────────────────────────────────────────────────────
    checks = {"slope": slope_ok, "impulse": impulse_ok, "rsi": rsi_ok, "h1_ok": h1_ok}
    score  = sum(checks.values())
    detail = ",".join(f"{k}{'+' if v else '-'}" for k, v in checks.items())

    if score >= 3:
        return ("BULL" if is_bull else "BEAR"), detail
    return None, detail


def _vote_bias(
    data_by_tf:        dict[str, pd.DataFrame],
    confirm_tfs:       list[str],
    trigger_tf:        str = "M5",
    min_confirm_votes: int = 1,
    scalping_h1_only:  bool = True,
    intraday_require_d1: bool = True,
) -> tuple[str | None, str]:
    """Vote bias dari HTF. Butuh min_confirm_votes TF sepakat, dan required_tf
    (H1 untuk M5/M15, H4 untuk H1) harus punya bias jelas (bukan NEUTRAL).

    Untuk scalping (M5/M15): cukup vote H1 saja (default) — data historis
    menunjukkan partisipasi H4 malah menekan WR (60% vs 72% saat H4 netral).
    Jika H1 NEUTRAL, coba deteksi momentum recovery lokal sebagai jalur ke-3.

    Untuk intraday: top-down penuh — H4 memerlukan D1 (anchoring tren besar).

    Returns (bias, detail_string).
    """
    trigger_up = trigger_tf.upper()
    is_scalping_tf = trigger_up in ("M5", "M15")

    # TF yang wajib punya bias jelas (bukan NEUTRAL) — tanpanya langsung reject
    _required_tf: dict[str, str] = {
        "M5":  "H1",
        "M15": "H1",
        "H1":  "H4",
    }
    if intraday_require_d1:
        _required_tf["H4"] = "D1"
    required_tf = _required_tf.get(trigger_up)

    if is_scalping_tf and scalping_h1_only:
        confirm_tfs = [tf for tf in confirm_tfs if tf.upper() == "H1"]

    votes:       dict[str, int] = {"BULL": 0, "BEAR": 0}
    details:     list[str]      = []
    votes_by_tf: dict[str, str] = {}

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING")
            continue
        b = _bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL({_bias_why_neutral(df)})")
            continue
        details.append(f"{tf}:{b}")
        votes[b]       += 1
        votes_by_tf[tf] = b

    # Required TF harus ada dan tidak NEUTRAL
    if required_tf is not None and votes_by_tf.get(required_tf) is None:
        # ── Momentum Recovery untuk scalping saat H1 NEUTRAL ─────────────
        # H1 NEUTRAL = EMA200 H1 belum flip, tapi mungkin ada impulse lokal
        # yang cukup kuat di M5/M15. Cek dengan kriteria lebih ketat.
        if is_scalping_tf and required_tf == "H1":
            df_scalp = data_by_tf.get(trigger_up)
            df_h1    = data_by_tf.get("H1")
            if df_scalp is not None:
                mom_bias, mom_detail = _momentum_recovery_bias(df_scalp, df_h1)
                if mom_bias is not None:
                    details.append(f"[MOM_RECOVERY:{mom_bias}({mom_detail})]")
                    return mom_bias, " ".join(details)
                else:
                    details.append(f"[MOM_RECOVERY_FAIL:{mom_detail}]")
        return None, " ".join(details) + f" [TF_FAIL:{required_tf}=NEUTRAL]"

    # Minimal votes harus terpenuhi
    if max(votes["BULL"], votes["BEAR"]) < min_confirm_votes:
        return None, " ".join(details)

    # Tie → reject
    if votes["BULL"] == votes["BEAR"]:
        return None, " ".join(details)

    bias = "BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"
    return bias, " ".join(details)


def _detect_trade_mode(trigger_tf: str) -> tuple[str, str]:
    tf = trigger_tf.upper()
    if tf in ("M5", "M15"):
        return "scalping", "M5"
    if tf == "H1":
        return "intraday", "M15"
    return "intraday", "H1"


def _trigger_score(df: pd.DataFrame, direction: str, min_score: int = 4) -> tuple[bool, int, str]:
    """Trigger Score Layer-1 (maks 6): EMA200, EMA50 pullback, EMA alignment, RSI, MACD, Candle."""
    direction = direction.upper()
    notes: list[str] = []
    score = 0

    if len(df) < 30:
        return False, 0, "TOO_FEW_BARS"

    last = _latest_closed(df)
    prev = df.iloc[-3] if len(df) > 3 else last

    close   = _safe(last, "close")
    open_   = _safe(last, "open")
    ema20   = _safe(last, "ema_20")
    ema50   = _safe(last, "ema_50")
    ema200  = _safe(last, "ema_200")
    rsi     = _safe(last, "rsi_14")
    rsi_p   = _safe(prev, "rsi_14")
    mhist   = _safe(last, "macdhist")
    mhist_p = _safe(prev, "macdhist")
    atr     = _atr_proxy(df)

    if close is None:
        return False, 0, "NO_CLOSE"

    # EMA200 — wajib
    if ema200 is not None:
        tolerance = 0.2 * atr if atr > 0 else 0.0
        in_band   = abs(close - ema200) <= tolerance  
        on_side   = (direction == "BUY"  and close > ema200 - tolerance) or \
                    (direction == "SELL" and close < ema200 + tolerance)
        if on_side or in_band:
            score += 1; notes.append("EMA200+")
        else:
            notes.append("EMA200-")
            return False, score, " ".join(notes)
    else:
        notes.append("EMA200_NA")

    # EMA50 pullback (dalam 1.5×ATR)
    if ema50 is not None and atr > 0:
        if abs(close - ema50) <= 1.5 * atr:
            score += 1; notes.append("EMA50+")
        else:
            notes.append("EMA50-")

    # EMA alignment
    if all(v is not None for v in [ema20, ema50, ema200]):
        if (direction == "BUY"  and ema20 > ema50 > ema200) or \
           (direction == "SELL" and ema20 < ema50 < ema200):
            score += 1; notes.append("ALIGN+")
        else:
            notes.append("ALIGN-")

    # RSI
    if rsi is not None and rsi_p is not None:
        if (direction == "BUY"  and rsi < 65 and rsi > rsi_p) or \
           (direction == "SELL" and rsi > 35 and rsi < rsi_p):
            score += 1; notes.append(f"RSI+({rsi:.0f})")
        else:
            notes.append(f"RSI-({rsi:.0f})")

    # MACD histogram
    if mhist is not None and mhist_p is not None:
        if (direction == "BUY"  and mhist > mhist_p) or \
           (direction == "SELL" and mhist < mhist_p):
            score += 1; notes.append("MACD+")
        else:
            notes.append("MACD-")

    # Candle
    if open_ is not None:
        if (direction == "BUY"  and close > open_) or \
           (direction == "SELL" and close < open_):
            score += 1; notes.append("CDL+")
        else:
            notes.append("CDL-")

    return score >= min_score, score, " ".join(notes)


def _get_active_patterns(direction: str, last_row: pd.Series) -> list[str]:
    from src.features.patterns import PATTERN_FUNCS
    names: list[str] = []
    for name in PATTERN_FUNCS:
        val = _safe(last_row, name)
        if val is None:
            continue
        if direction == "BUY"  and val >= 100:
            names.append(name.replace("CDL", ""))
        elif direction == "SELL" and val <= -100:
            names.append(name.replace("CDL", ""))
    return names


def _confluence_score(
    df:          pd.DataFrame,
    direction:   str,
    entry:       float,
    atr:         float,
    tf:          str  = "",
    is_scalping: bool = False,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
    now_utc:     datetime | None = None,   # untuk cek Asian session strictness
) -> tuple[int, str, dict]:
    """Confluence Score Layer-2 — berbobot sesuai akurasi historis komponen.

    Bobot per komponen (OPTIMIZED untuk balance quality + quantity):
      Pattern   : 1.5  (akurasi 48.8%, proven reliable)
      Fibonacci : 1.5  (akurasi 48.7%, proven reliable)
      Divergence: 1.5  (boosted - early reversal signal, high value)
      SNR       : weighted (0.3x weak, 0.6x med, 1.0x strong)
      SND       : 2.0  (boosted - strong institutional zones)

    Multi-TF alignment bonus: +1.0 jika 3+ TF setuju (strong confluence)
    
    Skor float dibulatkan ke int di akhir untuk kompatibilitas threshold.
    Threshold yang ada (min_confluence_score) sudah dikalibrasi untuk skala ini.
    """
    # ── Bobot komponen (OPTIMIZED) ────────────────────────────────────────────
    _W_PATTERN   = 1.5   # Pattern: 48.8%, proven
    _W_FIB       = 1.5   # Fibonacci: 48.7%, proven
    _W_DIV       = 1.5   # Divergence: BOOSTED (early signal, high value)
    _W_SNR       = 1.0   # SNR: weighted internally (0.3x/0.6x/1.0x)
    _W_SND       = 2.0   # SND: BOOSTED (institutional zones, high impact)
    direction = direction.upper()
    score: float = 0.0   # float untuk akumulasi bobot, dibulatkan ke int di akhir
    notes: list[str] = []
    detail: dict = {
        "pattern_names": "",
        "fib_detail":    "",
        "snr_detail":    "",
        "snd_detail":    "",
        "div_detail":    "",
    }
    last = _latest_closed(df)

    # Pattern — bobot 1.5 (akurasi tertinggi)
    bull_count = int(_safe(last, "pattern_bull_count") or 0)
    bear_count = int(_safe(last, "pattern_bear_count") or 0)
    count = bull_count if direction == "BUY" else bear_count
    if count >= 2:
        score += 2 * _W_PATTERN; notes.append("Pattern++")
    elif count >= 1:
        score += 1 * _W_PATTERN; notes.append("Pattern+")
    else:
        notes.append("Pattern-")
    # _get_active_patterns cek kolom individual (CDLMARUBOZU, dll) di candle terakhir.
    # Kalau kosong padahal count > 0, fallback scan ulang dari PATTERN_FUNCS langsung
    # agar pattern_names di template selalu konsisten dengan skor yang dihitung.
    pattern_names = _get_active_patterns(direction, last)
    if not pattern_names and count > 0:
        from src.features.patterns import PATTERN_FUNCS
        for pname in PATTERN_FUNCS:
            val = _safe(last, pname)
            if val is None:
                continue
            if direction == "BUY" and val > 0:
                pattern_names.append(pname.replace("CDL", ""))
            elif direction == "SELL" and val < 0:
                pattern_names.append(pname.replace("CDL", ""))
    detail["pattern_names"] = ", ".join(pattern_names[:3]) if pattern_names else ""

    # Divergence — bobot 1.5
    div_keys = {
        "BUY":  [("rsi_bull_div", "RSI"), ("macd_bull_div", "MACD")],
        "SELL": [("rsi_bear_div", "RSI"), ("macd_bear_div", "MACD")],
    }
    div_parts: list[str] = []
    for col, label in div_keys.get(direction, []):
        if bool(_safe(last, col) or False):
            div_parts.append(label)
    if div_parts:
        score += 1 * _W_DIV; notes.append("Div+")
    else:
        notes.append("Div-")
    detail["div_detail"] = "+".join(div_parts)

    # Fibonacci — bobot 1.5 (akurasi tertinggi bersama Pattern)
    if atr > 0:
        fib_sc, fib_note = fib_confluence_score(
            direction=direction, entry_price=entry, df=df, atr=atr,
            is_scalping=is_scalping, data_by_tf=data_by_tf,
        )
        score += fib_sc * _W_FIB
        notes.append(f"Fib+({fib_note})" if fib_sc > 0 else "Fib-")
        detail["fib_detail"] = fib_note if fib_sc > 0 else ""
    else:
        notes.append("Fib_SKIP")

    # SNR — Bug #1+#2 fix: pass tf + data_by_tf
    if atr > 0:
        snr_sc, snr_note = snr_confluence_score(
            direction=direction, entry_price=entry,
            df=df, atr=atr, sl=sl, tp1_rr=tp1_rr,
            tf=tf, is_scalping=is_scalping,
            data_by_tf=data_by_tf,
        )
        # Bug #4 fix: SNR_BLOCKED jadi hard-reject di semua mode, bukan cuma scalping
        if "SNR_BLOCKED" in snr_note:
            detail["snr_detail"] = snr_note
            notes.append("SnR_BLOCKED")
            return -99, " ".join(notes), detail

        # SNR weighted scoring: level lemah tetap contribute tapi dengan bobot lebih kecil
        # - str < 35 (2-touch): 30% contribution
        # - str 35-49 (3-4 touch): 60% contribution  
        # - str >= 50 (5+ touch): 100% contribution
        # Ini mencegah hilangnya informasi total tapi tetap prioritaskan level kuat.
        if snr_sc > 0:
            _str_match = re.search(r"str=(\d+)", snr_note)
            _snr_strength = int(_str_match.group(1)) if _str_match else 99
            if _snr_strength < 35:
                snr_sc = snr_sc * 0.3  # 30% weight untuk 2-touch
                snr_note = snr_note.replace("SNR_OK", "SNR_WEAK")
                notes.append("SnR_WEAK(0.3x)")
            elif _snr_strength < 50:
                snr_sc = snr_sc * 0.6  # 60% weight untuk 3-4 touch
                notes.append("SnR_MED(0.6x)")
            else:
                notes.append("SnR+")  # 100% weight untuk 5+ touch
        else:
            notes.append("SnR-")

        score += snr_sc * _W_SNR
        detail["snr_detail"] = snr_note
    else:
        notes.append("SnR_SKIP")

    # SND — bobot 1.0
    if atr > 0:
        snd_sc, snd_note = snd_confluence_score(
            direction=direction, entry_price=entry,
            df=df, atr=atr, tf=tf, is_scalping=is_scalping,
            data_by_tf=data_by_tf,
        )
        score += snd_sc * _W_SND
        notes.append("SnD+" if snd_sc > 0 else "SnD-")
        detail["snd_detail"] = snd_note if snd_sc > 0 else ""
    else:
        notes.append("SnD_SKIP")

    # ── Asian session filter ──────────────────────────────────────────────────
    # session_strictness() = 'RELAXED' di Asian (06:00-14:00 WIB).
    # Di Asian: volatilitas rendah, fake breakout dominan.
    # Requirements STRICTER untuk CONTINUATION scalping:
    # - CONTINUATION: butuh +1 confluence & +1 trigger (avoid false breakout)
    # - Sinyal tanpa key level (SNR/SND) di-reject (no Fib-only signals)
    #
    # Cek pakai variabel skor (snr_sc/snd_sc), bukan string-matching notes,
    # agar tidak rapuh terhadap perubahan format tag di masa depan.
    #
    # now_utc diisi dari close_time candle (bukan datetime.now()) agar
    # konsisten dengan waktu candle yang dievaluasi — penting untuk backtest.
    asian_session = session_strictness(now_utc, tf=tf) == "RELAXED"
    
    if is_scalping and asian_session:
        # Reject kalau tidak ada key level (SNR/SND)
        has_key_level = (snr_sc > 0) or (snd_sc > 0)
        if not has_key_level:
            notes.append("ASIAN_NO_KEY_LEVEL")
            detail["snr_detail"] = detail.get("snr_detail", "") or "ASIAN_REJECT"
            return -99, " ".join(notes), detail
        
        # Asian CONTINUATION butuh score lebih tinggi (handled by caller via threshold adjustment)
        notes.append("ASIAN_SESSION")

    # ── BONUS: Multi-TF Alignment ─────────────────────────────────────────────
    # Jika 3+ timeframes agree pada direction yang sama, bonus +1.0 score
    # Ini menandakan strong consensus across multiple timeframes
    # 
    # H1 SPECIAL: Jika H1 signal dan align dengan H4+D1, bonus extra +0.5
    # untuk kompensasi historical H1 underperformance - H1 butuh HTF backing
    if data_by_tf and len(data_by_tf) >= 3:
        aligned_count = 0
        h4_aligned = False
        d1_aligned = False
        
        for other_tf, other_df in data_by_tf.items():
            if other_tf == tf or len(other_df) < 200:
                continue
            other_bias = _bias_from_tf(other_df)
            expected_bias = "BULL" if direction == "BUY" else "BEAR"
            
            if other_bias == expected_bias:
                aligned_count += 1
                if other_tf == "H4":
                    h4_aligned = True
                elif other_tf == "D1":
                    d1_aligned = True
        
        if aligned_count >= 3:
            score += 1.0
            notes.append(f"MTF_ALIGN({aligned_count})")
        
        # H1 special bonus: if H1 signal backed by both H4 and D1
        if tf == "H1" and h4_aligned and d1_aligned:
            score += 0.5
            notes.append("H1_HTF_BACKED")

    # ── BONUS: Fibonacci Golden Ratio ─────────────────────────────────────────
    # Jika entry price dekat golden ratio (0.618 retracement), bonus +0.5
    # Golden ratio adalah level psikologis & teknikal paling kuat
    if "fib_detail" in detail and detail["fib_detail"]:
        fib_detail_str = detail["fib_detail"]
        # Check if 0.618 mentioned in fib detail
        if "0.618" in fib_detail_str or "61.8" in fib_detail_str:
            score += 0.5
            notes.append("FIB_GOLDEN")

    # Bulatkan skor float ke int — threshold (min_confluence_score) tetap integer
    # Pembulatan ke bawah (floor) agar tidak ada "kredit lebih" dari bobot
    return int(score), " ".join(notes), detail


def _is_counter_trend_valid(
    df:                     pd.DataFrame,
    direction:              str,
    entry:                  float,
    atr:                    float,
    tf:                     str  = "",
    min_counter_confluence: int  = 3,
    is_scalping:            bool = True,
    data_by_tf:             dict[str, pd.DataFrame] | None = None,
) -> tuple[bool, str, int]:
    """Validasi counter trend: Divergence (MANDATORY), Fib, SND, SNR.
    
    Counter-trend trading inherently risky - need strong reversal evidence.
    Divergence adalah primary signal untuk reversal, wajib ada untuk validate CT setup.
    """
    score = 0
    notes: list[str] = []
    last  = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

    # Divergence (MANDATORY untuk counter-trend - primary reversal signal)
    if direction == "BUY":
        rsi_div  = bool(_safe(last, "rsi_bull_div")  or False)
        macd_div = bool(_safe(last, "macd_bull_div") or False)
    else:
        rsi_div  = bool(_safe(last, "rsi_bear_div")  or False)
        macd_div = bool(_safe(last, "macd_bear_div") or False)

    # MANDATORY CHECK: Must have at least one divergence for counter-trend
    if not (rsi_div or macd_div):
        return False, "NO_DIVERGENCE", 0

    if rsi_div and macd_div:
        score += 2; notes.append("DIV_BOTH+")
    elif rsi_div or macd_div:
        score += 1; notes.append("RSI_DIV+" if rsi_div else "MACD_DIV+")
    else:
        notes.append("DIV-")

    # Fibonacci — Bug #1+#3 fix: pass is_scalping + data_by_tf
    fib_sc, fib_note = fib_confluence_score(
        direction=direction, entry_price=entry, df=df, atr=atr,
        is_scalping=is_scalping, data_by_tf=data_by_tf,
    )
    if fib_sc >= 2:
        score += 2; notes.append(f"FIB_GOLD+({fib_note})")
    elif fib_sc == 1:
        score += 1; notes.append(f"FIB_NEAR+({fib_note})")
    else:
        notes.append(f"FIB-({fib_note})")

    # SND — Bug #1 fix: pass tf + data_by_tf
    snd_sc, snd_note = snd_confluence_score(
        direction=direction, entry_price=entry,
        df=df, atr=atr, tf=tf, is_scalping=is_scalping,
        data_by_tf=data_by_tf,
    )
    if snd_sc >= 1:
        score += 1; notes.append(f"SND+({snd_note})")
    else:
        notes.append(f"SND-({snd_note})")

    # SNR — Bug #1+#2 fix: pass tf + data_by_tf
    snr_sc, snr_note = snr_confluence_score(
        direction=direction, entry_price=entry,
        df=df, atr=atr, tf=tf, is_scalping=is_scalping,
        data_by_tf=data_by_tf,
    )
    if snr_sc >= 1:
        score += 1; notes.append(f"SNR+({snr_note})")
    else:
        notes.append(f"SNR-({snr_note})")

    return score >= min_counter_confluence, " ".join(notes), score


def scan_setup_plan(
    data_by_tf:        dict[str, pd.DataFrame],
    symbol:            str,
    enabled_tfs:       list[str],
    min_confirm_votes: int   = 1,
    atr_min_pct:       float = 0.0006,
    tp1_rr:            float = 1.5,
    tp2_rr:            float = 2.5,
    tp3_rr:            float = 4.0,
    sl_pips:           float = 50.0,
    tp1_pips:          float = 70.0,
    tp2_pips:          float = 100.0,
    tp3_pips:          float = 140.0,
    pip_size:          float = 0.1,
    session_filter:    bool  = True,
) -> list[Signal]:
    """Scan setup plan dari M15+H1 atau H1+H4. Returns list Signal dengan is_setup_plan=True."""
    enabled_tfs = [tf.upper() for tf in enabled_tfs]
    results: list[Signal] = []

    scan_pairs = []
    if "M15" in enabled_tfs and "H1" in enabled_tfs:
        scan_pairs.append(("M15", "M5",  "scalping", "H1"))
    if "H1"  in enabled_tfs and "H4" in enabled_tfs:
        scan_pairs.append(("H1",  "M15", "intraday", "H4"))

    now_utc = datetime.now(pytz.utc)

    for anchor_tf, exec_tf, trade_mode, required_htf in scan_pairs:
        df_anchor = data_by_tf.get(anchor_tf)
        df_htf    = data_by_tf.get(required_htf)
        if df_anchor is None or df_htf is None or len(df_anchor) < 200:
            continue
        if session_filter and not is_active_session(now_utc, anchor_tf):
            continue

        htf_bias = _bias_from_tf(df_htf)
        if htf_bias is None:
            continue
        anchor_bias = _bias_from_tf(df_anchor)
        if anchor_bias is not None and anchor_bias != htf_bias:
            continue

        direction  = "BUY" if htf_bias == "BULL" else "SELL"
        last       = _latest_closed(df_anchor)
        price_now  = float(last["close"])
        atr        = _atr_proxy(df_anchor)
        sess       = session_name(now_utc)
        close_time = str(pd.to_datetime(last["time"]).to_pydatetime().replace(tzinfo=pytz.utc).isoformat())

        if atr <= 0 or atr < price_now * atr_min_pct:
            continue

        ema50_val = _safe(last, "ema_50")
        fib_anchor:      float | None = None
        fib_anchor_name: str          = ""

        swing = last_swing(df_anchor, lookback=fib_lookback_for_tf(anchor_tf), direction=direction)
        if swing is not None:
            levels     = fib_levels(swing[0], swing[1], swing[2])
            anchor_ref = ema50_val if ema50_val is not None else price_now
            candidates: list[tuple[float, str, float]] = []
            for name, px in levels.items():
                dist = abs(px - anchor_ref)
                if dist <= 1.5 * atr:
                    try:
                        lv = float(name.replace("fib_", ""))
                    except ValueError:
                        lv = 99.0
                    weight = 0.0 if lv in {0.382, 0.5, 0.618} else dist
                    candidates.append((weight, name, px))
            if candidates:
                candidates.sort()
                fib_anchor      = candidates[0][2]
                fib_anchor_name = candidates[0][1]

        if fib_anchor is not None:
            pb_low  = fib_anchor - 0.25 * atr
            pb_high = fib_anchor + 0.25 * atr
            pullback_price = fib_anchor
        elif ema50_val is not None:
            if direction == "BUY":
                pb_low, pb_high = ema50_val - 0.3 * atr, ema50_val + 0.5 * atr
            else:
                pb_low, pb_high = ema50_val - 0.5 * atr, ema50_val + 0.3 * atr
            pullback_price = ema50_val
        else:
            if direction == "BUY":
                pb_low, pb_high = price_now - 1.2 * atr, price_now - 0.5 * atr
            else:
                pb_low, pb_high = price_now + 0.5 * atr, price_now + 1.2 * atr
            pullback_price = (pb_low + pb_high) / 2

        if direction == "BUY" and pb_high >= price_now:
            pb_high, pb_low = price_now - 0.2 * atr, price_now - 0.8 * atr
            pullback_price  = pb_high
        elif direction == "SELL" and pb_low <= price_now:
            pb_low, pb_high = price_now + 0.2 * atr, price_now + 0.8 * atr
            pullback_price  = pb_low

        plan = dynamic_atr_sltp(
            direction=direction, price_now=pullback_price, atr=atr,
            tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
        )
        if plan is None:
            plan = fixed_zone_sltp(
                direction=direction, price_now=pullback_price,
                entry_zone_pips=30, sl_pips=sl_pips,
                tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
                pip_size=pip_size,
            )
        if plan is None:
            continue

        plan.entry_low  = round(pb_low,  2)
        plan.entry_high = round(pb_high, 2)

        entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
        rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
        if rr is None or rr < 1.5:
            continue

        confirm_tfs = higher_timeframes(anchor_tf, enabled_tfs)
        _, bias_detail = _vote_bias(
            data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
            trigger_tf=anchor_tf, min_confirm_votes=min_confirm_votes,
        )
        conf_score, conf_notes, conf_detail = _confluence_score(
            df=df_anchor, direction=direction, entry=price_now, atr=atr,
            tf=anchor_tf, is_scalping=(trade_mode == "scalping"),
            sl=float(plan.sl), tp1_rr=tp1_rr, data_by_tf=data_by_tf,
            now_utc=now_utc,
        )

        # conf_score -99 = SNR_BLOCKED — untuk Setup clamp ke 0, tidak direject
        # (Setup = sinyal early, belum tentu langsung dieksekusi)
        if conf_score == -99:
            conf_score = 0

        fib_tag = f" | Fib={fib_anchor_name}@{fib_anchor:.2f}" if fib_anchor else " | zona EMA50"
        results.append(Signal(
            symbol=symbol, tf=anchor_tf, direction=direction, close_time=close_time,
            entry=float(entry_for_rr), entry_low=float(plan.entry_low),
            entry_high=float(plan.entry_high), sl=float(plan.sl),
            tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
            rr=float(rr), sl_method="dynamic_atr", atr_value=float(atr),
            tp1_rr=float(tp1_rr), tp2_rr=float(tp2_rr), tp3_rr=float(tp3_rr),
            trigger_score=0, trigger_max=6, confluence_score=conf_score,
            htf_bias=bias_detail,
            trigger_notes=f"SETUP_PLAN via {required_htf}:{htf_bias}{fib_tag}",
            confluence_notes=conf_notes,
            pattern_names=conf_detail["pattern_names"],
            fib_detail=conf_detail["fib_detail"], snr_detail=conf_detail["snr_detail"],
            snd_detail=conf_detail["snd_detail"], divergence_detail=conf_detail["div_detail"],
            session_name=sess, signal_type="SETUP", signal_mode="CONTINUATION",
            trade_mode=trade_mode,
            exec_tf=exec_tf, is_setup_plan=True,
            reason=f"SETUP_PLAN {anchor_tf} {direction} | HTF:{required_htf}:{htf_bias}",
        ))

    return results


def evaluate_any_tf_mta(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    trigger_tf:           str,
    enabled_tfs:          list[str],
    min_rr:               float = 1.5,
    min_confirm_votes:    int   = 1,
    min_trigger_score:    int   = 4,
    min_confluence_score: int   = 2,
    cooldown_bars:        int   = 3,
    atr_min_pct:          float = 0.0006,
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    max_sl_points:        float = 50.0,
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    session_filter:       bool  = True,
    counter_trend_enabled:         bool             = True,
    min_counter_confluence:        int              = 3,
    counter_trend_min_rr:          float            = 2.0,
    counter_trend_tfs:             list[str] | None = None,
    scalping_min_trigger_score:    int              = 3,
    scalping_min_confluence_score: int              = 2,
    scalping_atr_min_points:       float            = 5.0,
    scalping_sl_atr_mult:          float            = 1.2,
    scalping_cooldown_bars:        int              = 5,
    scalping_cooldown_bars_m5:     int              = 9,
    scalping_cooldown_bars_m15:    int              = 5,
    scalping_tp1_rr:               float            = 1.0,
    scalping_tp2_rr:               float            = 1.6,
    scalping_tp3_rr:               float            = 2.6,
    scalping_min_rr:               float            = 1.0,
    scalping_counter_trend_min_rr: float            = 1.5,
    market_transition_adx_block:   float            = 15.0,
    market_transition_adx_gray:    float            = 25.0,
    scalping_h1_only:              bool             = True,
    intraday_require_d1:           bool             = True,
) -> Signal | None:
    """Evaluasi sinyal untuk satu (symbol, trigger_tf). Returns Signal jika 5 gate lulus."""
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _reject(df_t, "INIT")

    # ── Circuit breaker — cek loss beruntun sebelum Gate 1 ────────────────────
    # Scalping (M5/M15) dan intraday (H1/H4/D1) punya counter terpisah —
    # loss scalping tidak boleh memblokir sinyal intraday dan sebaliknya.
    # Key: "{symbol}_{mode}" untuk memisahkan counter per mode.
    today_str   = datetime.now().strftime("%Y-%m-%d")
    _is_scalping_tf = trigger_tf in {"M5", "M15"}
    _cb_key     = f"{symbol}_{'scalping' if _is_scalping_tf else 'intraday'}"
    _cb_mode    = "scalping" if _is_scalping_tf else "intraday"

    # Circuit breaker disabled - always allow signal generation
    # (code kept for backward compatibility but not evaluated)

    # GATE 1 — Validasi teknis
    if len(df_t) < 200:
        _reject(df_t, f"NOT_ENOUGH_BARS({len(df_t)})"); return None

    last          = _latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"])
    # Simpan sebagai UTC eksplisit (suffix +00:00) agar iso_to_wib_str() tahu perlu konversi
    close_time    = str(close_time_ts.to_pydatetime().replace(tzinfo=pytz.utc).isoformat())
    price_now     = float(last["close"])
    atr           = _atr_proxy(df_t)

    if atr <= 0:
        _reject(df_t, "ATR_INVALID"); return None
    if atr < price_now * atr_min_pct:
        _reject(df_t, f"ATR_TOO_LOW({atr:.4f})"); return None

    is_scalping = trigger_tf in {"M5", "M15"}

    # ── Filter ATR minimum absolut khusus scalping ────────────────────────────
    # ATR pct (di atas) cek relatif terhadap harga — tidak sensitif saat harga tinggi.
    # Filter ini cek nilai absolut: ATR < 5.0 poin = market terlalu flat untuk scalping.
    # Contoh: ATR 4.32 → TP1 butuh 9 poin = 2.1× ATR → mustahil dicapai scalping.
    # Nilai 5.0 berdasarkan data historis sinyal lose di ATR 4.32 dan 6.74.
    # Bisa di-override via SCALPING_ATR_MIN_POINTS di .env.
    if is_scalping and scalping_atr_min_points > 0 and atr < scalping_atr_min_points:
        _reject(df_t, f"ATR_TOO_LOW_SCALPING(atr={atr:.2f}/min={scalping_atr_min_points:.1f})")
        return None

    if is_scalping:
        base_trig  = scalping_min_trigger_score
        base_conf  = scalping_min_confluence_score
        # Cooldown per-TF: M5 pakai scalping_cooldown_bars_m5, M15 pakai scalping_cooldown_bars_m15
        # TF lain fallback ke scalping_cooldown_bars
        if trigger_tf == "M5":
            base_cd = scalping_cooldown_bars_m5
        elif trigger_tf == "M15":
            base_cd = scalping_cooldown_bars_m15
        else:
            base_cd = scalping_cooldown_bars
    else:
        base_trig  = min_trigger_score
        base_conf  = min_confluence_score
        base_cd    = cooldown_bars

    market_cond = detect_market_condition(df_t)
    if market_cond == "volatile":
        eff_trig = max(1, base_trig - 1)
        eff_conf = max(1, base_conf - 1)
    elif market_cond == "sideways":
        eff_trig = base_trig + 1
        eff_conf = base_conf + 1
    else:
        eff_trig = base_trig
        eff_conf = base_conf

    # ── Asian session CONTINUATION stricter requirement ────────────────────────
    # Asian session: low volatility, choppy, many false breakouts
    # CONTINUATION scalping butuh konfirmasi lebih kuat untuk avoid noise
    # Note: close_time_ts belum didefinisikan di sini, jadi kita check nanti
    # setelah close_time_ts tersedia (setelah validasi bars)
    _asian_continuation_pending = False
    if is_scalping:
        # We'll check this after we have close_time_ts
        _asian_continuation_pending = True

    key        = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        tf_min = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(trigger_tf, 5)
        bars_since = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars_since < base_cd:
            _reject(df_t, f"COOLDOWN({bars_since:.1f}bar)"); return None

    now_utc = close_time_ts.to_pydatetime().replace(tzinfo=pytz.utc) if close_time_ts.tzinfo is None else close_time_ts.to_pydatetime()
    sess    = session_name(now_utc)
    
    # ── Asian CONTINUATION threshold adjustment (deferred from earlier) ────────
    # Apply stricter requirement for CONTINUATION scalping in Asian session
    # We need to know if it's CONTINUATION (following HTF bias), but bias is
    # determined in GATE 2 below. So we check session here and apply adjustment
    # if Asian, then in GATE 3 we'll know if it's CONTINUATION.
    # Adjustment: +1 trigger, +1 confluence for Asian CONTINUATION scalping
    if _asian_continuation_pending and session_strictness(now_utc, tf=trigger_tf) == "RELAXED":
        # Asian session detected - will apply stricter rules for CONTINUATION
        # (REVERSAL/CT will not be affected as they use different path in GATE 3)
        eff_trig += 1  # Need stronger trigger in Asian
        eff_conf += 1  # Need stronger confluence in Asian
        # Note: This affects CONTINUATION path in GATE 3 (bias in BULL/BEAR branch)
        # Counter-trend path (else branch) will not be affected

    # ── Cap eff_trig / eff_conf ───────────────────────────────────────────────
    # Sideways (+1) dan Asian (+1) bisa numpuk jadi base+2.
    # Tanpa cap: scalping base=3 + sideways + Asian = 5, atau base=4 = 6
    # (6 = butuh SEMUA komponen sepakat — nyaris mustahil di kondisi riil).
    # Cap di 5: sisakan minimal 1 komponen "boleh tidak sepakat".
    # Cap di 4: untuk confluence (maks bobot float ~ 10+, threshold tetap integer).
    eff_trig = min(eff_trig, 5)
    eff_conf = min(eff_conf, 4)

    if session_filter and not is_active_session(now_utc, trigger_tf):
        _reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # GATE 2 — HTF Bias
    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = _vote_bias(
        data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
        trigger_tf=trigger_tf, min_confirm_votes=min_confirm_votes,
        scalping_h1_only=scalping_h1_only,
        intraday_require_d1=intraday_require_d1,
    )

    # GATE 3 — Trigger Score
    direction:   str | None = None
    trig_score:  int        = 0
    trig_notes:  str        = ""
    _is_counter: bool       = False

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"
        ok, sc, nt = _trigger_score(df_t, dir_try, eff_trig)
        if ok:
            # ── Market Transition Gate ────────────────────────────────────
            # detect_market_condition() sudah cek ADX di TF eksekusi (M5/M15)
            # secara soft (+1 threshold). Gate ini berbeda: cek ADX di TF
            # PENENTU BIAS (H1 untuk M5/M15, H4 untuk H1) — kalau tren di TF
            # penentu sendiri sudah melemah (ADX<18), HTF bias yang "katanya
            # masih BEAR/BULL" itu kemungkinan residu tren lama, bukan kondisi
            # aktual. Ini mencegah sistem ngotot Continuation saat pasar sedang
            # transisi/bounce — persis skenario 42 jam SELL terus tanpa BUY.
            #
            # Zona abu-abu (18-23): tren melemah tapi belum dinyatakan transisi
            # → naikkan min_confluence +1 (soft), bukan block total.
            # ADX < block (bawaan 15): block total Continuation (MARKET_TRANSITION).
            # Rileks dari bawaan lama 18 supaya awal tren (ADX rendah) tidak terblokir.
            #
            # Cuma berlaku untuk Continuation — Reversal/CT tidak kena karena
            # jalurnya ada di else-branch di bawah, dan CT memang valid
            # justru saat ADX rendah (momentum balik dari kondisi lemah).
            _decisive_map = {"M5": "H1", "M15": "H1", "H1": "H4"}
            _dec_tf  = _decisive_map.get(trigger_tf)
            _dec_df  = data_by_tf.get(_dec_tf) if _dec_tf else None
            _dec_adx: float | None = None
            if _dec_df is not None and "adx_14" in _dec_df.columns and len(_dec_df) > 2:
                _raw_adx = _dec_df["adx_14"].iloc[-2]
                if pd.notna(_raw_adx):
                    _dec_adx = float(_raw_adx)

            if _dec_adx is not None:
                if _dec_adx < market_transition_adx_block:
                    # Block total — tren di TF penentu sudah terlalu lemah
                    _reject(df_t, f"MARKET_TRANSITION(adx_{_dec_tf}={_dec_adx:.1f})")
                    return None
                elif _dec_adx < market_transition_adx_gray:
                    # Zona abu-abu — perketat confluence, jangan block total
                    eff_conf = min(eff_conf + 1, 5)

            direction, trig_score, trig_notes = dir_try, sc, nt
        else:
            _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{eff_trig}[{nt}] cond={market_cond}")
            return None
    else:
        _ct_tfs = [t.upper() for t in (counter_trend_tfs or ["H1", "H4"])]
        if not counter_trend_enabled or trigger_tf not in _ct_tfs:
            _reject(df_t, f"BIAS_FAIL({bias_detail})"); return None

        ct_direction: str | None = None
        ct_detail:    str        = ""
        ct_score:     int        = 0
        for try_dir in ["BUY", "SELL"]:
            ok_ct, det_ct, sc_ct = _is_counter_trend_valid(
                df=df_t, direction=try_dir, entry=price_now,
                atr=atr, tf=trigger_tf,
                min_counter_confluence=min_counter_confluence,
                is_scalping=is_scalping, data_by_tf=data_by_tf,
            )
            if ok_ct and sc_ct > ct_score:
                ct_direction, ct_detail, ct_score = try_dir, det_ct, sc_ct

        if ct_direction is None:
            _reject(df_t, f"BIAS_FAIL+CT_FAIL({bias_detail})"); return None

        direction   = ct_direction
        _is_counter = True
        ok_trig, trig_score, trig_full = _trigger_score(df_t, direction, min_score=1)
        trig_notes = f"{trig_full} [CT:{ct_detail} score={ct_score}]"
        if "EMA200-" in trig_full:
            _reject(df_t, f"CT_EMA200_FAIL({trig_full})"); return None

    # ── Late-entry filter (Saran B4) ─────────────────────────────────────────
    # Tolak sinyal kalau harga sudah terlalu jauh dari trigger candle.
    # Entry yang "chasing" (telat masuk, candle sudah lari jauh) = SL rawan
    # kena retracement wajar sebelum lanjut ke arah yang benar.
    #   Threshold: close harus dalam 1.5×ATR dari candle close trigger.
    #   (Jika data candle trigger close-nya sama dengan price_now karena real-time,
    #    filter ini akan skip otomatis karena dist = 0.)
    _trig_close = float(df_t.iloc[-2]["close"]) if len(df_t) >= 2 else price_now
    _late_dist  = abs(price_now - _trig_close)
    _late_max   = 1.5 * atr
    if _late_dist > _late_max:
        _reject(df_t, f"LATE_ENTRY(dist={_late_dist:.2f}/max={_late_max:.2f})"); return None

    # GATE 4 — SL/TP
    # RR berbeda untuk scalping (ambil profit cepat) vs intraday
    eff_tp1_rr = scalping_tp1_rr if is_scalping else tp1_rr
    eff_tp2_rr = scalping_tp2_rr if is_scalping else tp2_rr
    eff_tp3_rr = scalping_tp3_rr if is_scalping else tp3_rr

    if is_scalping:
        plan = swing_based_sltp(
            direction=direction, price_now=price_now, df=df_t, atr=atr,
            is_scalping=True, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
            max_sl=max_sl_points, sl_atr_mult_override=scalping_sl_atr_mult,
        )
        if plan is None:
            plan = dynamic_atr_sltp(
                direction=direction, price_now=price_now, atr=atr,
                is_scalping=True, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
                max_sl=max_sl_points, df=df_t, sl_atr_mult_override=scalping_sl_atr_mult,
            )
        sl_method = "swing" if (plan is not None and "Swing" in (plan.method or "")) else "dynamic_atr"
    else:
        plan = dynamic_atr_sltp(
            direction=direction, price_now=price_now, atr=atr,
            is_scalping=False, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
            max_sl=max_sl_points, df=df_t, data_by_tf=data_by_tf,
            sl_atr_mult_override=sl_atr_mult,
        )
        sl_method = "dynamic_atr"
    if plan is None:
        plan = fixed_zone_sltp(
            direction=direction, price_now=price_now,
            entry_zone_pips=30, sl_pips=sl_pips,
            tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
            pip_size=pip_size,
        )
        sl_method = "fixed"
    if plan is None:
        _reject(df_t, "SLTP_NONE"); return None

    # GATE 5 — Confluence + RR
    conf_score, conf_notes, conf_detail = _confluence_score(
        df=df_t, direction=direction, entry=price_now, atr=atr,
        tf=trigger_tf, is_scalping=is_scalping, sl=float(plan.sl),
        tp1_rr=eff_tp1_rr, data_by_tf=data_by_tf, now_utc=now_utc,
    )
    if conf_score == -99:
        _reject(df_t, f"ASIAN_NO_KEY_LEVEL [{conf_notes}]" if "ASIAN_NO_KEY_LEVEL" in conf_notes else f"SNR_BLOCKED [{conf_notes}]"); return None
    if conf_score < eff_conf:
        _reject(df_t, f"CONFLUENCE_FAIL conf={conf_score}/{eff_conf}[{conf_notes}] cond={market_cond}")
        return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr           = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
    # Pisahkan min_rr untuk scalping vs intraday, dan untuk CT vs trend-following:
    #   Scalping trend-following  : scalping_min_rr  (default 1.0)
    #   Scalping counter-trend    : scalping_counter_trend_min_rr  (default 1.5)
    #   Intraday trend-following  : min_rr  (default 1.0)
    #   Intraday counter-trend    : counter_trend_min_rr  (default 1.1)
    # Ini memastikan scalping CT tidak ikut counter_trend_min_rr intraday
    # (yang lebih tinggi dari scalping_tp1_rr → sinyal mustahil lolos)
    if is_scalping:
        min_rr_eff = scalping_counter_trend_min_rr if _is_counter else scalping_min_rr
    else:
        min_rr_eff = counter_trend_min_rr if _is_counter else min_rr
    if rr is None or rr < min_rr_eff:
        _reject(df_t, f"RR_FAIL(rr={rr}/min={min_rr_eff})"); return None

    # Normalisasi ke tz-naive sebelum simpan agar konsisten saat load ulang
    ts_to_save = close_time_ts.tz_localize(None) if close_time_ts.tzinfo is not None else close_time_ts
    _LAST_SIGNAL_TIME[key] = ts_to_save
    _save_cooldown_state()
    _reject(df_t, "OK")

    trade_mode, exec_tf = _detect_trade_mode(trigger_tf)
    mkt_tag = f" [mkt={market_cond}]" if market_cond != "normal" else ""

    return Signal(
        symbol=symbol, tf=trigger_tf, direction=direction, close_time=close_time,
        signal_type="LIVE",
        signal_mode="REVERSAL" if _is_counter else "CONTINUATION",
        entry=float(entry_for_rr), entry_low=float(plan.entry_low),
        entry_high=float(plan.entry_high), sl=float(plan.sl),
        tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
        rr=float(rr), sl_method=sl_method, atr_value=float(atr),
        tp1_rr=float(eff_tp1_rr), tp2_rr=float(eff_tp2_rr), tp3_rr=float(eff_tp3_rr),
        trigger_score=trig_score, trigger_max=6, confluence_score=conf_score,
        htf_bias=bias_detail,
        trigger_notes=f"{trig_notes}{mkt_tag}",
        confluence_notes=conf_notes,
        pattern_names=conf_detail["pattern_names"],
        fib_detail=conf_detail["fib_detail"], snr_detail=conf_detail["snr_detail"],
        snd_detail=conf_detail["snd_detail"], divergence_detail=conf_detail["div_detail"],
        session_name=sess,
        trade_mode=trade_mode, exec_tf=exec_tf, is_setup_plan=False,
    )
