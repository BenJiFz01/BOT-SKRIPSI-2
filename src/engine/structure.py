"""Swing-structure detection buat menangkap awal tren di TF kecil.

Tren jarang lahir langsung dari 1-2 candle impuls; biasanya melalui base/consolidation,
retracement, lalu break struktur. Layer ini membaca struktur swing (fractal pivot) supaya
engine tidak buta di fase momentum lemah. Murni klasifikasi berbasis OHLC tertutup.
"""

from __future__ import annotations

import pandas as pd

from src.engine.utils import _latest_closed, _safe


def _swing_pivots(df: pd.DataFrame, window: int = 2) -> list[dict]:
    """Fractal pivot di candle tertutup (iloc 0..-2; bar forming diabaikan)."""
    n = len(df)
    if n < 2 * window + 3:
        return []
    max_i = n - 2
    pivots: list[dict] = []
    for i in range(window, max_i - window + 1):
        hi = float(df["high"].iloc[i])
        lo = float(df["low"].iloc[i])
        is_hi = all(float(df["high"].iloc[k]) < hi for k in range(i - window, i + window + 1) if k != i)
        is_lo = all(float(df["low"].iloc[k]) > lo for k in range(i - window, i + window + 1) if k != i)
        if is_hi:
            pivots.append({"iloc": i, "kind": "H", "val": hi})
        if is_lo:
            pivots.append({"iloc": i, "kind": "L", "val": lo})
    return pivots


def _same_kind_sorted(pivots: list[dict], kind: str, gap: int = 3) -> list[dict]:
    """Pivot sejenis dengan jarak antar-pivot minimal `gap` bar (biar bukan noise)."""
    kept: list[dict] = []
    for p in pivots:
        if p["kind"] != kind:
            continue
        if kept and p["iloc"] - kept[-1]["iloc"] < gap:
            continue
        kept.append(p)
    return kept


def structure_holds(df: pd.DataFrame, direction: str) -> tuple[bool, str]:
    """Urutan swing masih mendukung arah: higher-low utk BUY, lower-high utk SELL.

    Dipakai utk anti-flicker: kalau leg momentum sudah patah tapi struktur belum,
    veto tetap aktif sampai swing yang menopang arah itu benar-benar dipatahkan.
    """
    direction = direction.upper()
    if direction not in ("BUY", "SELL") or len(df) < 20:
        return False, ""
    pivots = _swing_pivots(df)
    last = _latest_closed(df)
    close = _safe(last, "close")
    if close is None:
        return False, ""

    if direction == "BUY":
        lows = _same_kind_sorted(pivots, "L")
        if len(lows) >= 2:
            cur, prev = lows[-1], lows[-2]
            if cur["val"] > prev["val"] and close > cur["val"]:
                return True, f"HL(cur={cur['val']:.2f}>prev={prev['val']:.2f})"
        return False, ""

    highs = _same_kind_sorted(pivots, "H")
    if len(highs) >= 2:
        cur, prev = highs[-1], highs[-2]
        if cur["val"] < prev["val"] and close < cur["val"]:
            return True, f"LH(cur={cur['val']:.2f}<prev={prev['val']:.2f})"
    return False, ""


def structure_break(df: pd.DataFrame, direction: str, atr: float) -> tuple[bool, str]:
    """Break segar satu level swing terakhir searah arah (early-trend, bukan momentum).

    Persyaratan: close melewati swing terakhir + belum overextended (<=1.2×ATR) supaya
    masih ketangkap sebagai awal tren, bukan chase. BUY: break swing high; SELL: break
    swing low.
    """
    direction = direction.upper()
    if direction not in ("BUY", "SELL") or atr <= 0 or len(df) < 20:
        return False, ""
    pivots = _swing_pivots(df)
    last = _latest_closed(df)
    close = _safe(last, "close")
    if close is None:
        return False, ""

    kind = "H" if direction == "BUY" else "L"
    swing = _same_kind_sorted(pivots, kind)
    if not swing:
        return False, ""
    pivot = swing[-1]
    if pivot["iloc"] < len(df) - 42:
        return False, ""  # swing terlalu lama, bukan acuan breakout now

    if direction == "BUY":
        dist = close - pivot["val"]
        ok = close > pivot["val"] and 0 < dist <= 1.2 * atr
        note = f"SWING_BREAK(high={pivot['val']:.2f})"
    else:
        dist = pivot["val"] - close
        ok = close < pivot["val"] and 0 < dist <= 1.2 * atr
        note = f"SWING_BREAK(low={pivot['val']:.2f})"
    return ok, note if ok else ""


def base_breakout(df: pd.DataFrame, direction: str, atr: float) -> tuple[bool, str]:
    """Base/consolidation sempit yang pecah ke satu arah (awal tren saat momentum lemah).

    Rentang tinggi-rendah 10 candle tertutup <=0.8×ATR, lalu candle tertutup terakhir
    menembus rentang >=0.3×ATR searah. Momentum tidak wajib kuat di sini — struktur
    base yang pecah sudah bukti perpindahan.
    """
    direction = direction.upper()
    if direction not in ("BUY", "SELL") or atr <= 0 or len(df) < 15:
        return False, ""
    base = df.iloc[-12:-2]
    hi = float(base["high"].max())
    lo = float(base["low"].min())
    if (hi - lo) > 0.8 * atr:
        return False, ""
    last = _latest_closed(df)
    close = _safe(last, "close")
    if close is None:
        return False, ""

    if direction == "BUY" and close >= hi + 0.3 * atr:
        return True, f"BASE_BREAK(lo={lo:.2f},hi={hi:.2f})"
    if direction == "SELL" and close <= lo - 0.3 * atr:
        return True, f"BASE_BREAK(lo={lo:.2f},hi={hi:.2f})"
    return False, ""


def structure_trend_start(df: pd.DataFrame, direction: str, atr: float) -> tuple[bool, str]:
    """Awal tren dari struktur TF kecil: structure_break ATAU base_breakout."""
    ok, note = structure_break(df, direction, atr)
    if ok:
        return True, note
    ok, note = base_breakout(df, direction, atr)
    if ok:
        return True, note
    return False, ""