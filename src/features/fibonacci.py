"""fibonacci.py â€” Fibonacci Retracement untuk XAU/USD."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.features.swing_utils import pivot_highs, pivot_lows


@dataclass(frozen=True)
class FibConfig:
    fib_tf:          str
    pivot_length:    int
    lookback:        int
    min_impulse_atr: float
    zone_tolerance:  float
    strong_levels:   frozenset[float]

FIB_SCALPING_AREA = FibConfig(
    fib_tf="M15", pivot_length=3, lookback=400,
    min_impulse_atr=1.5, zone_tolerance=0.50,
    strong_levels=frozenset({0.382, 0.5, 0.618}),
)
FIB_INTRADAY_AREA = FibConfig(
    fib_tf="H1", pivot_length=4, lookback=500,
    min_impulse_atr=2.0, zone_tolerance=0.60,
    strong_levels=frozenset({0.382, 0.5, 0.618, 0.786}),
)

FIB_H4_CONF = FibConfig(
    fib_tf="H4", pivot_length=5, lookback=300,
    min_impulse_atr=4.0, zone_tolerance=0.30,
    strong_levels=frozenset({0.382, 0.5, 0.618, 0.786}),
)
FIB_H1_CONF = FibConfig(
    fib_tf="H1", pivot_length=4, lookback=300,
    min_impulse_atr=2.5, zone_tolerance=0.40,
    strong_levels=frozenset({0.382, 0.5, 0.618}),
)
FIB_D1_CONF = FibConfig(
    fib_tf="D1", pivot_length=5, lookback=200,
    min_impulse_atr=5.0, zone_tolerance=0.50,
    strong_levels=frozenset({0.382, 0.5, 0.618, 0.786}),
)

_CONF_TFS_SCALPING: tuple[str, ...] = ("H4", "H1")
_CONF_TFS_INTRADAY: tuple[str, ...] = ("D1", "H4")

_CONF_CFG: dict[str, FibConfig] = {
    "H4": FIB_H4_CONF,
    "H1": FIB_H1_CONF,
    "D1": FIB_D1_CONF,
}

_ALL_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
_WEAK_LEVEL = 0.236


def _get_area_config(is_scalping: bool) -> FibConfig:
    return FIB_SCALPING_AREA if is_scalping else FIB_INTRADAY_AREA


def _resolve_fib_df(
    df:         pd.DataFrame,
    target_tf:  str,
    data_by_tf: dict[str, pd.DataFrame] | None,
) -> tuple[pd.DataFrame, float]:
    """Ambil DataFrame TF target dari data_by_tf. Fallback ke df argumen."""
    src_df = df
    if data_by_tf:
        candidate = data_by_tf.get(target_tf.upper())
        if candidate is not None and len(candidate) >= 30:
            src_df = candidate
    atr = 0.0
    if "atr_14" in src_df.columns:
        v = src_df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            atr = float(v)
    return src_df, atr


def _check_fib_confluence(
    conf_tf:     str,
    conf_cfg:    FibConfig,
    direction:   str,
    entry_price: float,
    data_by_tf:  dict[str, pd.DataFrame],
    fallback_atr: float,
) -> bool:
    """Cek apakah entry_price dekat level fib di conf_tf."""
    df_conf = data_by_tf.get(conf_tf)
    if df_conf is None or len(df_conf) < 30:
        return False

    conf_atr = fallback_atr
    if "atr_14" in df_conf.columns:
        v = df_conf["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            conf_atr = float(v)

    min_imp = conf_cfg.min_impulse_atr * conf_atr
    sw = last_swing(df_conf, conf_cfg.lookback, direction, conf_cfg.pivot_length, min_imp)
    if sw is None:
        return False

    levels = fib_levels(*sw[:2], sw[2])
    near   = nearest_fib(entry_price, levels)
    if near is None:
        return False

    _, px     = near
    tolerance = conf_cfg.zone_tolerance * conf_atr
    return abs(entry_price - px) <= tolerance


def last_swing(
    df:           pd.DataFrame,
    lookback:     int,
    direction:    str,
    pivot_length: int   = 3,
    min_impulse:  float = 0.0,
) -> tuple[float, float, str] | None:
    if len(df) < lookback + 5:
        return None

    direction = direction.upper()
    w = df.iloc[-lookback:].reset_index(drop=True)

    p_highs = pivot_highs(w, window=pivot_length)
    p_lows  = pivot_lows(w,  window=pivot_length)

    # Fallback pivot_length lebih kecil jika tidak ada pivot
    if (not p_highs or not p_lows) and pivot_length > 3:
        p_highs = pivot_highs(w, window=3)
        p_lows  = pivot_lows(w,  window=3)

    # Fallback ke min/max absolut jika masih tidak ada pivot
    if not p_highs or not p_lows:
        w2     = df.iloc[-min(lookback, 50):].copy()
        idx_hi = w2["high"].idxmax()
        idx_lo = w2["low"].idxmin()
        s_lo   = float(w2.loc[idx_lo, "low"])
        s_hi   = float(w2.loc[idx_hi, "high"])
        s_dir  = "UP" if idx_lo < idx_hi else "DOWN"
        if direction == "BUY"  and s_dir != "UP":   return None
        if direction == "SELL" and s_dir != "DOWN":  return None
        if min_impulse > 0 and (s_hi - s_lo) < min_impulse:
            return None
        return s_lo, s_hi, s_dir

    if direction == "BUY":
        for lo_idx, lo_val in reversed(p_lows):
            highs_after = [(i, v) for i, v in p_highs if i > lo_idx]
            if not highs_after:
                continue
            _, hi_val = max(highs_after, key=lambda x: x[1])
            if min_impulse > 0 and (hi_val - lo_val) < min_impulse:
                continue
            return lo_val, hi_val, "UP"

    elif direction == "SELL":
        for hi_idx, hi_val in reversed(p_highs):
            lows_after = [(i, v) for i, v in p_lows if i > hi_idx]
            if not lows_after:
                continue
            _, lo_val = min(lows_after, key=lambda x: x[1])
            if min_impulse > 0 and (hi_val - lo_val) < min_impulse:
                continue
            return lo_val, hi_val, "DOWN"

    return None


def recent_swings(
    df:           pd.DataFrame,
    lookback:     int,
    direction:    str,
    pivot_length: int   = 3,
    min_impulse:  float = 0.0,
    max_results:  int   = 3,
) -> list[tuple[float, float, str]]:
    """Cari beberapa swing terakhir, diurutkan dari yang TERBARU.

    Identik dengan last_swing tapi lanjut mencari hingga max_results ditemukan
    atau pivot habis. Dipakai fib_confluence_score sebagai fallback swing lama.
    """
    if len(df) < lookback + 5:
        return []

    direction = direction.upper()
    w = df.iloc[-lookback:].reset_index(drop=True)

    p_highs = pivot_highs(w, window=pivot_length)
    p_lows  = pivot_lows(w,  window=pivot_length)

    if (not p_highs or not p_lows) and pivot_length > 3:
        p_highs = pivot_highs(w, window=3)
        p_lows  = pivot_lows(w,  window=3)

    # Jika tidak ada pivot sama sekali, fallback ke last_swing biasa
    if not p_highs or not p_lows:
        sw = last_swing(df, lookback, direction, pivot_length, min_impulse)
        return [sw] if sw is not None else []

    results: list[tuple[float, float, str]] = []

    if direction == "BUY":
        for lo_idx, lo_val in reversed(p_lows):
            if len(results) >= max_results:
                break
            highs_after = [(i, v) for i, v in p_highs if i > lo_idx]
            if not highs_after:
                continue
            _, hi_val = max(highs_after, key=lambda x: x[1])
            if min_impulse > 0 and (hi_val - lo_val) < min_impulse:
                continue
            sw = (lo_val, hi_val, "UP")
            # Hindari duplikat (swing sangat mirip)
            if not any(abs(r[0] - sw[0]) < 0.01 and abs(r[1] - sw[1]) < 0.01 for r in results):
                results.append(sw)

    elif direction == "SELL":
        for hi_idx, hi_val in reversed(p_highs):
            if len(results) >= max_results:
                break
            lows_after = [(i, v) for i, v in p_lows if i > hi_idx]
            if not lows_after:
                continue
            _, lo_val = min(lows_after, key=lambda x: x[1])
            if min_impulse > 0 and (hi_val - lo_val) < min_impulse:
                continue
            sw = (lo_val, hi_val, "DOWN")
            if not any(abs(r[0] - sw[0]) < 0.01 and abs(r[1] - sw[1]) < 0.01 for r in results):
                results.append(sw)

    return results


def fib_levels(
    swing_low:  float,
    swing_high: float,
    direction:  str,
) -> dict[str, float]:
    diff = swing_high - swing_low
    if diff <= 0:
        return {}
    levels: dict[str, float] = {}
    if direction == "UP":
        for lv in _ALL_LEVELS:
            levels[f"fib_{lv}"] = swing_high - diff * lv
        levels["fib_0"] = swing_high
        levels["fib_1"] = swing_low
    else:
        for lv in _ALL_LEVELS:
            levels[f"fib_{lv}"] = swing_low + diff * lv
        levels["fib_0"] = swing_low
        levels["fib_1"] = swing_high
    return levels


def nearest_fib(
    price:  float,
    levels: dict[str, float],
) -> tuple[str, float] | None:
    if not levels:
        return None
    key = min(levels.keys(), key=lambda k: abs(levels[k] - price))
    return key, float(levels[key])


def _score_level(name: str, px: float, strong_levels: frozenset[float]) -> tuple[int, str]:
    try:
        lv_num = float(name.replace("fib_", ""))
    except ValueError:
        return 1, f"FIB_NEAR({name}={px:.2f})"
    if lv_num in {0.0, 1.0}:    return 0, f"FIB_ENDPOINT({name}={px:.2f})"
    if lv_num == _WEAK_LEVEL:   return 0, f"FIB_WEAK({name}={px:.2f})"
    if lv_num in strong_levels: return 2, f"FIB_STRONG({name}={px:.2f})"
    return 1, f"FIB_NEAR({name}={px:.2f})"


def fib_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    tf:          str  = "",
    is_scalping: bool = False,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
) -> tuple[int, str]:
    """Skor konfluensi Fibonacci: 0, 1, atau 2+bonus.

    Fallback ke swing lama (rank-1/2) jika level swing terbaru terlalu jauh dari entry.
    Tag: FRESH (rank-0) atau FALLBACK_SWING2/3. Confluence set konsisten SNR/SND:
    Scalping = H4+H1; Intraday = D1+H4.
    """
    if atr <= 0:
        return 0, "FIB_SKIP"

    direction = direction.upper()
    cfg       = _get_area_config(is_scalping)

    src_df, src_atr = _resolve_fib_df(df, cfg.fib_tf, data_by_tf)
    eff_atr = src_atr if src_atr > 0 else atr
    min_imp = cfg.min_impulse_atr * eff_atr

    # Fallback ke swing lama (rank-1/2) jika level swing terbaru terlalu jauh dari entry
    swings = recent_swings(src_df, cfg.lookback, direction, cfg.pivot_length, min_imp, max_results=3)
    if not swings:
        return 0, f"FIB_NO_SWING(min={min_imp:.1f})"

    tolerance = cfg.zone_tolerance * eff_atr
    base_score, base_label, swing_tag = 0, "", "FRESH"

    for rank, sw in enumerate(swings):
        levels = fib_levels(*sw[:2], sw[2])
        if not levels:
            continue

        near = nearest_fib(entry_price, levels)
        if near is None:
            continue

        name, px = near
        if abs(entry_price - px) > tolerance:
            continue   # swing ini levelnya jauh, coba swing berikutnya

        sc, lbl = _score_level(name, px, cfg.strong_levels)
        if sc > 0:
            base_score = sc
            base_label = lbl
            swing_tag  = "FRESH" if rank == 0 else f"FALLBACK_SWING{rank + 1}"
            break

    if base_score == 0:
        return 0, f"FIB_FAR(no_swing_near tol={tolerance:.1f})"

    # Multi-TF confluence bonus
    conf_tfs  = _CONF_TFS_SCALPING if is_scalping else _CONF_TFS_INTRADAY
    bonus     = 0
    bonus_tfs: list[str] = []

    if data_by_tf is not None:
        for conf_tf in conf_tfs:
            if conf_tf == cfg.fib_tf.upper():
                continue
            conf_cfg = _CONF_CFG.get(conf_tf)
            if conf_cfg is None:
                continue
            if _check_fib_confluence(conf_tf, conf_cfg, direction,
                                     entry_price, data_by_tf, atr):
                bonus += 1
                bonus_tfs.append(conf_tf)

    bonus_tag = ("+" + "+".join(bonus_tfs)) if bonus_tfs else ""
    return base_score + bonus, f"{base_label}{bonus_tag}|{swing_tag}"


def fib_lookback_for_tf(tf: str) -> int:
    return {"M5": 200, "M15": 200, "H1": 300, "H4": 300, "D1": 200}.get(tf.upper(), 200)


