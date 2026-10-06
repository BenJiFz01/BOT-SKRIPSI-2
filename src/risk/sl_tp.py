"""sl_tp.py — Stop Loss & Take Profit: ATR-based dengan swing anchor dan clamp.

SL = min(swing_sl, atr_sl) untuk BUY (terjauh dari entry),
     max(swing_sl, atr_sl) untuk SELL (terjauh dari entry).
  - swing_sl = pivot ± (buffer_atr × ATR)
  - atr_sl = entry_high/low ± (sl_atr_mult × ATR) — dari sisi entry yang sama
  - Clamp: min = spread × min_spread_mult, max = max_atr_mult × ATR
  
TP = entry ± (sl_dist × tp_rr), dengan obstacle adjustment TP1/TP2.
Reject jika SL di luar clamp range.
"""
import math
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from src.features.swing_utils import pivot_highs, pivot_lows


@dataclass(frozen=True)
class _AtrSlConfig:
    atr_len:           int     # ATR(N)
    sl_atr_mult:       float   # SL = sl_atr_mult × ATR
    sl_buffer_atr:     float   # swing buffer = sl_buffer_atr × ATR
    min_spread_mult:   float   # min SL = spread × min_spread_mult
    max_atr_mult:      float   # max SL = max_atr_mult × ATR
    tp1_rr:            float   # TP1 = tp1_rr × sl_dist
    tp2_rr:            float
    tp3_rr:            float
    close_pct:         tuple[float, float, float]  # allocation TP1/TP2/TP3


_EZ_FRAC = 0.3
_CACHE_SCALPING: _AtrSlConfig | None = None
_CACHE_INTRADAY: _AtrSlConfig | None = None


def _validate_config(cfg: _AtrSlConfig, mode: str) -> None:
    """Validasi config saat load — gagal keras jika ada yang salah."""
    if not (cfg.tp1_rr < cfg.tp2_rr < cfg.tp3_rr):
        raise ValueError(
            f"{mode}: TP RR harus ascending (tp1 < tp2 < tp3), dapat: "
            f"{cfg.tp1_rr}/{cfg.tp2_rr}/{cfg.tp3_rr}"
        )
    if abs(sum(cfg.close_pct) - 1.0) > 0.01:
        raise ValueError(
            f"{mode}: close_pct harus sum=1.0, dapat: {sum(cfg.close_pct)}"
        )
    if cfg.sl_atr_mult >= cfg.max_atr_mult:
        raise ValueError(
            f"{mode}: sl_atr_mult ({cfg.sl_atr_mult}) harus < max_atr_mult ({cfg.max_atr_mult})"
        )
    if cfg.min_spread_mult <= 0:
        raise ValueError(f"{mode}: min_spread_mult harus > 0, dapat: {cfg.min_spread_mult}")


def get_atr_config(is_scalping: bool) -> _AtrSlConfig:
    """Load config dari settings (dengan cache). Validasi ketat saat pertama kali load."""
    global _CACHE_SCALPING, _CACHE_INTRADAY
    
    if is_scalping:
        if _CACHE_SCALPING is None:
            from src.config.settings import load_settings
            s = load_settings()
            _CACHE_SCALPING = _AtrSlConfig(
                atr_len=s.scalping_atr_len,
                sl_atr_mult=s.scalping_sl_atr_mult,
                sl_buffer_atr=s.scalping_sl_buffer_atr,
                min_spread_mult=s.scalping_min_spread_mult,
                max_atr_mult=s.scalping_max_atr_mult,
                tp1_rr=s.scalping_tp1_rr,
                tp2_rr=s.scalping_tp2_rr,
                tp3_rr=s.scalping_tp3_rr,
                close_pct=(0.5, 0.3, 0.2),
            )
            _validate_config(_CACHE_SCALPING, "SCALPING")
        return _CACHE_SCALPING
    else:
        if _CACHE_INTRADAY is None:
            from src.config.settings import load_settings
            s = load_settings()
            _CACHE_INTRADAY = _AtrSlConfig(
                atr_len=s.intraday_atr_len,
                sl_atr_mult=s.intraday_sl_atr_mult,
                sl_buffer_atr=s.intraday_sl_buffer_atr,
                min_spread_mult=s.intraday_min_spread_mult,
                max_atr_mult=s.intraday_max_atr_mult,
                tp1_rr=s.intraday_tp1_rr,
                tp2_rr=s.intraday_tp2_rr,
                tp3_rr=s.intraday_tp3_rr,
                close_pct=(0.4, 0.3, 0.3),
            )
            _validate_config(_CACHE_INTRADAY, "INTRADAY")
        return _CACHE_INTRADAY


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
    reject_reason: str  = field(default="")


