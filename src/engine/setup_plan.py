"""setup_plan.py — Scan setup plan antisipasi entry di zona Fibonacci/EMA."""

from datetime import datetime

import pandas as pd
import pytz

from src.engine.bias import bias_from_tf, vote_bias
from src.engine.confluence import confluence_score
from src.engine.helpers import (
    atr_proxy, calc_rr, detect_market_condition, latest_closed, safe,
)
from src.features.fibonacci import fib_levels, fib_lookback_for_tf, last_swing
from src.features.session import is_active_session, session_name
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp
from src.strategy.multi_timeframe import higher_timeframes


def _find_fib_anchor(
    df_src:    pd.DataFrame,
    tf_src:    str,
    direction: str,
    p_now:     float,
    atr_val:   float,
) -> tuple[float | None, str]:
    """Cari Fibonacci level kuat (38.2/50/61.8) dalam radius 2×ATR dari harga."""
    sw = last_swing(df_src, lookback=fib_lookback_for_tf(tf_src), direction=direction)
    if sw is None:
        return None, ""
    lvs = fib_levels(sw[0], sw[1], sw[2])
    cands: list[tuple[float, str, float]] = []
    for nm, px in lvs.items():
        dist = abs(px - p_now)
        if dist <= 2.0 * atr_val:
            try:
                lv = float(nm.replace("fib_", ""))
            except ValueError:
                lv = 99.0
            if lv in {0.382, 0.5, 0.618}:
                cands.append((dist, nm, px))
    if cands:
        cands.sort()
        return cands[0][2], cands[0][1]
    return None, ""


def _resolve_entry_zone(
    direction:  str,
    price_now:  float,
    atr:        float,
    fib_anchor: float | None,
    fib_name:   str,
    fib_tf:     str,
    ema20:      float | None,
    ema50:      float | None,
) -> tuple[float, float, float, str] | None:
    """
    Tentukan zona entry pullback berdasarkan anchor teknikal.
    Tier 1: Fibonacci → Tier 1.5: EMA20 → Tier 2: EMA50 → None = skip.
    Returns (pb_low, pb_high, pullback_price, zona_basis) atau None.
    """
    if fib_anchor is not None:
        pb_low  = fib_anchor - 0.5 * atr
        pb_high = fib_anchor + 0.5 * atr
        return pb_low, pb_high, fib_anchor, f"Fibonacci {fib_name}@{fib_anchor:.2f} [{fib_tf}]"

    if ema20 is not None and abs(ema20 - price_now) <= 1.5 * atr:
        if direction == "BUY":
            pb_low, pb_high = ema20 - 0.3 * atr, ema20 + 0.4 * atr
        else:
            pb_low, pb_high = ema20 - 0.4 * atr, ema20 + 0.3 * atr
        return pb_low, pb_high, ema20, f"EMA20@{ema20:.2f}"

    if ema50 is not None and abs(ema50 - price_now) <= 2.0 * atr:
        if direction == "BUY":
            pb_low, pb_high = ema50 - 0.3 * atr, ema50 + 0.5 * atr
        else:
            pb_low, pb_high = ema50 - 0.5 * atr, ema50 + 0.3 * atr
        return pb_low, pb_high, ema50, f"EMA50@{ema50:.2f}"

    return None


