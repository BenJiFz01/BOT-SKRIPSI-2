"""─ Scan setup plan (M15+H1 / H1+H4)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytz

from src.engine.bias import _all_tf_bias, _bias_from_tf, _vote_bias
from src.engine.confluence import _confluence_score
from src.engine.utils import _atr_proxy, _latest_closed, _safe, calc_rr
from src.features.fibonacci import fib_levels, fib_lookback_for_tf, last_swing
from src.features.session import is_active_session, session_name
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp
from src.strategy.multi_timeframe import higher_timeframes


def scan_setup_plan(
    data_by_tf:        dict[str, pd.DataFrame],
    symbol:            str,
    enabled_tfs:       list[str],
    min_confirm_votes: int   = 1,
    atr_min_pct:       float = 0.0006,
    tp1_rr:            float = 1.5,
    tp2_rr:            float = 2.5,
    tp3_rr:            float = 4.0,
    sl_pips:           float = 50.0,
    tp1_pips:          float = 70.0,
    tp2_pips:          float = 100.0,
    tp3_pips:          float = 140.0,
    pip_size:          float = 0.1,
    session_filter:    bool  = True,
    sweep_enabled:     bool  = False,
    fvg_enabled:       bool  = False,
) -> list[Signal]:
    """Scan setup plan dari M15+H1 atau H1+H4. Returns list Signal dengan is_setup_plan=True."""
    enabled_tfs = [tf.upper() for tf in enabled_tfs]
    results: list[Signal] = []

    scan_pairs = []
    if "M15" in enabled_tfs and "H1" in enabled_tfs:
        scan_pairs.append(("M15", "M5",  "scalping", "H1"))
    if "H1"  in enabled_tfs and "H4" in enabled_tfs:
        scan_pairs.append(("H1",  "M15", "intraday", "H4"))

    now_utc = datetime.now(pytz.utc)

    for anchor_tf, exec_tf, trade_mode, required_htf in scan_pairs:
        df_anchor = data_by_tf.get(anchor_tf)
        df_htf    = data_by_tf.get(required_htf)
        if df_anchor is None or df_htf is None or len(df_anchor) < 200:
            continue
        if session_filter and not is_active_session(now_utc, anchor_tf):
            continue

        htf_bias = _bias_from_tf(df_htf)
        if htf_bias is None:
            continue
        anchor_bias = _bias_from_tf(df_anchor)
        if anchor_bias is not None and anchor_bias != htf_bias:
            continue

        direction  = "BUY" if htf_bias == "BULL" else "SELL"
        last       = _latest_closed(df_anchor)
        price_now  = float(last["close"])
        atr        = _atr_proxy(df_anchor)
        sess       = session_name(now_utc)
        close_time = str(pd.to_datetime(last["time"]).to_pydatetime().replace(tzinfo=pytz.utc).isoformat())

        if atr <= 0 or atr < price_now * atr_min_pct:
            continue

        ema50_val = _safe(last, "ema_50")
        fib_anchor:      float | None = None
        fib_anchor_name: str          = ""

        swing = last_swing(df_anchor, lookback=fib_lookback_for_tf(anchor_tf), direction=direction)
        if swing is not None:
            levels     = fib_levels(swing[0], swing[1], swing[2])
            anchor_ref = ema50_val if ema50_val is not None else price_now
            candidates: list[tuple[float, str, float]] = []
            for name, px in levels.items():
                dist = abs(px - anchor_ref)
                if dist <= 1.5 * atr:
                    try:
                        lv = float(name.replace("fib_", ""))
                    except ValueError:
                        lv = 99.0
                    weight = 0.0 if lv in {0.382, 0.5, 0.618} else dist
                    candidates.append((weight, name, px))
            if candidates:
                candidates.sort()
                fib_anchor      = candidates[0][2]
                fib_anchor_name = candidates[0][1]

        if fib_anchor is not None:
            pb_low  = fib_anchor - 0.25 * atr
            pb_high = fib_anchor + 0.25 * atr
            pullback_price = fib_anchor
        elif ema50_val is not None:
            if direction == "BUY":
                pb_low, pb_high = ema50_val - 0.3 * atr, ema50_val + 0.5 * atr
            else:
                pb_low, pb_high = ema50_val - 0.5 * atr, ema50_val + 0.3 * atr
            pullback_price = ema50_val
        else:
            if direction == "BUY":
                pb_low, pb_high = price_now - 1.2 * atr, price_now - 0.5 * atr
            else:
                pb_low, pb_high = price_now + 0.5 * atr, price_now + 1.2 * atr
            pullback_price = (pb_low + pb_high) / 2

        if direction == "BUY" and pb_high >= price_now:
            pb_high, pb_low = price_now - 0.2 * atr, price_now - 0.8 * atr
            pullback_price  = pb_high
        elif direction == "SELL" and pb_low <= price_now:
            pb_low, pb_high = price_now + 0.2 * atr, price_now + 0.8 * atr
            pullback_price  = pb_low

        plan = dynamic_atr_sltp(
            direction=direction, price_now=pullback_price, atr=atr,
            tp1_rr=tp1_rr, tp2_rr=tp2_rr, tp3_rr=tp3_rr,
        )
        if plan is None:
            plan = fixed_zone_sltp(
                direction=direction, price_now=pullback_price,
                entry_zone_pips=30, sl_pips=sl_pips,
                tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
                pip_size=pip_size,
            )
        if plan is None:
            continue

        plan.entry_low  = round(pb_low,  2)
        plan.entry_high = round(pb_high, 2)

        entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
        rr = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
        if rr is None or rr < 1.5:
            continue

        confirm_tfs = higher_timeframes(anchor_tf, enabled_tfs)
        _, bias_detail = _vote_bias(
            data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
            trigger_tf=anchor_tf, min_confirm_votes=min_confirm_votes,
        )
        conf_score, conf_notes, conf_detail = _confluence_score(
            df=df_anchor, direction=direction, entry=price_now, atr=atr,
            tf=anchor_tf, is_scalping=(trade_mode == "scalping"),
            sl=float(plan.sl), tp1_rr=tp1_rr, data_by_tf=data_by_tf,
            now_utc=now_utc,
            sweep_enabled=sweep_enabled, fvg_enabled=fvg_enabled,
        )

        # conf_score -99 = SNR_BLOCKED — untuk Setup clamp ke 0, tidak direject
        # (Setup = sinyal early, belum tentu langsung dieksekusi)
        if conf_score == -99:
            conf_score = 0

        fib_tag = f" | Fib={fib_anchor_name}@{fib_anchor:.2f}" if fib_anchor else " | zona EMA50"
        results.append(Signal(
            symbol=symbol, tf=anchor_tf, direction=direction, close_time=close_time,
            entry=float(entry_for_rr), entry_low=float(plan.entry_low),
            entry_high=float(plan.entry_high), sl=float(plan.sl),
            tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
            rr=float(rr), sl_method="dynamic_atr", atr_value=float(atr),
            tp1_rr=float(tp1_rr), tp2_rr=float(tp2_rr), tp3_rr=float(tp3_rr),
            trigger_score=0, trigger_max=6, confluence_score=conf_score,
            htf_bias=bias_detail, htf_bias_all=_all_tf_bias(data_by_tf),
            trigger_notes=f"SETUP_PLAN via {required_htf}:{htf_bias}{fib_tag}",
            confluence_notes=conf_notes,
            pattern_names=conf_detail["pattern_names"],
            fib_detail=conf_detail["fib_detail"], snr_detail=conf_detail["snr_detail"],
            snd_detail=conf_detail["snd_detail"], divergence_detail=conf_detail["div_detail"],
            sweep_detail=conf_detail["sweep_detail"], fvg_detail=conf_detail["fvg_detail"],
            session_name=sess, signal_type="SETUP", signal_mode="CONTINUATION",
            trade_mode=trade_mode,
            exec_tf=exec_tf, is_setup_plan=True,
            reason=f"SETUP_PLAN {anchor_tf} {direction} | HTF:{required_htf}:{htf_bias}",
        ))

    return results
