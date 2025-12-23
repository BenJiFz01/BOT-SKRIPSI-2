from __future__ import annotations

import pandas as pd

from src.models.signal import Signal
from src.features.fibonacci import last_swing, fib_levels, nearest_fib
from src.features.zones_snr import swing_points, nearest_level
from src.features.zones_snd import detect_base_zone
from src.risk.rr import calc_rr
from src.risk.sl_tp import fixed_zone_sltp
from src.strategy.timeframe_hierarchy import higher_timeframes

_LAST_SIGNAL_TIME: dict[tuple[str, str], pd.Timestamp] = {}

def _atr_proxy(df: pd.DataFrame, n: int = 14) -> float:
    """
    ATR proxy sederhana = rata-rata range (high-low) n candle terakhir.
    Dipakai untuk sizing buffer/threshold.
    """
    if len(df) < 3:
        return 0.0
    w = df.iloc[-n:] if len(df) > n else df
    v = (w["high"].astype(float) - w["low"].astype(float)).mean()
    return float(v) if pd.notna(v) and v > 0 else 0.0

def _latest_closed(df: pd.DataFrame) -> pd.Series:
    # asumsi bar terakhir adalah candle berjalan (belum close)
    return df.iloc[-2]


def _bias_from_tf(df: pd.DataFrame) -> str | None:
    if len(df) < 220:
        return None

    last = _latest_closed(df)
    need = ["ema_50", "ema_200"]
    if any(pd.isna(last.get(c)) for c in need):
        return None

    close = float(last["close"])
    ema50 = float(last["ema_50"])
    ema200 = float(last["ema_200"])

    if close > ema200 and ema50 > ema200:
        return "BULL"
    if close < ema200 and ema50 < ema200:
        return "BEAR"
    return None


def _trigger_rule(df: pd.DataFrame, direction: str) -> bool:
    """
    Trigger 2 tahap (setup pullback + entry momentum) untuk mengurangi false signal.

    BUY:
      - Trend: close > EMA200
      - Setup: harga dekat EMA50 (pullback sehat)
      - Filter: RSI tidak overbought ( < 70 )
      - Entry: RSI naik dan MACD hist naik, candle hijau

    SELL:
      - Trend: close < EMA200
      - Setup: harga dekat EMA50
      - Filter: RSI tidak oversold ekstrem ( > 30 )
      - Entry: RSI turun dan MACD hist turun, candle merah
    """
    if len(df) < 220:
        return False

    last = df.iloc[-2]
    prev = df.iloc[-3]

    need_last = ["close", "open", "ema_50", "ema_200", "rsi_14", "macdhist", "high", "low"]
    need_prev = ["rsi_14", "macdhist"]
    if any(pd.isna(last.get(c)) for c in need_last) or any(pd.isna(prev.get(c)) for c in need_prev):
        return False

    close = float(last["close"])
    open_ = float(last["open"])
    ema50 = float(last["ema_50"])
    ema200 = float(last["ema_200"])
    rsi_last = float(last["rsi_14"])
    rsi_prev = float(prev["rsi_14"])
    macd_last = float(last["macdhist"])
    macd_prev = float(prev["macdhist"])

    atrp = _atr_proxy(df, n=14)
    if atrp <= 0:
        return False

    # setup: "dekat" EMA50 (pullback)
    near_ema50 = abs(close - ema50) <= (0.8 * atrp)

    if direction == "BUY":
        if close <= ema200:
            return False
        if not near_ema50:
            return False
        if rsi_last >= 70:
            return False
        if not (rsi_last > rsi_prev and macd_last > macd_prev):
            return False
        if close <= open_:  # candle hijau
            return False
        return True

    else:  # SELL
        if close >= ema200:
            return False
        if not near_ema50:
            return False
        if rsi_last <= 30:
            return False
        if not (rsi_last < rsi_prev and macd_last < macd_prev):
            return False
        if close >= open_:  # candle merah
            return False
        return True


def _vote_bias(
    data_by_tf: dict[str, pd.DataFrame], confirm_tfs: list[str]
) -> tuple[str | None, list[str]]:
    votes = {"BULL": 0, "BEAR": 0}
    details: list[str] = []

    for tf in confirm_tfs:
        df = data_by_tf.get(tf)
        if df is None:
            details.append(f"{tf}:MISSING")
            continue

        b = _bias_from_tf(df)
        if b is None:
            details.append(f"{tf}:NEUTRAL")
            continue

        votes[b] += 1
        details.append(f"{tf}:{b}")

    if votes["BULL"] == votes["BEAR"]:
        return None, details

    return ("BULL" if votes["BULL"] > votes["BEAR"] else "BEAR"), details