def scan_setup_plan(
    data_by_tf:        dict[str, pd.DataFrame],
    symbol:            str,
    enabled_tfs:       list[str],
    min_confirm_votes: int   = 1,
    atr_min_pct:       float = 0.0006,
    sl_atr_mult:       float = 1.5,
    tp1_rr:            float = 1.5,
    tp2_rr:            float = 2.5,
    tp3_rr:            float = 4.0,
    max_sl_points:     float = 50.0,
    sl_pips:           float = 50.0,
    tp1_pips:          float = 70.0,
    tp2_pips:          float = 100.0,
    tp3_pips:          float = 140.0,
    pip_size:          float = 0.1,
    session_filter:    bool  = True,
) -> list[Signal]:
    """
    Scan setup plan dari pasangan M15+H1 dan H1+H4.
    Returns list[Signal] dengan is_setup_plan=True.
    """
    enabled_tfs = [tf.upper() for tf in enabled_tfs]
    results: list[Signal] = []
    now_utc = datetime.now(pytz.utc)

    scan_pairs = []
    if "M15" in enabled_tfs and "H1" in enabled_tfs:
        scan_pairs.append(("M15", "M5",  "scalping",  "H1"))
    if "H1"  in enabled_tfs and "H4" in enabled_tfs:
        scan_pairs.append(("H1",  "M15", "intraday",  "H4"))

    for anchor_tf, exec_tf, trade_mode, required_htf in scan_pairs:
        df_anchor = data_by_tf.get(anchor_tf)
        df_htf    = data_by_tf.get(required_htf)

        if df_anchor is None or df_htf is None or len(df_anchor) < 220:
            continue
        if session_filter and not is_active_session(now_utc, anchor_tf):
            continue

        htf_bias = bias_from_tf(df_htf)
        if htf_bias is None and trade_mode == "scalping" and "H4" in enabled_tfs:
            df_h4 = data_by_tf.get("H4")
            if df_h4 is not None:
                htf_bias = bias_from_tf(df_h4)
                if htf_bias is not None:
                    required_htf = "H4(fallback)"
        if htf_bias is None:
            continue

        anchor_bias = bias_from_tf(df_anchor)
        if anchor_bias is not None and anchor_bias != htf_bias:
            continue

        direction = "BUY" if htf_bias == "BULL" else "SELL"
        last      = latest_closed(df_anchor)
        price_now = float(last["close"])
        atr       = atr_proxy(df_anchor)
        sess      = session_name(now_utc)
        close_time = str(pd.to_datetime(last["time"]).to_pydatetime().isoformat())

        if atr <= 0 or atr < price_now * atr_min_pct:
            continue
        if detect_market_condition(df_anchor) == "news_spike":
            continue

        # Cari Fibonacci anchor (Tier 1a → 1b → 1c)
        fib_anchor, fib_name = _find_fib_anchor(df_anchor, anchor_tf, direction, price_now, atr)
        fib_tf = anchor_tf

        if fib_anchor is None and trade_mode == "scalping" and "H1" in enabled_tfs:
            df_h1 = data_by_tf.get("H1")
            if df_h1 is not None:
                fib_anchor, fib_name = _find_fib_anchor(df_h1, "H1", direction, price_now, atr)
                if fib_anchor is not None:
                    fib_tf = "H1"

        if fib_anchor is None and "H4" in enabled_tfs:
            df_h4 = data_by_tf.get("H4")
            if df_h4 is not None:
                atr_h4 = atr_proxy(df_h4)
                fib_anchor, fib_name = _find_fib_anchor(df_h4, "H4", direction, price_now, atr_h4)
                if fib_anchor is not None:
                    fib_tf = "H4"

        if trade_mode == "intraday" and fib_anchor is None:
            continue

        # RSI filter — pastikan ada ruang gerak
        rsi_now = safe(last, "rsi_14")
        if rsi_now is not None:
            if direction == "SELL" and rsi_now < 30: continue
            if direction == "BUY"  and rsi_now > 70: continue

        ema20 = safe(last, "ema_20")
        ema50 = safe(last, "ema_50")
        zone  = _resolve_entry_zone(direction, price_now, atr, fib_anchor, fib_name, fib_tf, ema20, ema50)
        if zone is None:
            continue

        pb_low, pb_high, _, zona_basis = zone

        # Koreksi jika zona sudah terlewat harga
        if direction == "BUY" and pb_high >= price_now:
            pb_high = price_now - 0.1 * atr
            pb_low  = pb_high - 0.5 * atr
        elif direction == "SELL" and pb_low <= price_now:
            pb_low  = price_now + 0.1 * atr
            pb_high = pb_low  + 0.5 * atr

        # Validasi jarak zona dari fib anchor
        if fib_anchor is not None and abs((pb_low + pb_high) / 2 - fib_anchor) > 2.0 * atr:
            continue

        final_low  = round(pb_low,  2)
        final_high = round(pb_high, 2)
        sl_ref     = final_low if direction == "BUY" else final_high

        plan = dynamic_atr_sltp(direction=direction, price_now=sl_ref, atr=atr,
                                 sl_atr_mult=sl_atr_mult, tp1_rr=tp1_rr,
                                 tp2_rr=tp2_rr, tp3_rr=tp3_rr, max_sl_points=max_sl_points)
        if plan is None:
            plan = fixed_zone_sltp(direction=direction, price_now=sl_ref,
                                   entry_zone_pips=30, sl_pips=sl_pips,
                                   tp1_pips=tp1_pips, tp2_pips=tp2_pips,
                                   tp3_pips=tp3_pips, pip_size=pip_size)
        if plan is None:
            continue

        plan.entry_low  = final_low
        plan.entry_high = final_high
        entry_rr = plan.entry_high if direction == "BUY" else plan.entry_low
        rr = calc_rr(direction, entry_rr, plan.sl, plan.tp1)
        if rr is None or rr < 1.5 - 1e-9:
            continue

        confirm_tfs    = higher_timeframes(anchor_tf, enabled_tfs)
        _, bias_detail = vote_bias(data_by_tf, confirm_tfs, anchor_tf, min_confirm_votes)

        conf_sc, conf_notes, conf_detail = confluence_score(
            df=df_anchor, direction=direction, entry=price_now, atr=atr,
            tf=anchor_tf, is_scalping=(trade_mode == "scalping"),
            sl=float(plan.sl), tp1_rr=tp1_rr,
        )
        if "SNR_BLOCKED" in conf_detail.get("snr_detail", ""):
            continue

        results.append(Signal(
            symbol=symbol, tf=anchor_tf, direction=direction, close_time=close_time,
            entry=float(entry_rr), entry_low=float(plan.entry_low),
            entry_high=float(plan.entry_high), sl=float(plan.sl),
            tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
            rr=float(rr), sl_method="dynamic_atr", atr_value=float(atr),
            tp1_rr=float(tp1_rr), tp2_rr=float(tp2_rr), tp3_rr=float(tp3_rr),
            trigger_score=0, trigger_max=6, confluence_score=conf_sc,
            htf_bias=bias_detail,
            trigger_notes=f"SETUP_PLAN via {required_htf}:{htf_bias} | {zona_basis}",
            confluence_notes=conf_notes,
            pattern_names=conf_detail["pattern_names"],
            fib_detail=conf_detail["fib_detail"],
            snr_detail=conf_detail["snr_detail"],
            snd_detail=conf_detail["snd_detail"],
            divergence_detail=conf_detail["div_detail"],
            session_name=sess,
            signal_mode="trend", trade_mode=trade_mode,
            exec_tf=exec_tf, is_setup_plan=True,
            reason=f"SETUP_PLAN {anchor_tf} {direction} | HTF:{required_htf}:{htf_bias}",
        ))

    return results
