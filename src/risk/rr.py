"""
rr.py
=====
Kalkulasi Risk-Reward Ratio (RR).
"""
from __future__ import annotations


def calc_rr(
    direction: str,
    entry:     float,
    sl:        float,
    tp:        float,
    min_risk:  float = 0.0,
) -> float | None:
    """
    Hitung Risk-Reward Ratio dari entry, SL, dan TP.

    Args:
        direction: "BUY" atau "SELL".
        entry:     Harga entry.
        sl:        Harga Stop Loss.
        tp:        Harga Take Profit.
        min_risk:  Risiko minimum agar RR dihitung valid.

    Returns:
        RR sebagai float, atau None jika input tidak valid.
    """
    try:
        entry = float(entry)
        sl    = float(sl)
        tp    = float(tp)
    except Exception:
        return None

    direction = direction.upper().strip()

    if direction == "BUY":
        risk   = entry - sl
        reward = tp - entry
    elif direction == "SELL":
        risk   = sl - entry
        reward = entry - tp
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    if min_risk > 0 and risk < min_risk:
        return None

    return reward / risk
