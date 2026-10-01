"""â”€ HTF bias voting & trade-mode classification."""

from __future__ import annotations

import pandas as pd

from src.engine.utils import _atr_proxy, _latest_closed, _safe


def _bias_from_tf(df: pd.DataFrame) -> str | None:
    if len(df) < 200:
        return None

    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema20  = _safe(last, "ema_20")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")

    if any(v is None for v in [close, ema50, ema200]):
        return None

    is_bull = close > ema50 and close > ema200
    is_bear = close < ema50 and close < ema200  

    if not (is_bull or is_bear):
        return None

    gap_pct = abs(ema50 - ema200) / close  

    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()

    slope_ok = False
    if len(ema50_recent) >= 3:
        diffs   = ema50_recent.diff().dropna()
        n_total = len(diffs)
        if is_bull and (diffs > 0).sum() / n_total >= 0.5:
            slope_ok = True
        if is_bear and (diffs < 0).sum() / n_total >= 0.5:
            slope_ok = True
    else:
        slope_ok = True

    if gap_pct >= 0.0005 and slope_ok:
        candidate = "BULL" if is_bull else "BEAR"
    elif atr := _atr_proxy(df):
        if is_bull and close > ema200 + atr:
            candidate = "BULL"
        elif is_bear and close < ema200 - atr:
            candidate = "BEAR"
        else:
            candidate = None
    else:
        candidate = None

    return candidate


