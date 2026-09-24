from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.swing_utils import (
    swing_high_idx_prices,
    swing_high_prices,
    swing_low_idx_prices,
    swing_low_prices,
)


@dataclass(frozen=True)
class _TFConfig:
    pivot_length:  int
    lookback:      int
    atr_tolerance: float
    min_touches:   int
    min_strength:  int


# min_strength=20 konsisten dengan _touch_score(): 2 touch=20, 3 touch=35, 4+ touch=50
_TF_CONFIG: dict[str, _TFConfig] = {
    "M15": _TFConfig(pivot_length=3, lookback=300, atr_tolerance=0.50, min_touches=2, min_strength=20),
    "H1":  _TFConfig(pivot_length=4, lookback=400, atr_tolerance=0.60, min_touches=2, min_strength=20),
    "H4":  _TFConfig(pivot_length=5, lookback=400, atr_tolerance=0.70, min_touches=2, min_strength=20),
    "D1":  _TFConfig(pivot_length=5, lookback=300, atr_tolerance=0.80, min_touches=2, min_strength=20),
}
_TF_CONFIG_DEFAULT = _TFConfig(pivot_length=3, lookback=300, atr_tolerance=0.50, min_touches=2, min_strength=20)
_CONFLUENCE_TFS_SCALPING = ("H4", "H1", "M15")
_CONFLUENCE_TFS_INTRADAY = ("D1", "H4", "H1")


@dataclass
class SnrZone:
    zone_type:  str
    center:     float
    lower:      float
    upper:      float
    touches:    int
    strength:   float
    timeframes: list[str]     = field(default_factory=list)
    confluence: bool          = False
    age_bars:   int           = 0     
    freshness:  str           = ""    

def _cluster(levels: list[float], tolerance: float) -> list[list[float]]:
    if not levels:
        return []
    sorted_lvl = sorted(levels)
    clusters: list[list[float]] = [[sorted_lvl[0]]]
    for lv in sorted_lvl[1:]:
        last = clusters[-1]
        cluster_width = lv - last[0]
        if lv - last[-1] <= tolerance and cluster_width <= 1.5 * tolerance:
            last.append(lv)
        else:
            clusters.append([lv])
    return clusters


def _cluster_with_idx(
    idx_price_pairs: list[tuple[int, float]],
    tolerance: float,
) -> list[list[tuple[int, float]]]:
    """Cluster (idx, price) berdasarkan harga. Pertahankan idx untuk age_bars."""
    if not idx_price_pairs:
        return []
    sorted_pairs = sorted(idx_price_pairs, key=lambda x: x[1])
    clusters: list[list[tuple[int, float]]] = [[sorted_pairs[0]]]
    for pair in sorted_pairs[1:]:
        last = clusters[-1]
        cluster_width = pair[1] - last[0][1]
        if pair[1] - last[-1][1] <= tolerance and cluster_width <= 1.5 * tolerance:
            last.append(pair)
        else:
            clusters.append([pair])
    return clusters


def _touch_score(touches: int) -> float:
    if touches >= 4: return 50.0
    if touches == 3: return 35.0
    if touches == 2: return 20.0
    return 0.0


