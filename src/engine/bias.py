"""bias.py — Deteksi HTF bias (BULL/BEAR) dan voting multi-timeframe."""

import pandas as pd

from src.engine.helpers import atr_proxy, latest_closed, safe


def bias_from_tf(df: pd.DataFrame) -> str | None:
    """
    Baca bias BULL/BEAR dari satu TF berdasarkan EMA50/200.

    Tiga jalur deteksi (urutan prioritas):
      1. EMA200 Breakout Momentum — body candle >= 0.8×ATR, 2 candle konfirmasi.
      2. Normal bias — posisi EMA50/200 + slope >= 40% + gap minimum.
      3. Fallback ATR — harga jauh (>1×ATR) dari EMA200.
    """
    if len(df) < 220:
        return None

    last   = latest_closed(df)
    close  = safe(last, "close")
    ema50  = safe(last, "ema_50")
    ema200 = safe(last, "ema_200")

    if any(v is None for v in [close, ema50, ema200]):
        return None

    atr = atr_proxy(df)

    # Jalur 1: EMA200 Breakout Momentum
    if atr > 0 and len(df) >= 4:
        prev2, prev3 = df.iloc[-3], df.iloc[-4]
        cp  = safe(prev2, "close"); ep  = safe(prev2, "ema_200")
        cp3 = safe(prev3, "close"); ep3 = safe(prev3, "ema_200")
        op  = safe(last, "open")

        if all(v is not None for v in [cp, ep, cp3, ep3, op]):
            momentum = abs(float(close) - float(op)) >= 0.8 * atr  # type: ignore[arg-type]
            if float(cp3) < float(ep3) and float(cp) < float(ep) and float(close) > float(ema200) and momentum:  # type: ignore[arg-type]
                return "BULL"
            if float(cp3) > float(ep3) and float(cp) > float(ep) and float(close) < float(ema200) and momentum:  # type: ignore[arg-type]
                return "BEAR"

    # Jalur 2: Normal Bias (posisi + slope + gap)
    is_bull = close > ema200 and ema50 > ema200  # type: ignore[operator]
    is_bear = close < ema200 and ema50 < ema200  # type: ignore[operator]
    if not (is_bull or is_bear):
        return None

    gap_pct = abs(ema50 - ema200) / close  # type: ignore[operator]
    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()

    slope_ok = True
    if len(ema50_recent) >= 3:
        diffs   = ema50_recent.diff().dropna()
        n_total = len(diffs)
        slope_ok = (
            (is_bull and (diffs > 0).sum() / n_total >= 0.4)
            or (is_bear and (diffs < 0).sum() / n_total >= 0.4)
        )

    if gap_pct >= 0.0005 and slope_ok:
        return "BULL" if is_bull else "BEAR"

    # Jalur 3: Fallback ATR
    if atr > 0:
        if is_bull and close > ema200 + atr:  # type: ignore[operator]
            return "BULL"
        if is_bear and close < ema200 - atr:  # type: ignore[operator]
            return "BEAR"

    return None


def vote_bias(
    data_by_tf:        dict[str, pd.DataFrame],
    confirm_tfs:       list[str],
    trigger_tf:        str = "M5",
    min_confirm_votes: int = 1,
) -> tuple[str | None, str]:
    """
    Vote bias dari TF konfirmasi.
    M5/M15 → H1 penentu. H1 → H4. H4/D1 → semua ikut.
    Returns (bias, detail_str).
    """
    trigger_up = trigger_tf.upper()

    _decisive: dict[str, list[str]] = {"M5": ["H1"], "M15": ["H1"], "H1": ["H4"]}
    decisive_tfs = _decisive.get(trigger_up)

    votes: dict[str, int] = {"BULL": 0, "BEAR": 0}
    details: list[str]    = []
    votes_by_tf: dict[str, str] = {}

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING"); continue
        b = bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL"); continue
        details.append(f"{tf}:{b}")
        if decisive_tfs is None or tf in decisive_tfs:
            votes[b] += 1
            votes_by_tf[tf] = b

    if not votes_by_tf or votes["BULL"] == votes["BEAR"]:
        return None, " ".join(details)

    bias = "BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"

    _required: dict[str, str | None] = {
        "M5": "H1", "M15": "H1", "H1": "H4", "H4": None, "D1": None,
    }
    req = _required.get(trigger_up)
    if req and (votes_by_tf.get(req) != bias):
        return None, " ".join(details) + f" [TF_FAIL:{req}_diperlukan]"

    if max(votes["BULL"], votes["BEAR"]) < min_confirm_votes:
        return None, " ".join(details)

    return bias, " ".join(details)
