"""zones_snr.py — Deteksi Support & Resistance berbasis swing point historis."""

import numpy as np
import pandas as pd

from src.features.swing_utils import swing_high_prices, swing_low_prices


def cluster_levels(levels: list[float], tolerance: float) -> list[float]:
    """Gabungkan level berdekatan (dalam tolerance) menjadi rata-ratanya."""
    if not levels:
        return []
    sorted_lvl = sorted(levels)
    clusters: list[list[float]] = []
    current = [sorted_lvl[0]]
    for lv in sorted_lvl[1:]:
        if lv - current[-1] <= tolerance:
            current.append(lv)
        else:
            clusters.append(current)
            current = [lv]
    clusters.append(current)
    return [float(np.mean(c)) for c in clusters]


def nearest_level(price: float, levels: list[float]) -> float | None:
    """Kembalikan level yang paling dekat dengan price."""
    return min(levels, key=lambda x: abs(x - price)) if levels else None


def _has_clear_road(
    direction:    str,
    entry_price:  float,
    sl:           float,
    tp1_rr:       float,
    resistances:  list[float],
    supports:     list[float],
    atr:          float,
    block_factor: float = 0.9,
) -> bool:
    """
    Validasi tidak ada S/R kuat menghalangi sebelum TP1.
    BUY: cek resistance antara entry dan 90% jarak TP1.
    SELL: cek support antara entry dan 90% jarak TP1.
    """
    if atr <= 0:
        return True
    sl_dist    = abs(entry_price - sl)
    block_zone = block_factor * sl_dist * tp1_rr
    min_dist   = 0.3 * atr
    if direction.upper() == "BUY":
        return not any(entry_price + min_dist < r <= entry_price + block_zone for r in resistances)
    return not any(entry_price - block_zone <= s < entry_price - min_dist for s in supports)


def snr_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    sl:          float = 0.0,
    tp1_rr:      float = 1.5,
    lookback:    int   = 80,
    near_factor: float = 0.8,
) -> tuple[int, str]:
    """
    Skor konfluensi S/R (0-1).
    Lookback 80 candle = relevan untuk scalping (bukan 2 hari ke belakang).
    near_factor 0.8xATR = lebih sensitif mendeteksi S/R terdekat.
    block_factor 0.7 = lebih ketat blokir resistance sebelum TP.
    """
    if atr <= 0:
        return 0, "SNR_SKIP"

    recent = df.iloc[-lookback:] if len(df) > lookback else df
    highs = swing_high_prices(recent)
    lows  = swing_low_prices(recent)

    ctol        = atr * 0.3
    resistances = cluster_levels(highs, ctol)
    supports    = cluster_levels(lows,  ctol)
    near_thr    = near_factor * atr
    direction   = direction.upper()

    nr = nearest_level(entry_price, resistances)
    ns = nearest_level(entry_price, supports)
    level_str = " ".join(filter(None, [
        f"S~{ns:.2f}" if ns else "",
        f"R~{nr:.2f}" if nr else "",
    ]))

    # block_factor=0.7 lebih ketat — resistance dalam 70% jarak ke TP sudah dianggap blokir
    if sl > 0 and not _has_clear_road(direction, entry_price, sl, tp1_rr, resistances, supports, atr, block_factor=0.7):
        return 0, f"SNR_BLOCKED({level_str})"

    score = 0
    if direction == "BUY":
        sups = [s for s in supports if s <= entry_price]
        if sups and abs(entry_price - max(sups)) <= near_thr:
            score = 1
    else:
        res = [r for r in resistances if r >= entry_price]
        if res and abs(min(res) - entry_price) <= near_thr:
            score = 1

    detail = f"SNR_OK({level_str})" if score > 0 else f"SNR_FAR({level_str})"
    return score, detail