def _valid(*values: float) -> bool:
    return all(math.isfinite(v) and v > 0 for v in values)


def _find_swing_point(
    direction: str,
    price_now: float,
    df: pd.DataFrame,
    lookback: int = 40,
) -> float | None:
    """Cari swing high/low terdekat untuk anchor SL struktural."""
    if len(df) < lookback + 10:
        return None
    recent = df.iloc[-(lookback + 2):-1].reset_index(drop=True)

    if direction == "BUY":
        cands = sorted(
            [v for _, v in pivot_lows(recent, window=3) if v < price_now],
            reverse=True,
        )
        return cands[0] if cands else None
    else:
        cands = sorted(
            [v for _, v in pivot_highs(recent, window=3) if v > price_now]
        )
        return cands[0] if cands else None


def _find_tp_obstacle(
    direction: str,
    entry:     float,
    tp_target: float,
    atr:       float,
    df:        pd.DataFrame,
) -> float | None:
    """Cari level S/R antara entry dan TP."""
    if len(df) < 20:
        return None
    recent = df.iloc[-32:-1].reset_index(drop=True)
    if direction == "BUY":
        cands = [v for _, v in pivot_highs(recent, window=3)
                 if entry < v < tp_target]
        return min(cands) if cands else None
    else:
        cands = [v for _, v in pivot_lows(recent, window=3)
                 if tp_target < v < entry]
        return max(cands) if cands else None


def _adjust_tp_for_obstacle(
    direction: str,
    entry:     float,
    tp:        float,
    atr:       float,
    sl_dist:   float,
    df:        pd.DataFrame,
    min_rr:    float = 0.8,
    spread:    float = 0.3,
) -> float:
    """Geser TP sebelum obstacle jika RR masih terjaga.
    
    Margin = max(0.1×ATR, spread) untuk hindari TP terlalu dekat dengan S/R.
    Jika margin hanya 0.1×ATR (mis. 0.15pt pada ATR 1.5) < spread (0.30),
    harga bisa sentuh obstacle lalu bounce sebelum TP terisi.
    """
    obstacle = _find_tp_obstacle(direction, entry, tp, atr, df)
    if obstacle is None:
        return tp
    margin = max(0.1 * atr, spread)
    adjusted = (obstacle - margin) if direction == "BUY" else (obstacle + margin)
    if sl_dist > 0 and abs(adjusted - entry) / sl_dist >= min_rr:
        return adjusted
    return tp


