"""─ Runtime state engine (cooldown, conflict-resolver state, circuit-breaker stub)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}

# Cache sinyal terakhir per arah untuk mencegah duplikasi sinyal dalam 30 menit
_LAST_LIVE_EMIT: dict[tuple[str, str], tuple[float, float]] = {}
_CONFLICT_WINDOW_SEC: float = 30 * 60

# Circuit breaker tracking
_CONSEC_LOSS: dict[str, dict] = {}
_CONSEC_LOSS_DATE: dict[str, str] = {}


def record_loss(symbol: str) -> None:
    pass


def reset_consec_loss(symbol: str) -> None:
    pass


def get_consec_loss_count(symbol: str) -> int:
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
                if ts.tzinfo is not None:                    ts = ts.tz_convert("UTC").tz_localize(None)
                _LAST_SIGNAL_TIME[(parts[0], parts[1])] = ts
    except Exception:
        pass


def _save_cooldown_state() -> None:
    """Simpan _LAST_SIGNAL_TIME ke cooldown_state.json (string ISO UTC tz-naive)."""
    try:
        _COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for (sym, tf), ts in _LAST_SIGNAL_TIME.items():
            ts_naive = ts.tz_localize(None) if ts.tzinfo is not None else ts
            data[f"{sym}|{tf}"] = ts_naive.isoformat()
        tmp = _COOLDOWN_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_COOLDOWN_PATH)
    except Exception:
        pass


_load_cooldown_state()