def _build_zones(df: pd.DataFrame, tf: str, atr: float) -> list[SnrZone]:
    cfg       = _TF_CONFIG.get(tf.upper(), _TF_CONFIG_DEFAULT)
    recent    = df.iloc[-cfg.lookback:] if len(df) > cfg.lookback else df
    n         = len(recent)
    tolerance = atr * cfg.atr_tolerance
    zones: list[SnrZone] = []

    hi_idx_px = swing_high_idx_prices(recent, left=cfg.pivot_length, right=cfg.pivot_length)
    lo_idx_px = swing_low_idx_prices(recent,  left=cfg.pivot_length, right=cfg.pivot_length)

    for zone_type, idx_px_list in [("RESISTANCE", hi_idx_px), ("SUPPORT", lo_idx_px)]:
        clusters_with_idx = _cluster_with_idx(idx_px_list, tolerance)
        for cluster_pairs in clusters_with_idx:
            touches  = len(cluster_pairs)
            strength = _touch_score(touches)
            if strength < cfg.min_strength:
                continue

            prices   = [p for _, p in cluster_pairs]
            indices  = [i for i, _ in cluster_pairs]
            center   = float(np.mean(prices))
            half     = max(tolerance / 2, atr * 0.15)

            newest_touch_idx = max(indices)
            age_bars         = n - 1 - newest_touch_idx
            freshness        = "FRESH" if age_bars <= cfg.lookback / 3 else "AGED"

            zones.append(SnrZone(
                zone_type=zone_type, center=center,
                lower=center - half, upper=center + half,
                touches=touches, strength=strength,
                timeframes=[tf.upper()],
                age_bars=age_bars, freshness=freshness,
            ))
    return zones


def _merge_confluence(zones_by_tf: dict[str, list[SnrZone]]) -> list[SnrZone]:
    all_zones: list[SnrZone] = []
    for tf_zones in zones_by_tf.values():
        all_zones.extend(tf_zones)

    merged: list[SnrZone] = []
    used   = set()

    for i, z1 in enumerate(all_zones):
        if i in used:
            continue
        combined = SnrZone(
            zone_type=z1.zone_type, center=z1.center, lower=z1.lower,
            upper=z1.upper, touches=z1.touches, strength=z1.strength,
            timeframes=list(z1.timeframes), confluence=False,
            age_bars=z1.age_bars, freshness=z1.freshness,
        )
        for j, z2 in enumerate(all_zones):
            if j <= i or j in used:
                continue
            if z2.zone_type != z1.zone_type:
                continue
            if not (z1.lower <= z2.upper and z2.lower <= z1.upper):
                continue
            if set(z1.timeframes) & set(z2.timeframes):
                continue
            combined.lower      = max(combined.lower, z2.lower)
            combined.upper      = min(combined.upper, z2.upper)
            combined.center     = (combined.lower + combined.upper) / 2
            combined.touches   += z2.touches
            combined.strength   = min(100.0, combined.strength + z2.strength + 30.0)
            combined.timeframes = list(set(combined.timeframes) | set(z2.timeframes))
            combined.confluence = True
            # Freshness gabungan: pakai yang lebih baru (age_bars lebih kecil = lebih fresh)
            if z2.age_bars < combined.age_bars:
                combined.age_bars  = z2.age_bars
                combined.freshness = z2.freshness
            used.add(j)

        used.add(i)
        merged.append(combined)
    return merged


def _has_clear_road(
    direction:    str,
    entry:        float,
    sl:           float,
    tp1_rr:       float,
    zones:        list[SnrZone],
    atr:          float,
    block_factor: float = 0.7,
) -> bool:
    """Cek jalur ke TP bebas hambatan. Cek SEMUA zona (FRESH+AGED) tanpa pembedaan.
    Level lama tetap bisa jadi penghalang efektif — tidak dilemahkan oleh fallback logic.
    """
    if sl <= 0 or atr <= 0:
        return True
    sl_dist    = abs(entry - sl)
    block_dist = block_factor * sl_dist * tp1_rr
    min_dist   = 0.3 * atr

    if direction == "BUY":
        return not any(
            z.zone_type == "RESISTANCE"
            and entry + min_dist < z.center <= entry + block_dist
            for z in zones
        )
    return not any(
        z.zone_type == "SUPPORT"
        and entry - block_dist <= z.center < entry - min_dist
        for z in zones
    )