def calc_sltp(
    direction:   str,
    price_now:   float,
    atr:         float,
    spread:      float,
    is_scalping: bool = False,
    df:          pd.DataFrame | None = None,
    **_kwargs,
) -> SLTPlan | None:
    """ATR-based SL/TP dengan clamp min/max.
    
    Flow:
    1. Hitung swing_sl = swing ± (buffer_atr × ATR)
    2. Hitung atr_sl = entry_high/low ± (sl_atr_mult × ATR) dari ref_entry
    3. SL = min(swing_sl, atr_sl) untuk BUY (terjauh dari entry)
         SL = max(swing_sl, atr_sl) untuk SELL (terjauh dari entry)
    4. Clamp SL: [spread × min_spread_mult, ATR × max_atr_mult]
    5. Reject jika SL di luar clamp
    6. TP = entry ± (sl_dist × tp_rr)
    """
    try:
        p, a, s = float(price_now), float(atr), float(spread)
        d = direction.upper().strip()
    except Exception:
        return None
    if not _valid(p, a) or s < 0 or d not in ("BUY", "SELL"):
        return None

    cfg = get_atr_config(is_scalping)
    
    ez = _EZ_FRAC * a
    buffer = cfg.sl_buffer_atr * a
    
    sl_min = s * cfg.min_spread_mult
    sl_max = a * cfg.max_atr_mult

    swing_point = _find_swing_point(d, p, df, lookback=40) if df is not None and len(df) >= 50 else None
    
    if d == "BUY":
        entry_high = p
        entry_low = round(p - ez, 5)
        ref_entry = entry_high
        sign = 1
        
        if swing_point is not None:
            swing_sl = swing_point - buffer
        else:
            swing_sl = None
        
        atr_sl = entry_high - (cfg.sl_atr_mult * a)
        
        if swing_sl is not None:
            sl_candidate = min(swing_sl, atr_sl)
            sl_source = "swing+atr"
        else:
            sl_candidate = atr_sl
            sl_source = "atr_only"
        
        sl_dist = entry_high - sl_candidate
        
        if sl_dist < sl_min:
            return SLTPlan(
                entry_low=entry_low, entry_high=entry_high, sl=0, tp1=0, tp2=0, tp3=0,
                method="REJECT", reject_reason="SL_TOO_TIGHT", atr_used=a, sl_dist=sl_dist,
            )
        if sl_dist > sl_max:
            return SLTPlan(
                entry_low=entry_low, entry_high=entry_high, sl=0, tp1=0, tp2=0, tp3=0,
                method=f"REJECT {d}", reject_reason=f"SL_OUT_OF_BOUNDS(sl={sl_dist:.1f}/max={sl_max:.1f}/atr={a:.1f}/{sl_dist/a:.2f}x)",
                atr_used=a, sl_dist=sl_dist, sl_source=sl_source,
            )

        sl = round(entry_high - sl_dist, 5)
        
        if not (sl < entry_low < entry_high):
            return None
        
    else:
        entry_low = p
        entry_high = round(p + ez, 5)
        ref_entry = entry_low
        sign = -1
        
        if swing_point is not None:
            swing_sl = swing_point + buffer
        else:
            swing_sl = None
        
        atr_sl = entry_low + (cfg.sl_atr_mult * a)
        
        if swing_sl is not None:
            sl_candidate = max(swing_sl, atr_sl)
            sl_source = "swing+atr"
        else:
            sl_candidate = atr_sl
            sl_source = "atr_only"
        
        sl_dist = sl_candidate - entry_low
        
        if sl_dist < sl_min:
            return SLTPlan(
                entry_low=entry_low, entry_high=entry_high, sl=0, tp1=0, tp2=0, tp3=0,
                method="REJECT", reject_reason="SL_TOO_TIGHT", atr_used=a, sl_dist=sl_dist,
            )
        if sl_dist > sl_max:
            return SLTPlan(
                entry_low=entry_low, entry_high=entry_high, sl=0, tp1=0, tp2=0, tp3=0,
                method=f"REJECT {d}", reject_reason=f"SL_OUT_OF_BOUNDS(sl={sl_dist:.1f}/max={sl_max:.1f}/atr={a:.1f}/{sl_dist/a:.2f}x)",
                atr_used=a, sl_dist=sl_dist, sl_source=sl_source,
            )

        sl = round(entry_low + sl_dist, 5)
        
        if not (entry_low < entry_high < sl):
            return None

    tp1 = round(ref_entry + sign * sl_dist * cfg.tp1_rr, 5)
    tp2 = round(ref_entry + sign * sl_dist * cfg.tp2_rr, 5)
    tp3 = round(ref_entry + sign * sl_dist * cfg.tp3_rr, 5)

    if df is not None and len(df) >= 20:
        from src.config.settings import load_settings
        settings = load_settings()
        min_rr_frac = settings.obstacle_min_rr_frac
        
        tp1 = round(_adjust_tp_for_obstacle(d, ref_entry, tp1, a, sl_dist, df, min_rr=min_rr_frac * cfg.tp1_rr, spread=s), 5)
        tp2 = round(_adjust_tp_for_obstacle(d, ref_entry, tp2, a, sl_dist, df, min_rr=min_rr_frac * cfg.tp2_rr, spread=s), 5)
        tp3 = round(_adjust_tp_for_obstacle(d, ref_entry, tp3, a, sl_dist, df, min_rr=min_rr_frac * cfg.tp3_rr, spread=s), 5)

    # Validasi urutan TP dan jarak minimum antar TP (0.2R = 20% sl_dist)
    # Test 1 obstacle kasus: TP1=1.0R, TP2 adjusted=1.22R -> gap=0.22R >= 0.2R (lolos)
    _min_tp_gap = 0.2 * sl_dist
    _reject_tp = SLTPlan(
        entry_low=entry_low, entry_high=entry_high, sl=0, tp1=0, tp2=0, tp3=0,
        method="REJECT", reject_reason="TP_ORDER_INVALID", atr_used=a, sl_dist=sl_dist,
    )
    if d == "BUY":
        if not (sl < entry_low < entry_high < tp1 < tp2 < tp3):
            return _reject_tp
        if (tp2 - tp1) < _min_tp_gap or (tp3 - tp2) < _min_tp_gap:
            return _reject_tp
    else:
        if not (tp3 < tp2 < tp1 < entry_low < entry_high < sl):
            return _reject_tp
        if (tp1 - tp2) < _min_tp_gap or (tp2 - tp3) < _min_tp_gap:
            return _reject_tp

    rr1 = abs(tp1 - ref_entry) / sl_dist if sl_dist > 0 else 0
    rr2 = abs(tp2 - ref_entry) / sl_dist if sl_dist > 0 else 0
    rr3 = abs(tp3 - ref_entry) / sl_dist if sl_dist > 0 else 0

    mode = "SCAL" if is_scalping else "INTRA"
    return SLTPlan(
        entry_low=entry_low, entry_high=entry_high, sl=sl,
        tp1=tp1, tp2=tp2, tp3=tp3,
        method=f"{mode} {d} | {sl_source} sl={sl_dist:.1f}pt atr={a:.1f}",
        atr_used=a, sl_dist=sl_dist,
        rr_tp1=round(rr1, 2), rr_tp2=round(rr2, 2), rr_tp3=round(rr3, 2),
        sl_source=sl_source,
    )


