"""sl_tp.py — Stop Loss & Take Profit: Structural + ATR-based.

SL = swing point terdekat + 0.5×ATR buffer (anti stop-hunt), fallback atr_mult×ATR
(scalping 1.2×, intraday 1.5×). Entry zone 0.3×ATR. SL di-cap per TF.

TP: scalping ladder proporsional 0.7/1.0/1.3R, intraday 1.5/2.5/4.0R.
Gate RR dicabut (TP proporsional SL) → penggantinya OVEREXTENSION guard di engine.
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from src.features.swing_utils import pivot_highs, pivot_lows


# Config

@dataclass(frozen=True)
class _SlConfig:
    atr_mult:    float   # SL fallback = atr_mult × ATR
    min_sl_pts:  float   # batas bawah absolut
    max_sl_pts:  float   # batas atas absolut (di-override oleh max_sl dari settings)
    lookback:    int     # lookback untuk swing SL


@dataclass(frozen=True)
class _TpConfig:
    tp1_rr:       float
    tp2_rr:       float
    tp3_rr:       float
    tp1_atr_mult: float = 0.0   # >0 → TP1 = tp1_atr_mult × ATR (independen SL)


_SL_SCALPING = _SlConfig(atr_mult=1.2, min_sl_pts=5.0,  max_sl_pts=10.0, lookback=20)
_SL_INTRADAY = _SlConfig(atr_mult=1.5, min_sl_pts=10.0, max_sl_pts=60.0, lookback=40)
# Scalping: ladder proporsional SL 0.7/1.0/1.3R (vs intraday 1.5/2.5/4.0R) — TP lebih sering tersentuh.
_TP_SCALPING = _TpConfig(tp1_rr=0.7, tp2_rr=1.0, tp3_rr=1.3, tp1_atr_mult=0.0)
_TP_INTRADAY = _TpConfig(tp1_rr=1.5, tp2_rr=2.5, tp3_rr=4.0)

# Entry zone fraction — 0.3×ATR dari close
_EZ_FRAC = 0.3
# Structural SL buffer — 0.5×ATR di luar swing point (naik dari 0.3, anti zona stop-hunt)
_STRUCT_BUFFER_FRAC = 0.5


def get_sl_config(is_scalping: bool) -> _SlConfig:
    return _SL_SCALPING if is_scalping else _SL_INTRADAY


def get_tp_config(is_scalping: bool) -> _TpConfig:
    return _TP_SCALPING if is_scalping else _TP_INTRADAY


# Data class

@dataclass
class SLTPlan:
    entry_low:    float
    entry_high:   float
    sl:           float
    tp1:          float
    tp2:          float
    tp3:          float
    method:       str
    atr_used:     float = field(default=0.0)
    sl_dist:      float = field(default=0.0)
    rr_tp1:       float = field(default=0.0)
    rr_tp2:       float = field(default=0.0)
    rr_tp3:       float = field(default=0.0)
    sl_source:    str   = field(default="")
    obstacle_tp1: float = field(default=0.0)


# Helpers

def _valid(*values: float) -> bool:
    return all(math.isfinite(v) and v > 0 for v in values)


def _swing_sl(
    direction: str,
    price_now: float,
    df:        pd.DataFrame,
    buffer:    float,
    lookback:  int,
    max_dist:  float,
) -> float | None:
    """Cari SL struktural — di luar pivot high/low terdekat + buffer.

    Pilih swing point terdekat yang masih dalam batas max_dist dari harga sekarang.
    """
    if len(df) < lookback + 10:
        return None
    recent = df.iloc[-(lookback + 2):-1].reset_index(drop=True)

    if direction == "BUY":
        # SL di bawah pivot low terdekat
        cands = sorted(
            [v for _, v in pivot_lows(recent, window=3) if v < price_now],
            reverse=True,  # nearest first
        )
        for raw in cands:
            sl = raw - buffer
            dist = abs(price_now - sl)
            if 0 < dist <= max_dist:
                return sl
    else:
        # SL di atas pivot high terdekat
        cands = sorted(
            [v for _, v in pivot_highs(recent, window=3) if v > price_now]
        )
        for raw in cands:
            sl = raw + buffer
            dist = abs(price_now - sl)
            if 0 < dist <= max_dist:
                return sl
    return None


def _find_tp_obstacle(
    direction: str,
    entry:     float,
    tp_target: float,
    atr:       float,
    df:        pd.DataFrame,
) -> float | None:
    """Cari level S/R antara entry dan TP yang bisa menghalangi."""
    if len(df) < 20:
        return None
    recent = df.iloc[-32:-1].reset_index(drop=True)
    if direction == "BUY":
        cands = [v for _, v in pivot_highs(recent, window=3)
                 if entry < v < tp_target - 0.5 * atr]
        return min(cands) if cands else None
    else:
        cands = [v for _, v in pivot_lows(recent, window=3)
                 if tp_target + 0.5 * atr < v < entry]
        return max(cands) if cands else None


def _adjust_tp_for_obstacle(
    direction: str,
    entry:     float,
    tp:        float,
    atr:       float,
    sl_dist:   float,
    df:        pd.DataFrame,
    min_rr:    float = 0.8,
) -> float:
    """Geser TP ke sebelum obstacle jika RR masih terjaga."""
    obstacle = _find_tp_obstacle(direction, entry, tp, atr, df)
    if obstacle is None:
        return tp
    margin   = 0.2 * atr
    adjusted = (obstacle - margin) if direction == "BUY" else (obstacle + margin)
    if sl_dist > 0 and abs(adjusted - entry) / sl_dist >= min_rr:
        return adjusted
    return tp


def _build_plan(
    d:          str,
    p:          float,
    a:          float,
    sl_raw:     float,
    sl_source:  str,
    r1:         float,
    r2:         float,
    r3:         float,
    df:         pd.DataFrame | None,
    is_scalping: bool,
    tp1_atr_mult: float = 0.0,
) -> SLTPlan | None:
    """Bangun SLTPlan dari titik SL yang sudah ditentukan.

    tp1_atr_mult > 0 → TP1 = ref_entry ± tp1_atr_mult×ATR (independen SL).
    tp1_atr_mult == 0 → TP1 = ref_entry ± sl_dist×r1 (legacy, proporsional SL).
    """
    ez = _EZ_FRAC * a

    if d == "BUY":
        entry_high = p
        entry_low  = round(p - ez, 5)
        # Pastikan SL di bawah entry_low
        if sl_raw >= entry_low:
            sl_raw = entry_low - _STRUCT_BUFFER_FRAC * a
        sl         = round(sl_raw, 5)
        sl_dist    = entry_high - sl
        ref_entry  = entry_high
        sign       = 1
        ok         = sl < entry_low < entry_high
    else:
        entry_low  = p
        entry_high = round(p + ez, 5)
        # Pastikan SL di atas entry_high
        if sl_raw <= entry_high:
            sl_raw = entry_high + _STRUCT_BUFFER_FRAC * a
        sl         = round(sl_raw, 5)
        sl_dist    = sl - entry_low
        ref_entry  = entry_low
        sign       = -1
        ok         = entry_low < entry_high < sl

    if not ok or sl_dist <= 0:
        return None

    if tp1_atr_mult > 0:
        # TP1 ATR-based — kunci profit cepat, tidak ikut lebar saat SL lebar.
        tp1 = round(ref_entry + sign * tp1_atr_mult * a, 5)
    else:
        tp1 = round(ref_entry + sign * sl_dist * r1, 5)
    tp2 = round(ref_entry + sign * sl_dist * r2, 5)
    tp3 = round(ref_entry + sign * sl_dist * r3, 5)

    if df is not None and len(df) >= 20:
        # TP1 tetap digeser lewat obstacle adjust selama RR terjaga >= 0.8.
        tp1 = round(_adjust_tp_for_obstacle(d, ref_entry, tp1, a, sl_dist, df, min_rr=0.8), 5)
        tp2 = round(_adjust_tp_for_obstacle(d, ref_entry, tp2, a, sl_dist, df, min_rr=1.5), 5)

    # Sanity check arah TP
    if d == "BUY" and not (sl < entry_low < entry_high < tp1):
        return None
    if d == "SELL" and not (tp1 < entry_low < entry_high < sl):
        return None

    rr1 = abs(tp1 - ref_entry) / sl_dist
    rr2 = abs(tp2 - ref_entry) / sl_dist
    rr3 = abs(tp3 - ref_entry) / sl_dist

    return SLTPlan(
        entry_low=entry_low, entry_high=entry_high,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        method=f"{'SCAL' if is_scalping else 'INTRA'} {d} | src={sl_source} sl={sl_dist:.1f}pt atr={a:.1f}",
        atr_used=a, sl_dist=sl_dist,
        rr_tp1=round(rr1, 2), rr_tp2=round(rr2, 2), rr_tp3=round(rr3, 2),
        sl_source=sl_source,
    )


# Fungsi utama

def calc_sltp(
    direction:   str,
    price_now:   float,
    atr:         float,
    is_scalping: bool  = False,
    tp1_rr:      float = 0.0,
    tp2_rr:      float = 0.0,
    tp3_rr:      float = 0.0,
    max_sl:      float = 0.0,
    df:          pd.DataFrame | None = None,
    max_sl_points:       float = 0.0,
    sl_atr_mult_override: float = 0.0,   # >0 → override sl_cfg.atr_mult (wire dari .env)
    tp1_atr_mult_override: float = 0.0,  # >0 → TP1 = ATR-based (wire dari .env, scalping)
    **_kwargs,
) -> "SLTPlan | None":
    """Hitung SL/TP: structural SL (swing ± 0.5×ATR) dulu, fallback atr_mult×ATR.

    safe_cap = hard_cap - ez (murni, bukan max() dgn min_sl_pts); jika < min_sl_pts
    → reject. Invariant: sl_dist + ez <= hard_cap di semua kondisi termasuk ATR tinggi.
    """
    try:
        p, a = float(price_now), float(atr)
        d    = direction.upper().strip()
    except Exception:
        return None
    if not _valid(p, a) or d not in ("BUY", "SELL"):
        return None

    sl_cfg = get_sl_config(is_scalping)
    tp_cfg = get_tp_config(is_scalping)

    # Override atr_mult dari luar (wire .env): >0 = pakai nilai eksternal.
    eff_atr_mult = sl_atr_mult_override if sl_atr_mult_override > 0 else sl_cfg.atr_mult

    r1 = tp1_rr if tp1_rr > 0 else tp_cfg.tp1_rr
    r2 = tp2_rr if tp2_rr > 0 else tp_cfg.tp2_rr
    r3 = tp3_rr if tp3_rr > 0 else tp_cfg.tp3_rr

    eff_tp1_atr = tp1_atr_mult_override if tp1_atr_mult_override > 0 else tp_cfg.tp1_atr_mult

    hard_cap = max_sl if max_sl > 0 else (max_sl_points if max_sl_points > 0 else sl_cfg.max_sl_pts)
    ez       = _EZ_FRAC * a
    buffer   = _STRUCT_BUFFER_FRAC * a

    # Scalping: SL cap 10pt dari entry reference; floor 0.8×ATR mencegah terlalu rapat (anti stop-hunt).
    if is_scalping:
        hard_cap = min(hard_cap, max(sl_cfg.max_sl_pts, 0.8 * a))
        safe_cap = hard_cap
    else:
        # safe_cap = ruang bersih utk sl_dist setelah entry zone (sl_dist <= hard_cap - ez).
        # Dua batas beda arah tak bisa di-max(): atas hard_cap-ez, bawah min_sl_pts;
        # bawah > atas → tidak ada SL valid yang muat → reject.
        safe_cap = hard_cap - ez
    if safe_cap < sl_cfg.min_sl_pts:
        # ATR sangat besar: entry zone "memakan" hard_cap, tak ada ruang utk SL minimum valid.
        return None

    # Coba structural SL dulu (swing point + buffer)
    struct_sl = _swing_sl(d, p, df if df is not None else pd.DataFrame(),
                          buffer, sl_cfg.lookback, safe_cap) if df is not None else None

    if struct_sl is not None:
        plan = _build_plan(d, p, a, struct_sl, "swing", r1, r2, r3, df, is_scalping,
                           tp1_atr_mult=eff_tp1_atr)
        # Cap scalping: swing valid secara struktural bisa terlalu jauh relatif ATR (contoh SL=2×ATR)
        # → sl_dist <= 1.5×ATR; kalau terlalu jauh, skip ke fallback 1.2×ATR. Intraday tak di-cap.
        _atr_cap_ok = (plan.sl_dist <= 1.5 * a) if (is_scalping and plan is not None) else True
        if plan is not None and sl_cfg.min_sl_pts <= plan.sl_dist <= safe_cap and _atr_cap_ok:
            return plan

    # Fallback: ATR flat
    if is_scalping:
        # Cap scalping dari entry reference (sl_dist di _build_plan sudah termasuk ez) → ruang SL = safe_cap - ez.
        sl_dist = eff_atr_mult * a
        sl_dist = min(sl_dist, safe_cap - ez)
        sl_dist = max(sl_dist, 0.0)
    else:
        sl_dist = eff_atr_mult * a
        sl_dist = max(sl_dist, sl_cfg.min_sl_pts)
        sl_dist = min(sl_dist, safe_cap)

    if sl_dist <= 0:
        return None

    if d == "BUY":
        atr_sl = p - ez - sl_dist   # = entry_low - sl_dist
    else:
        atr_sl = p + ez + sl_dist   # = entry_high + sl_dist

    plan = _build_plan(d, p, a, atr_sl, "atr_fallback", r1, r2, r3, df, is_scalping,
                       tp1_atr_mult=eff_tp1_atr)
    if plan is not None and sl_cfg.min_sl_pts <= plan.sl_dist <= safe_cap:
        return plan

    return None


# Alias untuk kompatibilitas engine

def swing_based_sltp(
    direction:           str,
    price_now:           float,
    df:                  pd.DataFrame,
    atr:                 float,
    is_scalping:         bool  = False,
    data_by_tf:          dict[str, pd.DataFrame] | None = None,
    tp1_rr:              float = 0.0,
    tp2_rr:              float = 0.0,
    tp3_rr:              float = 0.0,
    entry_atr_frac:      float = 0.3,
    max_sl:              float = 0.0,
    sl_atr_mult_override: float = 0.0,
    tp1_atr_mult_override: float = 0.0,
    **_kwargs,
) -> "SLTPlan | None":
    """SL pivot struktural (PRD §19): _swing_sl → swing ± 0.5×ATR; tanpa pivot valid,
    fallback atr_mult×ATR (scalping 1.2×, intraday 1.5×, override via sl_atr_mult_override).
    df wajib — tanpa df langsung fallback ATR.
    """
    return calc_sltp(
        direction=direction, price_now=price_now, atr=atr,
        is_scalping=is_scalping, tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
        max_sl=max_sl, df=df, sl_atr_mult_override=sl_atr_mult_override,
        tp1_atr_mult_override=tp1_atr_mult_override,
    )


def dynamic_atr_sltp(
    direction:           str,
    price_now:           float,
    atr:                 float,
    is_scalping:         bool  = False,
    tp1_rr:              float = 0.0,
    tp2_rr:              float = 0.0,
    tp3_rr:              float = 0.0,
    entry_atr_frac:      float = 0.3,
    max_sl:              float = 0.0,
    data_by_tf:          dict[str, pd.DataFrame] | None = None,
    df:                  pd.DataFrame | None = None,
    sl_atr_mult_override: float = 0.0,
    tp1_atr_mult_override: float = 0.0,
    **_kwargs,
) -> "SLTPlan | None":
    """ATR-based SL — langsung ke fallback path tanpa coba swing."""
    return calc_sltp(
        direction=direction, price_now=price_now, atr=atr,
        is_scalping=is_scalping, tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
        max_sl=max_sl, df=df, sl_atr_mult_override=sl_atr_mult_override,
        tp1_atr_mult_override=tp1_atr_mult_override,
    )


def fixed_zone_sltp(
    direction:       str,
    price_now:       float,
    entry_zone_pips: float = 30.0,
    sl_pips:         float = 50.0,
    tp1_pips:        float = 70.0,
    tp2_pips:        float = 90.0,
    tp3_pips:        float = 120.0,
    pip_size:        float = 0.1,
) -> "SLTPlan | None":
    """Fixed pip fallback — dipakai hanya jika calc_sltp gagal."""
    try:
        p    = float(price_now)
        ez   = float(entry_zone_pips) * float(pip_size)
        sl_v = float(sl_pips)  * float(pip_size)
        t1   = float(tp1_pips) * float(pip_size)
        t2   = float(tp2_pips) * float(pip_size)
        t3   = float(tp3_pips) * float(pip_size)
    except Exception:
        return None

    d = direction.upper().strip()

    if d == "BUY":
        entry_high, entry_low = p, round(p - ez, 5)
        sl = round(entry_low - sl_v, 5)
        if not (sl < entry_low < entry_high):
            return None
        sl_dist = entry_high - sl
        return SLTPlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=round(entry_high + t1, 5), tp2=round(entry_high + t2, 5),
            tp3=round(entry_high + t3, 5),
            method=f"Fixed BUY sl={sl_pips}p",
            sl_dist=sl_dist,
            rr_tp1=round(t1/sl_dist, 2) if sl_dist > 0 else 0,
            rr_tp2=round(t2/sl_dist, 2) if sl_dist > 0 else 0,
            rr_tp3=round(t3/sl_dist, 2) if sl_dist > 0 else 0,
        )
    if d == "SELL":
        entry_low, entry_high = p, round(p + ez, 5)
        sl = round(entry_high + sl_v, 5)
        if not (entry_low < entry_high < sl):
            return None
        sl_dist = sl - entry_low
        return SLTPlan(
            entry_low=entry_low, entry_high=entry_high, sl=sl,
            tp1=round(entry_low - t1, 5), tp2=round(entry_low - t2, 5),
            tp3=round(entry_low - t3, 5),
            method=f"Fixed SELL sl={sl_pips}p",
            sl_dist=sl_dist,
            rr_tp1=round(t1/sl_dist, 2) if sl_dist > 0 else 0,
            rr_tp2=round(t2/sl_dist, 2) if sl_dist > 0 else 0,
            rr_tp3=round(t3/sl_dist, 2) if sl_dist > 0 else 0,
        )
    return None