def evaluate_any_tf_mta(
    data_by_tf: dict[str, pd.DataFrame],
    symbol: str,
    trigger_tf: str,
    enabled_tfs: list[str],
    min_rr: float = 1.0,
    min_confirm_votes: int = 1,
) -> Signal | None:
    trigger_tf = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    def _set_reject(df: pd.DataFrame, reason: str) -> None:
        df.attrs["reject_reason"] = reason

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _set_reject(df_t, "INIT")

    if len(df_t) < 220:
        _set_reject(df_t, f"NOT_ENOUGH_BARS len={len(df_t)} need>=220")
        return None

    last = _latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"])
    close_time = str(close_time_ts.to_pydatetime().isoformat())
    price_now = float(last["close"])

    # ===== FILTER 3a: ATR minimum (hindari market sepi/flat) =====
    atrp = _atr_proxy(df_t, n=14)
    if atrp <= 0:
        _set_reject(df_t, "ATR_INVALID")
        return None

    # threshold ATR minimum relatif terhadap harga (tuning ringan)
    # 0.0006 = 0.06% dari harga. Untuk XAUUSD biasanya masuk akal sebagai filter "too flat".
    if atrp < (price_now * 0.0006):
        _set_reject(df_t, f"ATR_TOO_LOW atrp={atrp:.4f} thr={(price_now*0.0006):.4f}")
        return None

    # ===== FILTER 3b: Cooldown (hindari spam/whipsaw) =====
    # contoh: setelah sinyal, tunggu 2 candle pada TF trigger
    cooldown_bars = 2
    key = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        # hitung selisih bar secara kasar dari time delta / durasi TF
        # Kita pakai mapping sederhana timeframe -> menit
        tf_minutes_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        tf_min = tf_minutes_map.get(trigger_tf, 5)
        bars_since = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars_since < cooldown_bars:
            _set_reject(df_t, f"COOLDOWN active bars_since={bars_since:.2f} need>={cooldown_bars}")
            return None

    # 1) Konfirmasi HTF (opsional)
    confirm_tfs = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_details = _vote_bias(data_by_tf, confirm_tfs)

    if confirm_tfs:
        bull_votes = sum(1 for d in bias_details if d.endswith(":BULL"))
        bear_votes = sum(1 for d in bias_details if d.endswith(":BEAR"))
        if max(bull_votes, bear_votes) < int(min_confirm_votes):
            bias = None  # tanpa bias, bukan reject

    # 2) Tentukan arah dari bias (kalau ada)
    direction: str | None = None
    if bias == "BULL":
        direction = "BUY"
    elif bias == "BEAR":
        direction = "SELL"

    # kalau bias ada → harus trigger sesuai arah bias (anti false lawan trend)
    if direction is not None:
        if not _trigger_rule(df_t, direction):
            _set_reject(df_t, f"TRIGGER_FAIL_WITH_BIAS dir={direction} bias={bias} confirm={bias_details}")
            return None
    else:
        # kalau tidak ada bias → boleh cek dua arah (lebih sering, tapi tetap disiplin)
        buy_ok = _trigger_rule(df_t, "BUY")
        sell_ok = _trigger_rule(df_t, "SELL")
        if buy_ok:
            direction = "BUY"
        elif sell_ok:
            direction = "SELL"
        else:
            _set_reject(df_t, f"TRIGGER_FAIL buy={buy_ok} sell={sell_ok} bias=None confirm={bias_details}")
            return None

    pip_size = 0.1

    plan = fixed_zone_sltp(
        direction=direction,
        price_now=price_now,
        entry_zone_pips=30,
        sl_pips=50,
        tp1_pips=70,
        tp2_pips=100,
        tp3_pips=140,
        pip_size=pip_size,
    )
    if plan is None:
        _set_reject(df_t, "SLTP_PLAN_NONE")
        return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
    if rr is None:
        _set_reject(df_t, "RR_NONE")
        return None
    if rr < float(min_rr):
        _set_reject(df_t, f"RR_TOO_LOW rr={rr:.2f} min_rr={float(min_rr):.2f}")
        return None

    # konfluensi info (tetap seperti punyamu)
    fib_info = ""
    sw = last_swing(df_t, lookback=80)
    if sw:
        sw_low, sw_high, swing_dir = sw
        levels = fib_levels(sw_low, sw_high, swing_dir)
        near = nearest_fib(entry_for_rr, levels)
        if near:
            nm, px = near
            fib_info = f" | FIB near {nm}={px:.2f} ({swing_dir})"

    recent = df_t.iloc[-250:] if len(df_t) > 250 else df_t
    highs, lows = swing_points(recent, left=3, right=3)
    nearest_r = nearest_level(entry_for_rr, highs)
    nearest_s = nearest_level(entry_for_rr, lows)

    snr_info = ""
    parts = []
    if nearest_s is not None:
        parts.append(f"S~{nearest_s:.2f}")
    if nearest_r is not None:
        parts.append(f"R~{nearest_r:.2f}")
    if parts:
        snr_info = " | " + " ".join(parts)

    recent2 = df_t.iloc[-60:] if len(df_t) > 60 else df_t
    zone = detect_base_zone(recent2, window=8, max_range_ratio=0.003)
    snd_info = ""
    if zone:
        zl, zh = zone
        snd_info = f" | BaseZone {zl:.2f}-{zh:.2f}"

    bias_txt = " | ".join(bias_details) if bias_details else "NO_HTF_CONFIRM"
    reason = (
        f"AnyTF-MTA | Trigger={trigger_tf} | Direction={direction}"
        f" | Confirm={bias_txt}"
        f"{fib_info}{snr_info}{snd_info}"
        f" | {plan.method}"
        f" | PriceNow={price_now:.2f}"
        f" | EntryZone={plan.entry_low:.2f}-{plan.entry_high:.2f}"
        f" | SL={plan.sl:.2f} | TP1={plan.tp1:.2f} TP2={plan.tp2:.2f} TP3={plan.tp3:.2f}"
        f" | RR(TP1)={rr:.2f}"
    )

    # sukses: set cooldown timestamp
    _LAST_SIGNAL_TIME[key] = close_time_ts
    _set_reject(df_t, "OK")

    return Signal(
        symbol=symbol,
        tf=trigger_tf,
        direction=direction,
        close_time=close_time,
        entry=float(entry_for_rr),
        sl=float(plan.sl),
        tp=float(plan.tp1),
        rr=float(rr),
        reason=reason,
    )
