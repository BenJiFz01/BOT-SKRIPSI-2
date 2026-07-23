"""sl_tp.py — Kalkulasi Stop Loss dan Take Profit."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SLTPlan:
    entry_low:  float
    entry_high: float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    method:     str
    atr_used:   float
    sl_dist:    float
    rr_tp1:     float
    rr_tp2:     float
    rr_tp3:     float


@dataclass
class FixedZonePlan:
    """Fallback plan jika ATR tidak valid."""
    entry_low:  float
    entry_high: float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    method:     str
    atr_used:   float = 0.0
    sl_dist:    float = 0.0
    rr_tp1:     float = 0.0
    rr_tp2:     float = 0.0
    rr_tp3:     float = 0.0


def dynamic_atr_sltp(
    direction:      str,
    price_now:      float,
    atr:            float,
    sl_atr_mult:    float = 1.5,
    tp1_rr:         float = 1.5,
    tp2_rr:         float = 2.5,
    tp3_rr:         float = 4.0,
    entry_atr_frac: float = 0.2,
    max_sl_pct:     float = 0.015,
    min_sl_pct:     float = 0.001,
    max_sl_points:  float = 50.0,
) -> SLTPlan | None:
    """SL/TP adaptif berbasis ATR. SL = min(ATR-based, max_sl_points). TP dihitung dari sl_dist."""
    try:
        p, a, slm, ez = float(price_now), float(atr), float(sl_atr_mult), float(entry_atr_frac)
    except Exception:
        return None

    if not all(math.isfinite(x) for x in [p, a, slm, ez]):
        return None
    if p <= 0 or a <= 0 or slm <= 0:
        return None

    d       = direction.upper().strip()
    sl_dist = max(p * min_sl_pct, min(slm * a, p * max_sl_pct))
    if max_sl_points > 0:
        sl_dist = min(sl_dist, max_sl_points)
    ez_dist = ez * a

    if d == "BUY":
        entry_high = p
        entry_low  = p - ez_dist
        sl         = entry_high - sl_dist
        if sl >= entry_low:
            sl = entry_low - (sl_dist * 0.3)
        tp1 = entry_high + sl_dist * tp1_rr
        tp2 = entry_high + sl_dist * tp2_rr
        tp3 = entry_high + sl_dist * tp3_rr
        if not (entry_low < entry_high and sl < entry_low):
            return None
    elif d == "SELL":
        entry_low  = p
        entry_high = p + ez_dist
        sl         = entry_low + sl_dist
        if sl <= entry_high:
            sl = entry_high + (sl_dist * 0.3)
        tp1 = entry_low - sl_dist * tp1_rr
        tp2 = entry_low - sl_dist * tp2_rr
        tp3 = entry_low - sl_dist * tp3_rr
        if not (entry_low < entry_high and sl > entry_high):
            return None
    else:
        return None

    return SLTPlan(
        entry_low=entry_low, entry_high=entry_high,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        method=f"DynamicATR {d} | ATR={a:.4f} | SL={slm}xATR={sl_dist:.4f}",
        atr_used=a, sl_dist=sl_dist,
        rr_tp1=tp1_rr, rr_tp2=tp2_rr, rr_tp3=tp3_rr,
    )


def fixed_zone_sltp(
    direction:       str,
    price_now:       float,
    entry_zone_pips: float = 30.0,
    sl_pips:         float = 50.0,
    tp1_pips:        float = 40.0,
    tp2_pips:        float = 70.0,
    tp3_pips:        float = 100.0,
    pip_size:        float = 0.1,
) -> FixedZonePlan | None:
    """SL/TP fixed pip — fallback jika ATR tidak valid."""
    try:
        p, ez, slp, t1, t2, t3, ps = (
            float(price_now), float(entry_zone_pips), float(sl_pips),
            float(tp1_pips), float(tp2_pips), float(tp3_pips), float(pip_size)
        )
    except Exception:
        return None

    if not all(math.isfinite(x) for x in [p, ez, slp, t1, t2, t3, ps]):
        return None
    if any(x <= 0 for x in [p, ez, slp, t1, t2, t3, ps]):
        return None

    d    = direction.upper().strip()
    ez_v, sl_v = ez * ps, slp * ps
    t1_v, t2_v, t3_v = t1 * ps, t2 * ps, t3 * ps

    if d == "BUY":
        entry_high, entry_low = p, p - ez_v
        sl = entry_high - sl_v
        if not (entry_low < entry_high and sl < entry_low):
            return None
        return FixedZonePlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=entry_high + t1_v, tp2=entry_high + t2_v, tp3=entry_high + t3_v,
            method=f"FixedZone BUY | EZ={ez}p SL={slp}p",
        )
    if d == "SELL":
        entry_low, entry_high = p, p + ez_v
        sl = entry_low + sl_v
        if not (entry_low < entry_high and sl > entry_high):
            return None
        return FixedZonePlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=entry_low - t1_v, tp2=entry_low - t2_v, tp3=entry_low - t3_v,
            method=f"FixedZone SELL | EZ={ez}p SL={slp}p",
        )
    return None
