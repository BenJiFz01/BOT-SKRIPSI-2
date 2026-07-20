"""
sl_tp.py
========
Kalkulasi Stop Loss dan Take Profit.

Dua metode tersedia:
    1. dynamic_atr_sltp()  -- UTAMA  : SL/TP adaptif berdasarkan ATR
    2. fixed_zone_sltp()   -- FALLBACK: SL/TP tetap dalam satuan pip

Gunakan dynamic_atr_sltp() sebagai primary. Jika ATR tidak valid,
fallback ke fixed_zone_sltp().
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class SLTPlan:
    """Hasil kalkulasi SL/TP dari dynamic_atr_sltp."""
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
    """Hasil kalkulasi SL/TP dari fixed_zone_sltp (fallback)."""
    entry_low:  float
    entry_high: float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    method:     str
    # Alias agar kompatibel dengan SLTPlan di engine
    atr_used:   float = 0.0
    sl_dist:    float = 0.0
    rr_tp1:     float = 0.0
    rr_tp2:     float = 0.0
    rr_tp3:     float = 0.0


# ── Dynamic ATR SL/TP (Primary) ───────────────────────────────────────

def dynamic_atr_sltp(
    direction:      str,
    price_now:      float,
    atr:            float,
    sl_atr_mult:    float = 1.5,   # SL = sl_atr_mult x ATR
    tp1_rr:         float = 1.5,
    tp2_rr:         float = 2.5,
    tp3_rr:         float = 4.0,
    entry_atr_frac: float = 0.2,   # Entry zone = entry_atr_frac x ATR
    max_sl_pct:     float = 0.015, # SL maks 1.5% dari harga (safety cap)
    min_sl_pct:     float = 0.001, # SL min 0.1% dari harga
) -> SLTPlan | None:
    """
    Hitung SL/TP berbasis ATR (adaptif terhadap volatilitas pasar).

    Contoh XAU/USD:
        ATR = 12.5 pips, sl_atr_mult = 1.5
        -> SL distance = 18.75 pips
        -> TP1 = RR 1.5 -> 28.1 pips dari entry
        -> TP2 = RR 2.5 -> 46.9 pips dari entry
        -> TP3 = RR 4.0 -> 75.0 pips dari entry

    Returns:
        SLTPlan atau None jika kalkulasi tidak valid.
    """
    try:
        p   = float(price_now)
        a   = float(atr)
        slm = float(sl_atr_mult)
        ez  = float(entry_atr_frac)
    except Exception:
        return None

    if not all(math.isfinite(x) for x in [p, a, slm, ez]):
        return None
    if p <= 0 or a <= 0 or slm <= 0:
        return None

    d = direction.upper().strip()

    # SL distance dengan safety cap
    sl_dist_raw = slm * a
    sl_dist     = max(p * min_sl_pct, min(sl_dist_raw, p * max_sl_pct))
    ez_dist     = ez * a

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


# ── TP Snap ke level S/R (opsional) ──────────────────────────────────

def snap_tp_to_snr(
    direction:   str,
    tp_raw:      float,
    entry:       float,
    snr_levels:  list[float],
    atr:         float,
    snap_factor: float = 0.5,
    min_rr:      float = 1.2,
    sl:          float = 0.0,
) -> float:
    """
    Geser TP agar "menempel" ke level Support/Resistance terdekat.

    Berguna agar TP tidak menembus S/R yang bisa menjadi hambatan.
    Snap hanya terjadi jika S/R dalam radius snap_factor * ATR dari TP,
    dan hasilnya tetap memenuhi min_rr.

    Returns:
        Harga TP baru (atau tp_raw jika tidak ada snap yang valid).
    """
    if not snr_levels or atr <= 0:
        return tp_raw

    direction   = direction.upper()
    snap_radius = snap_factor * atr
    margin      = 0.1 * atr

    if direction == "BUY":
        candidates = [lv for lv in snr_levels if entry < lv <= tp_raw + snap_radius]
        if candidates:
            snapped = min(candidates) - margin
            if sl > 0:
                risk   = entry - sl
                reward = snapped - entry
                if risk > 0 and (reward / risk) >= min_rr:
                    return snapped
            else:
                return snapped

    else:  # SELL
        candidates = [lv for lv in snr_levels if tp_raw - snap_radius <= lv < entry]
        if candidates:
            snapped = max(candidates) + margin
            if sl > 0:
                risk   = sl - entry
                reward = entry - snapped
                if risk > 0 and (reward / risk) >= min_rr:
                    return snapped
            else:
                return snapped

    return tp_raw


# ── Fixed Pip SL/TP (Fallback) ────────────────────────────────────────

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
    """
    Hitung SL/TP dengan nilai pip tetap (fallback jika ATR tidak valid).

    Args:
        pip_size: Nilai 1 pip dalam satuan harga.
                  Untuk XAU/USD: 1 pip = 0.1 (harga ~3300.0).

    Returns:
        FixedZonePlan atau None jika parameter tidak valid.
    """
    try:
        p    = float(price_now)
        ez   = float(entry_zone_pips)
        slp  = float(sl_pips)
        t1   = float(tp1_pips)
        t2   = float(tp2_pips)
        t3   = float(tp3_pips)
        ps   = float(pip_size)
    except Exception:
        return None

    if not all(math.isfinite(x) for x in [p, ez, slp, t1, t2, t3, ps]):
        return None
    if any(x <= 0 for x in [p, ez, slp, t1, t2, t3, ps]):
        return None

    d    = direction.upper().strip()
    ez_v = ez  * ps
    sl_v = slp * ps
    t1_v = t1  * ps
    t2_v = t2  * ps
    t3_v = t3  * ps

    if d == "BUY":
        entry_high = p
        entry_low  = p - ez_v
        sl         = entry_high - sl_v
        if not (entry_low < entry_high and sl < entry_low):
            return None
        return FixedZonePlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=entry_high + t1_v, tp2=entry_high + t2_v, tp3=entry_high + t3_v,
            method=f"FixedZone BUY | EZ={ez}p SL={slp}p TP={t1}/{t2}/{t3}p",
        )

    if d == "SELL":
        entry_low  = p
        entry_high = p + ez_v
        sl         = entry_low + sl_v
        if not (entry_low < entry_high and sl > entry_high):
            return None
        return FixedZonePlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=entry_low - t1_v, tp2=entry_low - t2_v, tp3=entry_low - t3_v,
            method=f"FixedZone SELL | EZ={ez}p SL={slp}p TP={t1}/{t2}/{t3}p",
        )

    return None
