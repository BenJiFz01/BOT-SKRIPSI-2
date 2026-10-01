"""zones_snd.py — Deteksi zona Supply & Demand berbasis historical impulse."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class _SndConfig:
    lookback:         int
    impulse_body_atr: float
    base_max_range:   float
    min_impulse_dist: float


_TF_CONFIG: dict[str, _SndConfig] = {
    "M5":  _SndConfig(lookback=150, impulse_body_atr=1.2, base_max_range=0.9, min_impulse_dist=1.2),
    "M15": _SndConfig(lookback=250, impulse_body_atr=1.2, base_max_range=0.9, min_impulse_dist=1.2),
    "H1":  _SndConfig(lookback=300, impulse_body_atr=1.5, base_max_range=0.8, min_impulse_dist=1.5),
    "H4":  _SndConfig(lookback=300, impulse_body_atr=2.0, base_max_range=0.7, min_impulse_dist=2.0),
    "D1":  _SndConfig(lookback=250, impulse_body_atr=2.0, base_max_range=0.7, min_impulse_dist=2.0),
}
_TF_CONFIG_DEFAULT = _SndConfig(lookback=200, impulse_body_atr=1.2, base_max_range=0.9, min_impulse_dist=1.2)

# Confluence set per mode (sama pola seperti SNR):
#   Scalping: H4+H1; Intraday: D1+H4 (D1 untuk validasi zona major intraday)
_CONFLUENCE_TFS_SCALPING = ("H4", "H1")
_CONFLUENCE_TFS_INTRADAY = ("D1", "H4")

_BASE_WINDOW    = 6
_NEAR_ENTRY_ATR = 1.2   # Radius "dekat zona valid" (×ATR)


def _get_atr(df: pd.DataFrame) -> float:
    if "atr_14" in df.columns:
        v = df["atr_14"].dropna()
        if len(v) > 0:
            val = float(v.iloc[-2] if len(v) >= 2 else v.iloc[-1])
            if val > 0:
                return val
    trs = (df.tail(15)["high"] - df.tail(15)["low"]).abs()
    return float(trs.mean()) if len(trs) > 0 else 0.0


def _count_zone_touches(
    after:     pd.DataFrame,
    zone_low:  float,
    zone_high: float,
    bullish:   bool,
) -> tuple[int, bool]:
    """Hitung touch zona secara vectorized (numpy).

    Returns (touch_count: 0=fresh, 1=retest, 2+=exhausted; zone_held: False jika ada
    close yang menembus sisi seberang). Candle break terakhir ikut dihitung touch.
    """
    if len(after) == 0:
        return 0, True

    lows   = after["low"].to_numpy(dtype=float)
    highs  = after["high"].to_numpy(dtype=float)
    closes = after["close"].to_numpy(dtype=float)

    if bullish:
        broken = closes < zone_low
    else:
        broken = closes > zone_high

    break_idx = int(np.argmax(broken)) if broken.any() else len(after)

    # Hanya hitung touch sebelum (atau sampai) break point
    lows_pre  = lows[:break_idx]
    highs_pre = highs[:break_idx]

    # Touch = candle overlap zona (cek dua sisi)
    if bullish:
        entered = (lows_pre <= zone_high) & (highs_pre >= zone_low)
    else:
        entered = (highs_pre >= zone_low) & (lows_pre <= zone_high)

    touch_count = int(entered.sum())

    if broken.any():
        return touch_count + 1, False   # candle break dihitung touch terakhir
    return touch_count, True


def _find_zones(
    df:      pd.DataFrame,
    atr:     float,
    cfg:     _SndConfig,
    bullish: bool,
) -> list[dict]:
    zones: list[dict] = []
    if atr <= 0 or len(df) < cfg.lookback + 5:
        return zones

    data = df.iloc[-(cfg.lookback + 2):-1].reset_index(drop=True)
    n    = len(data)

    for i in range(_BASE_WINDOW, n - 2):
        c      = data.iloc[i]
        c_open  = float(c.get("open",  0))
        c_close = float(c.get("close", 0))

        body = (c_close - c_open) if bullish else (c_open - c_close)
        if body < cfg.impulse_body_atr * atr:
            continue

        base_slice = data.iloc[max(0, i - _BASE_WINDOW):i]
        if len(base_slice) < 2:
            continue

        base_high  = float(base_slice["high"].max())
        base_low   = float(base_slice["low"].min())
        base_range = base_high - base_low

        if base_range > cfg.base_max_range * atr:
            continue

        impulse_dist = (c_close - base_high) if bullish else (base_low - c_close)
        if impulse_dist < cfg.min_impulse_dist * atr:
            continue

        after = data.iloc[i + 1:]
        if len(after) > 0:
            touch_count, zone_held = _count_zone_touches(after, base_low, base_high, bullish)
            if touch_count >= 2:
                continue   # exhausted — terlalu sering disentuh
            if touch_count == 1 and not zone_held:
                continue   # close menembus zona = rusak
            # touch_count == 0: fresh (strength penuh)
            # touch_count == 1 + held: valid retest, strength dikurangi 1
        else:
            touch_count = 0

        # Freshness dari umur formasi — independen dari touch_count (zona baru ≠ zona lama)
        age_bars  = n - i
        freshness = "FRESH" if age_bars <= cfg.lookback / 3 else "AGED"

        strength = 1
        if impulse_dist >= cfg.min_impulse_dist * atr * 2: strength += 1
        if base_range   <= 0.4 * atr:                      strength += 1
        if touch_count  == 1:                              strength  = max(1, strength - 1)

        zones.append({
            "type":         "DEMAND" if bullish else "SUPPLY",
            "zone_low":     base_low,
            "zone_high":    base_high,
            "mid":          (base_low + base_high) / 2,
            "zone_mid":     (base_low + base_high) / 2,
            "impulse_dist": impulse_dist,
            "strength":     strength,
            "touch_count":  touch_count,
            "age_bars":     age_bars,
            "freshness":    freshness,
            "timeframes":   [],
        })
    return zones


def _apply_mtf_confluence(zones: list[dict], atr: float, tf_zones: list[dict], tf_name: str) -> None:
    for z in zones:
        for tz in tf_zones:
            if tz["type"] != z["type"]:
                continue
            if z["zone_low"] <= tz["zone_high"] and tz["zone_low"] <= z["zone_high"]:
                z["strength"] = min(100, z["strength"] + 20)
                if tf_name not in z["timeframes"]:
                    z["timeframes"].append(tf_name)
                break


def _best_zone_near_entry(
    zones:       list[dict],
    entry_price: float,
    near_thr:    float,
    atr:         float,
) -> dict | None:
    """Pilih zona terbaik dekat entry: FRESH (ketat near_thr) dulu, lalu AGED
    fallback (longgar near_thr+0.3×ATR). Dalam kategori: utamakan (touch_count==1,
    strength) lebih tinggi.
    """
    near_thr_aged = near_thr + 0.3 * atr

    def _composite(z: dict) -> tuple:
        """Key sorting: (is_fresh, has_retest, strength, -dist)."""
        dist      = min(abs(entry_price - z["zone_low"]), abs(entry_price - z["zone_high"]))
        is_fresh  = 1 if z.get("freshness") == "FRESH" else 0
        has_retest = 1 if z.get("touch_count", 0) == 1 else 0
        return (is_fresh, has_retest, z["strength"], -dist)

    # FRESH — near_thr ketat
    fresh_cands = [
        z for z in zones
        if z.get("freshness") == "FRESH"
        and min(abs(entry_price - z["mid"]),
                abs(entry_price - z["zone_low"]),
                abs(entry_price - z["zone_high"])) <= near_thr
    ]
    if fresh_cands:
        return max(fresh_cands, key=_composite)

    # AGED fallback — near_thr lebih longgar
    aged_cands = [
        z for z in zones
        if min(abs(entry_price - z["mid"]),
               abs(entry_price - z["zone_low"]),
               abs(entry_price - z["zone_high"])) <= near_thr_aged
    ]
    return max(aged_cands, key=_composite) if aged_cands else None


def snd_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    tf:          str  = "",
    near_factor: float = _NEAR_ENTRY_ATR,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
    is_scalping: bool = True,
) -> tuple[int, str]:
    """
    Skor konfluensi Supply & Demand: 0 atau 1.

    Confluence set: True → H4+H1; False → D1+H4 (D1 untuk zona major intraday).
    """
    if atr <= 0:
        return 0, "SND_SKIP"

    direction = direction.upper()
    tf_upper  = tf.upper() if tf else ""
    cfg       = _TF_CONFIG.get(tf_upper, _TF_CONFIG_DEFAULT)
    bullish   = direction == "BUY"
    zone_type = "DEMAND" if bullish else "SUPPLY"
    conf_tfs  = _CONFLUENCE_TFS_SCALPING if is_scalping else _CONFLUENCE_TFS_INTRADAY

    zones = _find_zones(df, atr, cfg, bullish)
    if not zones:
        return 0, f"SND_NO_ZONE({zone_type})"

    if data_by_tf is not None:
        for conf_tf in conf_tfs:
            if conf_tf == tf_upper:
                continue
            src_df = data_by_tf.get(conf_tf)
            if src_df is None or len(src_df) < 30:
                continue
            conf_atr = atr
            if "atr_14" in src_df.columns:
                v = src_df["atr_14"].iloc[-2]
                if pd.notna(v) and float(v) > 0:
                    conf_atr = float(v)
            conf_cfg   = _TF_CONFIG.get(conf_tf, _TF_CONFIG_DEFAULT)
            conf_zones = _find_zones(src_df, conf_atr, conf_cfg, bullish)
            if conf_zones:
                _apply_mtf_confluence(zones, atr, conf_zones, conf_tf)

    best_zone = _best_zone_near_entry(zones, entry_price, near_factor * atr, atr)
    if best_zone is None:
        closest = min(zones, key=lambda z: abs(entry_price - z["mid"]))
        return 0, (f"SND_FAR({zone_type} "
                   f"{closest['zone_low']:.2f}-{closest['zone_high']:.2f} "
                   f"dist={abs(entry_price - closest['mid']):.1f})")

    z         = best_zone
    tf_tag    = "+" + "+".join(z["timeframes"]) if z["timeframes"] else ""
    touch_tag = f" t={z['touch_count']}" if z.get("touch_count", 0) > 0 else ""
    fresh_tag = f" {z.get('freshness', '')}" if z.get("freshness") else ""
    age_tag   = f" age={z.get('age_bars', 0)}b"
    return 1, (f"SND_{zone_type}({z['zone_low']:.2f}-{z['zone_high']:.2f}"
               f" str={z['strength']}{tf_tag}{touch_tag}{fresh_tag}{age_tag}"
               f" imp={z['impulse_dist']:.1f})")
