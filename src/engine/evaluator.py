"""evaluator.py — Gate utama evaluasi sinyal live (5 gate).

Format reject reason yang disimpan ke df.attrs["reject_reason"]:
  Gate 1: NOT_ENOUGH_BARS(N) | ATR_INVALID | ATR_TOO_LOW(val) | NEWS_SPIKE_SKIP
           OUT_OF_SESSION(sess) | COOLDOWN(Nbar/M)
  Gate 2: BIAS_FAIL(detail) | BIAS_FAIL+CT_FAIL(detail)
  Gate 3: TRIGGER_FAIL:dir=BUY:score=N/M:comp=[...]:cond=X
           EMA200_WAJIB:dir=BUY:bias=BULL | RSI_EXTREME:RSI_OVERBOUGHT(val)
           CT_EMA200_FAIL(detail) | CT_NO_FIB(detail) | CT_NO_DIV
  Gate 4: SLTP_NONE
  Gate 5: CONFLUENCE_FAIL:score=N/M:comp=[...]:cond=X | INTRADAY_NO_FIB:[comp]
           RR_FAIL:rr=X/min=Y | CANDLE_CONFIRM_FAIL:dir=BUY
"""

from datetime import datetime

import pandas as pd
import pytz

from src.engine.bias import vote_bias
from src.engine.confluence import confluence_score
from src.engine.helpers import (
    _LAST_SIGNAL_TIME, _save_cooldown, atr_proxy, calc_rr, detect_market_condition,
    detect_trade_mode, latest_closed, reject,
)
from src.engine.trigger import counter_trend_valid, trigger_score
from src.features.session import is_active_session, session_name
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp
from src.strategy.multi_timeframe import higher_timeframes


