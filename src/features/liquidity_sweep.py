"""liquidity_sweep.py — Deteksi liquidity sweep (stop-hunt) untuk konfluensi scalping.

Wick menembus swing high/low (kena kluster SL) lalu close kembali ke dalam range
sebelum entry — menjawab masalah "SL kena wick dulu baru profit". Swing dari swing_utils.
"""
from __future__ import annotations

import pandas as pd

from src.features.swing_utils import swing_high_idx_prices, swing_low_idx_prices


_LOOKBACK_BARS    = 30   # jarak max swing yang dipertimbangkan dari now (bar)
_MIN_WICK_RATIO   = 0.30 # fraksi minimum range candle yang menembus level (0.5->0.3, 2026-09-24)
_RECENT_BARS      = 10   # candle sweep harus dalam N bar terakhir (closed) (6->10, 2026-09-24)
_PIVOT_WINDOW     = 3    # window pivot swing (konsisten dengan swing_utils)


def detect_liquidity_sweep(
    df:             pd.DataFrame,
    direction:      str,
    lookback:       int  = _LOOKBACK_BARS,
    min_wick_ratio: float = _MIN_WICK_RATIO,
) -> tuple[bool, dict]:
    """Deteksi liquidity sweep di bar tertutup terakhir (bar terakhir = live, dilewati).

    'BUY'  → sweep di bawah swing low; 'SELL' → sweep di atas swing high (wick
    menembus lalu close kembali ke range). Returns (swept, info{level, wick_ratio, bars_ago}).
    """
    direction = direction.upper().strip()
    if len(df) < 12:
        return False, {}

    closed = df.iloc[:-1]   # hanya bar tertutup (bar terakhir = live)
    n      = len(closed)
    if n < 12:
        return False, {}

    lows   = closed["low"].to_numpy(dtype=float)
    highs  = closed["high"].to_numpy(dtype=float)
    closes = closed["close"].to_numpy(dtype=float)
    recent_start = max(0, n - _RECENT_BARS)

    if direction == "BUY":
        pivots = swing_low_idx_prices(closed, left=_PIVOT_WINDOW, right=_PIVOT_WINDOW)
        for p_idx, p_low in reversed(pivots):
            if n - 1 - p_idx > lookback:
                continue
            for b in range(max(p_idx + 1, recent_start), n):
                rng = highs[b] - lows[b]
                if rng <= 0:
                    continue
                if lows[b] < p_low and closes[b] > p_low:
                    ratio = (p_low - lows[b]) / rng
                    if ratio >= min_wick_ratio:
                        return True, {
                            "level":      float(p_low),
                            "wick_ratio": round(float(ratio), 2),
                            "bars_ago":   n - 1 - b,
                        }
    elif direction == "SELL":
        pivots = swing_high_idx_prices(closed, left=_PIVOT_WINDOW, right=_PIVOT_WINDOW)
        for p_idx, p_high in reversed(pivots):
            if n - 1 - p_idx > lookback:
                continue
            for b in range(max(p_idx + 1, recent_start), n):
                rng = highs[b] - lows[b]
                if rng <= 0:
                    continue
                if highs[b] > p_high and closes[b] < p_high:
                    ratio = (highs[b] - p_high) / rng
                    if ratio >= min_wick_ratio:
                        return True, {
                            "level":      float(p_high),
                            "wick_ratio": round(float(ratio), 2),
                            "bars_ago":   n - 1 - b,
                        }
    return False, {}


def liquidity_sweep_score(
    direction:   str,
    entry:       float,
    df:          pd.DataFrame,
    atr:         float,
    tf:          str  = "",
    is_scalping: bool = True,
    data_by_tf:  dict[str, pd.DataFrame] | None = None,
) -> tuple[int, str]:
    """Skor konfluensi liquidity sweep untuk scalping: 0 atau 1.

    entry/atr/tf/data_by_tf hanya untuk konsistensi tanda tangan (SNR/SND/Fib)
    — deteksi murni struktur candle di TF sinyal, tidak butuh MTF.
    """
    if not is_scalping or atr <= 0:
        return 0, "SWEEP_SKIP"
    swept, info = detect_liquidity_sweep(df, direction)
    if not swept:
        return 0, "SWEEP_NONE"
    return 1, (f"SWEEP_OK(level={info['level']:.2f} "
               f"wick={info['wick_ratio'] * 100:.0f}% bars={info['bars_ago']})")