def swing_based_sltp(
    direction:   str,
    price_now:   float,
    df:          pd.DataFrame,
    atr:         float,
    spread:      float = 0.3,
    is_scalping: bool = False,
    **_kwargs,
) -> SLTPlan | None:
    """Alias untuk kompatibilitas dengan engine."""
    return calc_sltp(direction, price_now, atr, spread, is_scalping, df)


def dynamic_atr_sltp(
    direction:   str,
    price_now:   float,
    atr:         float,
    spread:      float = 0.3,
    is_scalping: bool = False,
    df:          pd.DataFrame | None = None,
    **_kwargs,
) -> SLTPlan | None:
    """Alias untuk kompatibilitas dengan engine."""
    return calc_sltp(direction, price_now, atr, spread, is_scalping, df)


def fixed_zone_sltp(
    direction:       str,
    price_now:       float,
    entry_zone_pips: float = 30.0,
    sl_pips:         float = 50.0,
    tp1_pips:        float = 70.0,
    tp2_pips:        float = 90.0,
    tp3_pips:        float = 120.0,
    pip_size:        float = 0.1,
) -> SLTPlan | None:
    """Fixed pip fallback (DEPRECATED, hanya untuk emergency fallback)."""
    try:
        p = float(price_now)
        ez = float(entry_zone_pips) * float(pip_size)
        sl_v = float(sl_pips) * float(pip_size)
        t1 = float(tp1_pips) * float(pip_size)
        t2 = float(tp2_pips) * float(pip_size)
        t3 = float(tp3_pips) * float(pip_size)
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


def get_sl_config(is_scalping: bool):
    """Legacy compatibility."""
    return get_atr_config(is_scalping)


def get_tp_config(is_scalping: bool):
    """Legacy compatibility."""
    return get_atr_config(is_scalping)