def evaluate_any_tf_mta(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    trigger_tf:           str,
    enabled_tfs:          list[str],
    min_rr:               float = 1.5,
    min_confirm_votes:    int   = 1,
    min_trigger_score:    int   = 4,
    min_confluence_score: int   = 2,
    cooldown_bars:        int   = 3,
    atr_min_pct:          float = 0.0006,
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    max_sl_points:        float = 50.0,
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    session_filter:       bool  = True,
    counter_trend_enabled:         bool            = True,
    min_counter_confluence:        int             = 3,
    counter_trend_min_rr:          float           = 2.0,
    counter_trend_tfs:             list[str] | None = None,
    scalping_min_trigger_score:    int   = 3,
    scalping_min_confluence_score: int   = 1,
    scalping_sl_atr_mult:          float = 1.2,
    scalping_cooldown_bars:        int   = 5,
    scalping_max_sl_points:        float = 5.0,
    scalping_tp1_rr:               float = 1.5,
    scalping_tp2_rr:               float = 2.0,
    scalping_tp3_rr:               float = 2.5,
) -> Signal | None:
    """
    Evaluasi sinyal trading untuk satu (symbol, trigger_tf).
    5 gate: Validasi → HTF Bias → Trigger → Confluence → SL/TP & RR.
    Setiap gate yang gagal menyimpan reject reason ke df.attrs["reject_reason"]
    dengan format terstruktur yang dapat di-parse oleh _explain_reject() di main.py.
    """
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    reject(df_t, "INIT")

    # ── GATE 1: Validasi awal ────────────────────────────────────────────────
    if len(df_t) < 220:
        reject(df_t, f"NOT_ENOUGH_BARS({len(df_t)})"); return None

    last          = latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"], utc=True)   # selalu UTC-aware
    close_time    = str(close_time_ts.to_pydatetime().isoformat())
    price_now     = float(last["close"])
    atr           = atr_proxy(df_t)

    if atr <= 0:
        reject(df_t, "ATR_INVALID"); return None
    if atr < price_now * atr_min_pct:
        reject(df_t, f"ATR_TOO_LOW({atr:.4f}<{price_now*atr_min_pct:.4f})"); return None

    is_scalping = trigger_tf in {"M5", "M15"}

    if is_scalping:
        base_trig  = scalping_min_trigger_score
        base_conf  = scalping_min_confluence_score
        base_sl    = scalping_sl_atr_mult
        base_cd    = scalping_cooldown_bars
        tp1, tp2, tp3 = scalping_tp1_rr, scalping_tp2_rr, scalping_tp3_rr
        eff_max_sl = scalping_max_sl_points
    else:
        base_trig  = min_trigger_score
        base_conf  = min_confluence_score
        base_sl    = sl_atr_mult
        base_cd    = cooldown_bars
        tp1, tp2, tp3 = tp1_rr, tp2_rr, tp3_rr
        eff_max_sl = max_sl_points

    mkt = detect_market_condition(df_t)
    if mkt == "news_spike":
        reject(df_t, "NEWS_SPIKE_SKIP"); return None
    elif mkt == "volatile":
        eff_trig = max(1, base_trig - 1)
        eff_conf = max(1, base_conf - 1)
        eff_sl   = base_sl * 1.3
    elif mkt == "sideways":
        eff_trig = base_trig + 1
        eff_conf = base_conf + 1
        eff_sl   = base_sl
    else:
        eff_trig = base_trig
        eff_conf = base_conf
        eff_sl   = base_sl

    # Cooldown check
    key        = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        tf_min = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(trigger_tf, 5)
        bars   = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars < base_cd:
            reject(df_t, f"COOLDOWN({bars:.1f}bar/{base_cd}bar)"); return None

    now_utc = datetime.now(pytz.utc)
    sess    = session_name(now_utc)
    if session_filter and not is_active_session(now_utc, trigger_tf):
        reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # ── GATE 2: HTF Bias ─────────────────────────────────────────────────────
    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = vote_bias(data_by_tf, confirm_tfs, trigger_tf, min_confirm_votes)

    # ── GATE 3: Trigger Score ────────────────────────────────────────────────
    direction:  str | None = None
    trig_score: int        = 0
    trig_notes: str        = ""
    is_counter  = False

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"
        ok, sc, nt = trigger_score(df_t, dir_try, eff_trig)
        if ok:
            direction, trig_score, trig_notes = dir_try, sc, nt
        else:
            if nt.startswith("EMA200-"):
                reject(df_t, f"EMA200_WAJIB:dir={dir_try}:bias={bias}:comp=[{nt}]:cond={mkt}")
            elif nt.startswith("RSI_OVERSOLD") or nt.startswith("RSI_OVERBOUGHT"):
                reject(df_t, f"RSI_EXTREME:{nt}:dir={dir_try}:cond={mkt}")
            elif nt == "TOO_FEW_BARS":
                reject(df_t, "NOT_ENOUGH_BARS(trigger<30)")
            else:
                reject(df_t, f"TRIGGER_FAIL:dir={dir_try}:score={sc}/{eff_trig}:comp=[{nt}]:cond={mkt}")
            return None
    else:
        ct_tfs = [t.upper() for t in (counter_trend_tfs or ["M5", "M15", "H1", "H4"])]
        if not counter_trend_enabled or trigger_tf not in ct_tfs:
            reject(df_t, f"BIAS_FAIL({bias_detail})"); return None

        ct_dir, ct_detail, ct_sc = None, "", 0
        for try_dir in ["BUY", "SELL"]:
            ok_ct, det, sc = counter_trend_valid(
                df=df_t, direction=try_dir, entry=price_now, atr=atr,
                min_confluence=min_counter_confluence, is_scalping=is_scalping,
            )
            if ok_ct and sc > ct_sc:
                ct_dir, ct_detail, ct_sc = try_dir, det, sc

        if ct_dir is None:
            reject(df_t, f"BIAS_FAIL+CT_FAIL({bias_detail})"); return None

        direction  = ct_dir
        is_counter = True
        _, trig_score, trig_full = trigger_score(df_t, direction, min_score=1)
        trig_notes = f"{trig_full} [CT:{ct_detail} score={ct_sc}]"
        if "EMA200-" in trig_full:
            reject(df_t, f"CT_EMA200_FAIL:dir={direction}:comp=[{trig_full}]"); return None

    # ── GATE 4: SL/TP ────────────────────────────────────────────────────────
    plan = dynamic_atr_sltp(
        direction=direction, price_now=price_now, atr=atr,
        sl_atr_mult=eff_sl, tp1_rr=tp1, tp2_rr=tp2, tp3_rr=tp3,
        max_sl_points=eff_max_sl,
    )
    sl_method = "dynamic_atr"
    if plan is None:
        plan = fixed_zone_sltp(
            direction=direction, price_now=price_now,
            entry_zone_pips=30, sl_pips=sl_pips,
            tp1_pips=tp1_pips, tp2_pips=tp2_pips,
            tp3_pips=tp3_pips, pip_size=pip_size,
        )
        sl_method = "fixed"
    if plan is None:
        reject(df_t, "SLTP_NONE"); return None

    # ── GATE 5: Confluence + RR ──────────────────────────────────────────────
    conf_sc, conf_notes, conf_detail = confluence_score(
        df=df_t, direction=direction, entry=price_now, atr=atr,
        tf=trigger_tf, is_scalping=is_scalping, sl=float(plan.sl), tp1_rr=tp1_rr,
    )
    if conf_sc < eff_conf:
        reject(df_t, f"CONFLUENCE_FAIL:score={conf_sc}/{eff_conf}:comp=[{conf_notes}]:cond={mkt}")
        return None

    if not is_scalping and not conf_detail.get("fib_detail"):
        reject(df_t, f"INTRADAY_NO_FIB:comp=[{conf_notes}]"); return None

    entry_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr       = calc_rr(direction, entry_rr, plan.sl, plan.tp1)
    min_rr_e = counter_trend_min_rr if is_counter else min_rr
    if rr is None or rr < min_rr_e - 1e-9:
        rr_val = f"{rr:.2f}" if rr is not None else "None"
        reject(df_t, f"RR_FAIL:rr={rr_val}/min={min_rr_e}"); return None

    # Konfirmasi 2 candle terakhir
    if len(df_t) >= 4:
        c1_bull = float(df_t.iloc[-2].get("close", 0)) > float(df_t.iloc[-2].get("open", 0))
        c2_bull = float(df_t.iloc[-3].get("close", 0)) > float(df_t.iloc[-3].get("open", 0))
        if direction == "BUY" and not (c1_bull or c2_bull):
            reject(df_t, "CANDLE_CONFIRM_FAIL:dir=BUY"); return None
        if direction == "SELL" and c1_bull and c2_bull:
            reject(df_t, "CANDLE_CONFIRM_FAIL:dir=SELL"); return None

    _LAST_SIGNAL_TIME[key] = close_time_ts
    _save_cooldown()
    reject(df_t, "OK")

    trade_mode, exec_tf = detect_trade_mode(trigger_tf)
    mkt_tag = f" [pasar={mkt}]" if mkt != "normal" else ""
    trig_label = f"{trig_notes}{mkt_tag}"

    current_price = float(last["close"])
    is_setup_plan = False
    
    if direction == "BUY" and current_price > plan.entry_high:
        is_setup_plan = True  # harga sudah di atas zona → tunggu pullback
    elif direction == "SELL" and current_price < plan.entry_low:
        is_setup_plan = True  # harga sudah di bawah zona → tunggu rally

    return Signal(
        symbol=symbol, tf=trigger_tf, direction=direction, close_time=close_time,
        entry=float(entry_rr), entry_low=float(plan.entry_low),
        entry_high=float(plan.entry_high), sl=float(plan.sl),
        tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
        rr=float(rr), sl_method=sl_method, atr_value=float(atr),
        tp1_rr=float(tp1), tp2_rr=float(tp2), tp3_rr=float(tp3),
        trigger_score=trig_score, trigger_max=6, confluence_score=conf_sc,
        htf_bias=bias_detail, trigger_notes=trig_label,
        confluence_notes=conf_notes,
        pattern_names=conf_detail["pattern_names"],
        fib_detail=conf_detail["fib_detail"],
        snr_detail=conf_detail["snr_detail"],
        snd_detail=conf_detail["snd_detail"],
        divergence_detail=conf_detail["div_detail"],
        session_name=sess,
        signal_mode="counter_trend" if is_counter else "trend",
        trade_mode=trade_mode, exec_tf=exec_tf, is_setup_plan=is_setup_plan,
    )