def _bias_why_neutral(df: pd.DataFrame) -> str:
    """Diagnostik kenapa _bias_from_tf None â€” dipakai log vote bias. Hindari '()' di return (pemangkasan main)."""
    if len(df) < 200:
        return "bars_kurang_200"
    last   = _latest_closed(df)
    close  = _safe(last, "close")
    ema50  = _safe(last, "ema_50")
    ema200 = _safe(last, "ema_200")
    if any(v is None for v in [close, ema50, ema200]):
        return "kolom_MA_tidak_lengkap"
    if abs(ema50 - ema200) <= abs(close) * 1e-6:
        return f"ema50_sama_ema200_kode_lama e50={ema50:.2f}"
    is_bull = close > ema50 and close > ema200
    is_bear = close < ema50 and close < ema200
    if not (is_bull or is_bear):
        return f"harga_antara_MA c={close:.0f} e50={ema50:.0f} e200={ema200:.0f}"
    gap_pct = abs(ema50 - ema200) / close
    if gap_pct < 0.0005:
        return f"gap_MA_kecil {gap_pct*100:.3f}pct"
    idx = df.index.get_loc(last.name) if hasattr(last, "name") and last.name in df.index else -2
    try:
        ema50_recent = df["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_recent = df["ema_50"].iloc[-7:-2].dropna()
    if len(ema50_recent) >= 3:
        diffs = ema50_recent.diff().dropna()
        n     = float(len(diffs))
        slope_too_weak = (is_bull and (diffs > 0).sum() / n < 0.5) or \
                         (is_bear and (diffs < 0).sum() / n < 0.5)
        if slope_too_weak:
            return f"slope_ema50_lemah {diffs.iloc[-1]:+.2f}/bar"
    return "unknown"


def _momentum_recovery_bias(
    df_scalp: pd.DataFrame,
    df_h1:    pd.DataFrame | None,
) -> tuple[str | None, str]:
    """Deteksi momentum recovery scalping saat H1 NEUTRAL â€” sistem skor min 3 dari 4
    (slope â‰¥60%, impulse >1.5Ã—ATR, rsi searah, h1_ok EMA50 H1 tak berlawanan), bukan
    wajib semua. Returns (bias, detail) utk log vote bias."""
    if len(df_scalp) < 30:
        return None, "TOO_FEW_BARS"

    last = _latest_closed(df_scalp)
    prev = df_scalp.iloc[-3] if len(df_scalp) > 3 else last

    close = _safe(last, "close")
    ema20 = _safe(last, "ema_20")
    ema50 = _safe(last, "ema_50")
    rsi   = _safe(last, "rsi_14")
    rsi_p = _safe(prev, "rsi_14")
    atr   = _atr_proxy(df_scalp)

    if any(v is None for v in [close, ema20, ema50, rsi, rsi_p]) or atr <= 0:
        return None, "DATA_INCOMPLETE"

    # Gerbang wajib: arah momentum
    ema20_bull = ema20 > ema50
    ema20_bear = ema20 < ema50
    if not (ema20_bull or ema20_bear):
        return None, "NO_MOMENTUM_DIR"
    is_bull = ema20_bull

    try:
        idx         = df_scalp.index.get_loc(last.name) if hasattr(last, "name") and last.name in df_scalp.index else -2
        ema50_slice = df_scalp["ema_50"].iloc[max(0, idx - 4): idx + 1].dropna()
    except Exception:
        ema50_slice = df_scalp["ema_50"].iloc[-7:-2].dropna()

    slope_ok = False
    if len(ema50_slice) >= 3:
        diffs    = ema50_slice.diff().dropna()
        n        = len(diffs)
        slope_ok = ((diffs > 0).sum() / n >= 0.6) if is_bull else ((diffs < 0).sum() / n >= 0.6)

    low_20  = float(df_scalp["low"].iloc[-22:-2].min())  if len(df_scalp) >= 22 else float(df_scalp["low"].iloc[:-2].min())
    high_20 = float(df_scalp["high"].iloc[-22:-2].max()) if len(df_scalp) >= 22 else float(df_scalp["high"].iloc[:-2].max())
    impulse_ok = (close > low_20 + 1.5 * atr) if is_bull else (close < high_20 - 1.5 * atr)

    rsi_ok = (rsi > 50 and rsi > rsi_p) if is_bull else (rsi < 50 and rsi < rsi_p)

    # H1 tidak boleh aktif berlawanan arah; skor 3/4 â€” satu syarat boleh gagal
    h1_ok = True
    if df_h1 is not None and len(df_h1) >= 10:
        try:
            h1_last   = _latest_closed(df_h1)
            h1_idx    = df_h1.index.get_loc(h1_last.name) if hasattr(h1_last, "name") and h1_last.name in df_h1.index else -2
            h1_ema50s = df_h1["ema_50"].iloc[max(0, h1_idx - 4): h1_idx + 1].dropna()
            if len(h1_ema50s) >= 4:
                h1_diffs = h1_ema50s.diff().dropna()
                h1_n     = len(h1_diffs)
                if is_bull  and (h1_diffs < 0).sum() / h1_n >= 0.8:
                    h1_ok = False
                if not is_bull and (h1_diffs > 0).sum() / h1_n >= 0.8:
                    h1_ok = False
        except Exception:
            pass

    checks = {"slope": slope_ok, "impulse": impulse_ok, "rsi": rsi_ok, "h1_ok": h1_ok}
    score  = sum(checks.values())
    detail = ",".join(f"{k}{'+' if v else '-'}" for k, v in checks.items())

    if score >= 3:
        return ("BULL" if is_bull else "BEAR"), detail
    return None, detail


def _vote_bias(
    data_by_tf:        dict[str, pd.DataFrame],
    confirm_tfs:       list[str],
    trigger_tf:        str = "M5",
    min_confirm_votes: int = 1,
    scalping_h1_only:  bool = True,
    intraday_require_d1: bool = True,
) -> tuple[str | None, str]:
    """Vote bias HTF: required_tf (H1 utk M5/M15, H4(+D1) utk intraday) harus punya bias
    jelas + min_confirm_votes sepakat. Scalping cukup H1 saja (data: H4 menekan WR 60%
    vs 72% saat netral). H1 NEUTRAL â†’ coba momentum recovery. Returns (bias, detail)."""
    trigger_up = trigger_tf.upper()
    is_scalping_tf = trigger_up in ("M5", "M15")

    _required_tf: dict[str, list[str]] = {
        "M5":  ["H1"],
        "M15": ["H1"],
        "H1":  ["H4"],
        "H4":  [],
    }
    if intraday_require_d1:
        _required_tf["H4"] = ["D1"]
        _required_tf["H1"].append("D1")  # intraday: D1 (tren besar) wajib punya bias jelas
    required_tfs = _required_tf.get(trigger_up, [])

    if is_scalping_tf and scalping_h1_only:
        confirm_tfs = [tf for tf in confirm_tfs if tf.upper() == "H1"]

    votes:       dict[str, int] = {"BULL": 0, "BEAR": 0}
    details:     list[str]      = []
    votes_by_tf: dict[str, str] = {}

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING")
            continue
        b = _bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL({_bias_why_neutral(df)})")
            continue
        details.append(f"{tf}:{b}")
        votes[b]       += 1
        votes_by_tf[tf] = b

    for req in required_tfs:
        if votes_by_tf.get(req) is not None:
            continue
        # Momentum Recovery scalping saat H1 NEUTRAL
        if is_scalping_tf and req == "H1":
            df_scalp = data_by_tf.get(trigger_up)
            df_h1    = data_by_tf.get("H1")
            if df_scalp is not None:
                mom_bias, mom_detail = _momentum_recovery_bias(df_scalp, df_h1)
                if mom_bias is not None:
                    details.append(f"[MOM_RECOVERY:{mom_bias}({mom_detail})]")
                    return mom_bias, " ".join(details)
                else:
                    details.append(f"[MOM_RECOVERY_FAIL:{mom_detail}]")
        return None, " ".join(details) + f" [TF_FAIL:{req}=NEUTRAL]"

    # Minimal votes harus terpenuhi
    if max(votes["BULL"], votes["BEAR"]) < min_confirm_votes:        return None, " ".join(details)

    if votes["BULL"] == votes["BEAR"]:
        return None, " ".join(details)

    bias = "BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"
    return bias, " ".join(details)


def _all_tf_bias(data_by_tf: dict[str, pd.DataFrame]) -> str:
    """Bias semua TF (D1â†’M15) untuk tampilan stack sinyal â€” diagnostik, bukan keputusan gate."""
    parts: list[str] = []
    for tf in ["D1", "H4", "H1", "M15"]:
        df = data_by_tf.get(tf)
        if df is None:
            continue
        b = _bias_from_tf(df)
        if b is None:
            parts.append(f"{tf}:NEUTRAL({_bias_why_neutral(df)})")
        else:
            parts.append(f"{tf}:{b}")
    return " ".join(parts)


def _detect_trade_mode(trigger_tf: str) -> tuple[str, str]:
    tf = trigger_tf.upper()
    if tf in ("M5", "M15"):
        return "scalping", "M5"
    if tf == "H1":
        return "intraday", "M15"
    return "intraday", "H1"

