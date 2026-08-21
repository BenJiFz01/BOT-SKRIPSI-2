"""helpers.py — Fungsi utilitas internal engine (tidak diimpor dari luar)."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Cooldown state per (symbol, tf) — persisted ke file ────────────────────
_COOLDOWN_PATH = Path("logs/cooldown_state.json")
_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}


def _load_cooldown() -> None:
    """Muat state cooldown dari file saat startup."""
    global _LAST_SIGNAL_TIME
    if not _COOLDOWN_PATH.exists():
        return
    try:
        raw = json.loads(_COOLDOWN_PATH.read_text(encoding="utf-8"))
        for k, v in raw.items():
            sym, tf = k.split("|", 1)
            _LAST_SIGNAL_TIME[(sym, tf)] = pd.Timestamp(v, tz="UTC")
    except Exception:
        pass  # file corrupt → mulai fresh, tidak fatal


def _save_cooldown() -> None:
    """Simpan state cooldown ke file setelah sinyal baru."""
    try:
        _COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            f"{sym}|{tf}": ts.isoformat()
            for (sym, tf), ts in _LAST_SIGNAL_TIME.items()
        }
        _COOLDOWN_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except Exception:
        pass  # gagal save tidak harus crash bot


_load_cooldown()


def atr_proxy(df: pd.DataFrame, n: int = 14) -> float:
    """Baca ATR dari kolom atr_14, fallback ke avg high-low range."""
    if "atr_14" in df.columns:
        v = df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            return float(v)
    if len(df) < 3:
        return 0.0
    w = df.iloc[-n:] if len(df) > n else df
    v = (w["high"].astype(float) - w["low"].astype(float)).mean()
    return float(v) if pd.notna(v) and v > 0 else 0.0


def latest_closed(df: pd.DataFrame) -> pd.Series:
    """Candle ke-2 dari belakang = candle yang baru saja close."""
    return df.iloc[-2]


def safe(row: pd.Series, col: str) -> float | None:
    """Baca kolom dari Series, kembalikan None jika NaN/tidak ada."""
    v = row.get(col)
    return None if (v is None or pd.isna(v)) else float(v)


def reject(df: pd.DataFrame, reason: str) -> None:
    """Tulis alasan reject ke df.attrs untuk logging di main loop."""
    df.attrs["reject_reason"] = reason


def detect_market_condition(df: pd.DataFrame, atr_period: int = 20) -> str:
    """
    Deteksi kondisi pasar dari rasio ATR terkini vs rata-rata historis.
    Returns: 'news_spike' | 'volatile' | 'sideways' | 'normal'.
    """
    col = "atr_14" if "atr_14" in df.columns else None
    if col is None or len(df) < atr_period + 3:
        return "normal"

    series = df[col].dropna()
    if len(series) < atr_period + 2:
        return "normal"

    current = float(series.iloc[-2])
    avg     = float(series.iloc[-(atr_period + 2):-2].mean())
    if avg <= 0:
        return "normal"

    ratio = current / avg
    if ratio > 3.0:   return "news_spike"
    if ratio > 1.5:   return "volatile"
    if ratio < 0.7:   return "sideways"
    return "normal"


def calc_rr(direction: str, entry: float, sl: float, tp: float) -> float | None:
    """Hitung Risk-Reward Ratio. Returns float atau None jika input tidak valid."""
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


def detect_trade_mode(trigger_tf: str) -> tuple[str, str]:
    """Kembalikan (trade_mode, exec_tf) berdasarkan trigger TF."""
    tf = trigger_tf.upper()
    if tf in ("M5", "M15"):  return "scalping", "M5"
    if tf == "H1":           return "intraday", "M15"
    return "intraday", "H1"