def build_snr_zones(
    df:          pd.DataFrame,
    tf:          str,
    atr:         float,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
    is_scalping: bool = True,
) -> list[SnrZone]:
    """Bangun SnrZone dengan multi-TF confluence.

    is_scalping=True  → confluence set: H4+H1+M15
    is_scalping=False → confluence set: D1+H4+H1
    """
    if atr <= 0:
        return []
    tf_upper      = tf.upper()
    conf_tfs      = _CONFLUENCE_TFS_SCALPING if is_scalping else _CONFLUENCE_TFS_INTRADAY

    if data_by_tf is None:
        return _build_zones(df, tf_upper, atr)

    zones_by_tf: dict[str, list[SnrZone]] = {}
    for conf_tf in conf_tfs:
        src_df = data_by_tf.get(conf_tf)
        if src_df is None or len(src_df) < 30:
            continue
        tf_atr = atr
        if "atr_14" in src_df.columns:
            v = src_df["atr_14"].iloc[-2]
            if pd.notna(v) and float(v) > 0:
                tf_atr = float(v)
        zones_by_tf[conf_tf] = _build_zones(src_df, conf_tf, tf_atr)

    if tf_upper not in zones_by_tf:
        zones_by_tf[tf_upper] = _build_zones(df, tf_upper, atr)

    return _merge_confluence(zones_by_tf)


def snr_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
    tf:          str   = "",
    near_factor: float = 1.2,   # Dinaikkan dari 0.8: radius "dekat zona valid" lebih longgar
    is_scalping: bool  = True,
) -> tuple[int, str]:
    """Skor konfluensi S/R: 0 atau 1.

    Search: FRESH (near_factor ketat) dulu, lalu AGED (longgar +0.3×ATR) → tag AGED_FALLBACK.
    Obstacle check (_has_clear_road) tetap cek SEMUA zona.
    """
    if atr <= 0:
        return 0, "SNR_SKIP"

    direction = direction.upper()
    tf_upper  = tf.upper() if tf else ""
    zones     = build_snr_zones(df, tf_upper or "M15", atr, data_by_tf, is_scalping=is_scalping)
    if not zones:
        return 0, "SNR_NO_ZONE"

    near_thr_fresh = near_factor * atr
    near_thr_aged  = (near_factor + 0.3) * atr   # lebih longgar untuk level lama yang lebih "mayor"

    if direction == "BUY":
        same_type = [z for z in zones
                     if z.zone_type == "SUPPORT" and z.center <= entry_price]
    else:
        same_type = [z for z in zones
                     if z.zone_type == "RESISTANCE" and z.center >= entry_price]

    if not same_type:
        all_same = [z for z in zones
                    if z.zone_type == ("SUPPORT" if direction == "BUY" else "RESISTANCE")]
        if all_same:
            nearest = min(all_same, key=lambda z: abs(z.center - entry_price))
            return 0, f"SNR_FAR(nearest={nearest.center:.2f} t={nearest.touches})"
        return 0, "SNR_FAR(no_zone)"

    fresh_cands = [z for z in same_type
                   if z.freshness == "FRESH"
                   and abs(entry_price - z.center) <= near_thr_fresh]
    aged_cands  = [z for z in same_type
                   if abs(entry_price - z.center) <= near_thr_aged]

    if fresh_cands:
        best = max(fresh_cands, key=lambda z: z.strength)
        tag  = "FRESH"
    elif aged_cands:
        best = max(aged_cands, key=lambda z: z.strength)
        tag  = "AGED_FALLBACK"
    else:
        nearest = min(same_type, key=lambda z: abs(z.center - entry_price))
        return 0, f"SNR_FAR(nearest={nearest.center:.2f} t={nearest.touches} {nearest.freshness})"

    if sl > 0 and not _has_clear_road(direction, entry_price, sl, tp1_rr, zones, atr):
        return 0, f"SNR_BLOCKED(clear_road {best.zone_type[:3]}={best.center:.2f})"

    tfs_str  = "+".join(sorted(best.timeframes))
    conf_tag = " MTF" if best.confluence else ""
    age_tag  = f" age={best.age_bars}b"
    return 1, (f"SNR_OK({best.zone_type[:3]}={best.center:.2f}"
               f" t={best.touches} str={best.strength:.0f}"
               f" tf={tfs_str}{conf_tag} {tag}{age_tag})")
