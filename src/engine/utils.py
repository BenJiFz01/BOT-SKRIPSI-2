"""─ Helper primitif engine (RR calc, ATR proxy, safe accessor, reject marker)."""

from __future__ import annotations

import pandas as pd


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
