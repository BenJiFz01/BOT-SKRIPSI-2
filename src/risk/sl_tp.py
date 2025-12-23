from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class FixedZonePlan:
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    method: str


def fixed_zone_sltp(
    direction: str,
    price_now: float,
    entry_zone_pips: float = 30.0,
    sl_pips: float = 50.0,
    tp1_pips: float = 40.0,
    tp2_pips: float = 70.0,
    tp3_pips: float = 100.0,
    pip_size: float = 0.1,
) -> FixedZonePlan | None:
    try:
        p = float(price_now)
        ez_p = float(entry_zone_pips)
        sl_p = float(sl_pips)
        t1_p = float(tp1_pips)
        t2_p = float(tp2_pips)
        t3_p = float(tp3_pips)
        ps = float(pip_size)
    except Exception:
        return None

    if not all(math.isfinite(x) for x in [p, ez_p, sl_p, t1_p, t2_p, t3_p, ps]):
        return None
    if p <= 0 or ps <= 0:
        return None
    if ez_p <= 0 or sl_p <= 0 or t1_p <= 0 or t2_p <= 0 or t3_p <= 0:
        return None

    d = direction.upper().strip()

    ez = ez_p * ps
    sl_dist = sl_p * ps
    tp1 = t1_p * ps
    tp2 = t2_p * ps
    tp3 = t3_p * ps

    if d == "BUY":
        entry_high = p
        entry_low = p - ez
        sl = entry_high - sl_dist

        # sanity check
        if not (entry_low < entry_high and sl < entry_low):
            return None

        return FixedZonePlan(
            entry_low=entry_low,
            entry_high=entry_high,
            sl=sl,
            tp1=entry_high + tp1,
            tp2=entry_high + tp2,
            tp3=entry_high + tp3,
            method="FixedZone BUY (EZ=30p, SL=50p, TP=40/70/100)",
        )

    if d == "SELL":
        entry_low = p
        entry_high = p + ez
        sl = entry_low + sl_dist

        if not (entry_low < entry_high and sl > entry_high):
            return None

        return FixedZonePlan(
            entry_low=entry_low,
            entry_high=entry_high,
            sl=sl,
            tp1=entry_low - tp1,
            tp2=entry_low - tp2,
            tp3=entry_low - tp3,
            method="FixedZone SELL (EZ=30p, SL=50p, TP=40/70/100)",
        )

    return None
