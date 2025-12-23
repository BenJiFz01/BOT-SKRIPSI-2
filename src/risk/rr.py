from __future__ import annotations


def calc_rr(direction: str, entry: float, sl: float, tp: float, min_risk: float = 0.0) -> float | None:
    try:
        entry = float(entry)
        sl = float(sl)
        tp = float(tp)
    except Exception:
        return None

    direction = direction.upper().strip()

    if direction == "BUY":
        risk = entry - sl
        reward = tp - entry
    elif direction == "SELL":
        risk = sl - entry
        reward = entry - tp
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    if risk < min_risk:
        return None
    return reward / risk