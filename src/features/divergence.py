"""divergence.py — Deteksi RSI dan MACD Histogram divergence."""
import numpy as np

from src.features.swing_utils import swing_highs_idx, swing_lows_idx

_LOOKBACK_MAP: dict[str, int] = {
    "M1": 150, "M5": 120, "M15": 100, "M30": 80,
    "H1": 80,  "H4": 60,  "D1":  40,
}
_LOOKBACK_DEFAULT = 100

_LEFT_RIGHT_MAP: dict[str, tuple[int, int]] = {
    "M1": (3, 3), "M5": (3, 3), "M15": (4, 4), "M30": (4, 4),
    "H1": (5, 5), "H4": (5, 5), "D1":  (5, 5),
}
_LEFT_RIGHT_DEFAULT = (4, 4)


def lookback_for_tf(tf: str) -> int:
    return _LOOKBACK_MAP.get(tf.upper(), _LOOKBACK_DEFAULT)


def left_right_for_tf(tf: str) -> tuple[int, int]:
    return _LEFT_RIGHT_MAP.get(tf.upper(), _LEFT_RIGHT_DEFAULT)


def _detect_divergence(
    close:     np.ndarray,
    indicator: np.ndarray,
    lookback:  int = 100,
    left:      int = 4,
    right:     int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    n    = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    if n < lookback + left + right + 5:
        return bull, bear

    for i in range(lookback + left + right, n - right):
        wc = close[i - lookback: i + 1]
        wi = indicator[i - lookback: i + 1]
        if np.any(np.isnan(wi)):
            continue

        # Bullish: price lower low + indicator higher low
        pl = swing_lows_idx(wc, left, right)
        il = swing_lows_idx(wi, left, right)
        if len(pl) >= 2 and len(il) >= 2:
            p1, p2 = pl[-2], pl[-1]
            r1, r2 = il[-2], il[-1]
            if wc[p2] < wc[p1] and wi[r2] > wi[r1] and p2 >= len(wc) - right - 5:
                bull[i] = True

        # Bearish: price higher high + indicator lower high
        ph = swing_highs_idx(wc, left, right)
        ih = swing_highs_idx(wi, left, right)
        if len(ph) >= 2 and len(ih) >= 2:
            p1, p2 = ph[-2], ph[-1]
            r1, r2 = ih[-2], ih[-1]
            if wc[p2] > wc[p1] and wi[r2] < wi[r1] and p2 >= len(wc) - right - 5:
                bear[i] = True

    return bull, bear


def detect_rsi_divergence(
    close:    np.ndarray,
    rsi:      np.ndarray,
    lookback: int = 0,
    left:     int = 0,
    right:    int = 0,
    tf:       str = "",
) -> tuple[np.ndarray, np.ndarray]:
    lb = lookback if lookback > 0 else (lookback_for_tf(tf) if tf else _LOOKBACK_DEFAULT)
    lr = (left, right) if left > 0 and right > 0 else (left_right_for_tf(tf) if tf else _LEFT_RIGHT_DEFAULT)
    return _detect_divergence(close, rsi, lb, lr[0], lr[1])


def detect_macd_divergence(
    close:    np.ndarray,
    macdhist: np.ndarray,
    lookback: int = 0,
    left:     int = 0,
    right:    int = 0,
    tf:       str = "",
) -> tuple[np.ndarray, np.ndarray]:
    lb = lookback if lookback > 0 else (lookback_for_tf(tf) if tf else _LOOKBACK_DEFAULT)
    lr = (left, right) if left > 0 and right > 0 else (left_right_for_tf(tf) if tf else _LEFT_RIGHT_DEFAULT)
    return _detect_divergence(close, macdhist, lb, lr[0], lr[1])
