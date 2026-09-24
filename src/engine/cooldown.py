"""─ Runtime state engine (cooldown, conflict-resolver state, circuit-breaker stub)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}

# [Conflict resolver — ADITIF anti-spam "3 sinyal sekaligus"] state lintas-TF per (symbol, direction).
# key=(symbol,direction) → (epoch_second_emit, confluence_score_terakhir). Dedup ADITIF, tak ubah skor/gate/threshold.
_LAST_LIVE_EMIT: dict[tuple[str, str], tuple[float, float]] = {}
_CONFLICT_WINDOW_SEC: float = 30 * 60  # 30 menit window anti-duplikat arah-sama lintas-TF

# Circuit breaker disabled: sinyal terus masuk tanpa pause demi data collection. Functions tetap ada utk backward compat.

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

# Cooldown persistence
_COOLDOWN_PATH = Path("logs/cooldown_state.json")


def _load_cooldown_state() -> None:
    """Baca cooldown_state.json ke _LAST_SIGNAL_TIME (timestamp tz-naive UTC)."""
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
    """Simpan _LAST_SIGNAL_TIME ke cooldown_state.json (string ISO UTC tz-naive)."""
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


# Load state saat import (startup)
_load_cooldown_state()
