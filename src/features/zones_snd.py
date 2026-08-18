"""zones_snd.py — Deteksi zona Supply & Demand berbasis konsolidasi harga."""

import pandas as pd


def detect_base_zone(
    df: pd.DataFrame,
    window: int = 5,
    max_range_ratio: float = 0.3,
) -> tuple[float, float] | None:
    """
    Deteksi zona konsolidasi (base zone) dari N candle terakhir.
    Returns (zone_low, zone_high) atau None jika tidak ada zona valid.
    """
    if len(df) < window + 2:
        return None

    recent = df.iloc[-(window + 2): -2]
    highs  = recent["high"].astype(float)
    lows   = recent["low"].astype(float)
    atr    = df["atr_14"].iloc[-2] if "atr_14" in df.columns else None

    zone_high = float(highs.max())
    zone_low  = float(lows.min())
    zone_range = zone_high - zone_low

    if zone_range <= 0:
        return None
    if atr is not None and pd.notna(atr) and float(atr) > 0:
        if zone_range > max_range_ratio * float(atr) * window:
            return None

    return zone_low, zone_high


def snd_confluence_score(
    direction:   str,
    entry_price: float,
    df:          pd.DataFrame,
    atr:         float,
    near_factor: float = 1.0,
) -> tuple[int, str]:
    """
    Skor konfluensi Supply & Demand (0 atau 1).
    +1 jika entry berada dalam zona konsolidasi yang relevan.
    Dicoba dari window kecil ke besar (3, 5, 7 candle).
    """
    if atr <= 0:
        return 0, "SND_SKIP"

    zone = None
    for w in [3, 5, 7]:
        zone = detect_base_zone(df, window=w)
        if zone is not None:
            break

    if zone is None:
        return 0, "SND_NO_ZONE"

    zone_low, zone_high = zone
    zone_mid = (zone_low + zone_high) / 2

    if abs(entry_price - zone_mid) <= near_factor * atr:
        label = "SUPPLY" if direction.upper() == "SELL" else "DEMAND"
        return 1, f"SND_{label}({zone_low:.2f}-{zone_high:.2f})"

    return 0, f"SND_FAR({zone_low:.2f}-{zone_high:.2f})"
