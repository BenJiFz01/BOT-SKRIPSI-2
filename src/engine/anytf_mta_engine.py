"""anytf_mta_engine.py — Rule-Based Decision Engine (Multi-Timeframe Analysis).

5 gate: Validasi -> HTF Bias -> Trigger Score -> Confluence Score -> SL/TP & RR.
Orchestrator: implementasi tiap gate dipecah ke submodul (bias/state/trigger/confluence/
setup_plan/cooldown/utils). Simbol publik tetap re-export dari sini.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytz

from src.engine.bias import _all_tf_bias, _detect_trade_mode, _vote_bias
from src.engine.cooldown import (
    _CONFLICT_WINDOW_SEC,
    _LAST_LIVE_EMIT,
    _LAST_SIGNAL_TIME,
    _save_cooldown_state,
    get_consec_loss_count,
    record_loss,
    reset_consec_loss,
)
from src.engine.confluence import _confluence_score, _is_counter_trend_valid
from src.engine.setup_plan import scan_setup_plan
from src.engine.state import _decisive_adx, _ltf_counter_veto, _market_state, detect_market_condition
from src.engine.structure import structure_holds, structure_trend_start
from src.engine.trigger import _has_key_level, _has_quality_key_level, _range_rejection_setup, _scalp_pullback_setup, _trigger_score
from src.engine.utils import _atr_proxy, _latest_closed, _reject, calc_rr
from src.features.entry_setup import classify_entry_setup
from src.features.session import is_active_session, session_name, session_strictness
from src.models.signal import Signal
from src.risk.sl_tp import swing_based_sltp
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
    counter_trend_enabled:         bool             = True,
    min_counter_confluence:        int              = 3,
    counter_trend_min_rr:          float            = 2.0,
    counter_trend_tfs:             list[str] | None = None,
    scalping_min_trigger_score:    int              = 3,
    scalping_min_confluence_score: int              = 2,
    scalping_atr_min_points:       float            = 4.0,
    scalping_sl_atr_mult:          float            = 1.2,
    scalping_cooldown_bars:        int              = 5,
    scalping_cooldown_bars_m5:     int              = 6,
    scalping_cooldown_bars_m15:    int              = 5,
    scalping_tp1_rr:               float            = 1.0,
    scalping_tp2_rr:               float            = 1.6,
    scalping_tp3_rr:               float            = 2.6,
    scalping_tp1_atr_mult:         float            = 0.0,  # >0 → TP1 scalping = ×ATR (off: ladder RR)
    scalping_overextend_atr_mult:   float            = 1.2,  # anti-chase: jarak max entry dari EMA20 (×ATR)
    momentum_ema200_tolerance:      float            = 1.0,  # jalur momentum: band EMA200 (×ATR)
    range_rejection_enabled:        bool             = True, # RANGE lane: rejection di level kunci
    scalping_pullback_enabled:      bool             = False, # mode pullback/rebound scalping (opsional)
    scalping_sweep_enabled:         bool             = False, # liquidity sweep ikut skor scalping (off: logging-only)
    scalping_fvg_enabled:           bool             = False, # FVG ikut skor scalping (off: logging-only)
    scalping_min_rr:               float            = 1.0,
    scalping_counter_trend_min_rr: float            = 1.5,
    market_transition_adx_block:   float            = 15.0,
    market_transition_adx_gray:    float            = 25.0,
    scalping_h1_only:              bool             = True,
    intraday_require_d1:           bool             = True,
    # Tuas keketatan/reaksi (A/B testing tanpa ubah kode).
    ltf_veto_enabled:              bool             = True,  # VETO + FLIP lane menyala
    flip_min_trigger:              int              = 3,     # FLIP wajib trigger >= ini
    flip_require_key_level:        bool             = True,  # FLIP wajib key level
    h1_require_key_level:          bool             = True,  # H1 wajib key level
    scalping_pullback_min_trigger: int              = 2,     # floor trigger jalur PULLBACK
    range_quality_key_level:       bool             = True,  # RANGE/sideways: continuation wajib level berkualitas
    spread:                       float            = 0.30,
) -> Signal | None:
    """Evaluasi sinyal untuk satu (symbol, trigger_tf). Returns Signal jika 5 gate lulus."""
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _reject(df_t, "INIT")

    # Circuit breaker key terpisah per mode (scalping vs intraday)
    today_str   = datetime.now().strftime("%Y-%m-%d")
    _is_scalping_tf = trigger_tf in {"M5", "M15"}
    _cb_key     = f"{symbol}_{'scalping' if _is_scalping_tf else 'intraday'}"
    _cb_mode    = "scalping" if _is_scalping_tf else "intraday"

    # GATE 1
    if len(df_t) < 200:
        _reject(df_t, f"NOT_ENOUGH_BARS({len(df_t)})"); return None

    last          = _latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"])
    close_time    = str(close_time_ts.to_pydatetime().replace(tzinfo=pytz.utc).isoformat())
    price_now     = float(last["close"])
    atr           = _atr_proxy(df_t)

    if atr <= 0:
        _reject(df_t, "ATR_INVALID"); return None
    if atr < price_now * atr_min_pct:
        _reject(df_t, f"ATR_TOO_LOW({atr:.4f})"); return None

    is_scalping = trigger_tf in {"M5", "M15"}

    # ATR absolut scalping: tolak rentang terlalu sempit agar SL/TP punya ruang
    if is_scalping and scalping_atr_min_points > 0 and atr < scalping_atr_min_points:
        _reject(df_t, f"ATR_TOO_LOW_SCALPING(atr={atr:.2f}/min={scalping_atr_min_points:.1f})")
        return None

    if is_scalping:
        base_trig  = scalping_min_trigger_score
        base_conf  = scalping_min_confluence_score
        if trigger_tf == "M5":
            base_cd = scalping_cooldown_bars_m5
        elif trigger_tf == "M15":
            base_cd = scalping_cooldown_bars_m15
        else:
            base_cd = scalping_cooldown_bars
    else:
        base_trig  = min_trigger_score
        base_conf  = min_confluence_score
        base_cd    = cooldown_bars

    market_cond = detect_market_condition(df_t)
    if market_cond == "volatile":
        eff_trig = max(1, base_trig - 1)
        eff_conf = max(1, base_conf - 1)
    elif market_cond == "sideways":
        eff_trig = base_trig + 1
        eff_conf = base_conf + 1
    else:
        eff_trig = base_trig
        eff_conf = base_conf

    _asian_continuation_pending = False
    if is_scalping:
        _asian_continuation_pending = True

    key        = (symbol, trigger_tf)
    last_sig_t = _LAST_SIGNAL_TIME.get(key)
    if last_sig_t is not None:
        tf_min = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(trigger_tf, 5)
        bars_since = (close_time_ts - last_sig_t).total_seconds() / (tf_min * 60)
        if bars_since < base_cd:
            _reject(df_t, f"COOLDOWN({bars_since:.1f}bar)"); return None

    now_utc = close_time_ts.to_pydatetime().replace(tzinfo=pytz.utc) if close_time_ts.tzinfo is None else close_time_ts.to_pydatetime()
    sess    = session_name(now_utc)
    
    # Asian session: +1 trig & +1 conf untuk continuation scalping
    if _asian_continuation_pending and session_strictness(now_utc, tf=trigger_tf) == "RELAXED":
        eff_trig += 1
        eff_conf += 1

    # H1: +1 trig & +1 conf (WR historis 19% tanpa hardening)
    if trigger_tf == "H1":
        eff_trig += 1
        eff_conf += 1

    # Cap agar sideways(+1) dan asian(+1) tak numpuk terlalu tinggi
    eff_trig = min(eff_trig, 5)
    eff_conf = min(eff_conf, 4)

    if session_filter and not is_active_session(now_utc, trigger_tf):
        _reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # GATE 2
    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = _vote_bias(
        data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
        trigger_tf=trigger_tf, min_confirm_votes=min_confirm_votes,
        scalping_h1_only=scalping_h1_only,
        intraday_require_d1=intraday_require_d1,
    )

    # GATE 3 — Trigger Score
    direction:    str | None = None
    trig_score:   int        = 0
    trig_notes:   str        = ""
    _is_counter:  bool       = False
    _flip_active: bool       = False
    _pb_active:   bool       = False
    _mom_active:  bool       = False
    _range_active: bool      = False

    market_state, state_note = _market_state(
        df_t, trigger_tf, data_by_tf,
        market_transition_adx_block, market_transition_adx_gray,
    )

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"

        if market_state == "TRANSITION":
            _reject(df_t, f"MARKET_TRANSITION(state={state_note})")
            return None

        ok, sc, nt = _trigger_score(df_t, dir_try, eff_trig)
        if ok:
            direction, trig_score, trig_notes = dir_try, sc, nt
        elif scalping_pullback_enabled and is_scalping:
            _pb_ok, _pb_note = _scalp_pullback_setup(df_t, dir_try, atr)
            _pb_tok, _pb_tsc, _pb_tnt = _trigger_score(df_t, dir_try, min_score=scalping_pullback_min_trigger)
            if _pb_ok and _pb_tok:
                direction, trig_score, trig_notes = dir_try, _pb_tsc, f"PULLBACK[{_pb_note}]"
                _pb_active = True
            else:
                if _pb_ok:
                    _pb_note = f"{_pb_note}+TRIGWEAK({_pb_tnt})"
                # Jalur MOMENTUM/BREAKOUT: EMA200 dilonggarkan
                if market_state in ("HIGH_MOMENTUM", "TREND_BULL", "TREND_BEAR", "BREAKOUT"):
                    _mok, _msc, _mnt = _trigger_score(
                        df_t, dir_try, eff_trig,
                        ema200_tolerance_mult=momentum_ema200_tolerance,
                    )
                    if _mok:
                        direction, trig_score = dir_try, _msc
                        trig_notes = f"MOMENTUM[{_mnt}]"
                        _mom_active = True
                    else:
                        _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{eff_trig}[{nt}] "
                                      f"+ PULLBACK_FAIL[{_pb_note}] + MOMENTUM_FAIL[{_mnt}] "
                                      f"state={market_state}({state_note})")
                        return None
                else:
                    _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{eff_trig}[{nt}] "
                                  f"+ PULLBACK_FAIL[{_pb_note}] state={market_state}({state_note})")
                    return None
        else:
            _reject(df_t, f"TRIGGER_FAIL dir={dir_try} score={sc}/{eff_trig}[{nt}] "
                          f"cond={market_cond} state={market_state}")
            return None

        _dec_reason, _dec_bonus = _decisive_adx(
            trigger_tf, data_by_tf, market_transition_adx_block,
            market_transition_adx_gray,
        )
        if _dec_reason:
            _reject(df_t, _dec_reason)
            return None
        eff_conf = min(eff_conf + _dec_bonus, 5)
    else:
        _ct_tfs = [t.upper() for t in (counter_trend_tfs or ["H1", "H4"])]
        if counter_trend_enabled and trigger_tf in _ct_tfs:
            ct_direction: str | None = None
            ct_detail:    str        = ""
            ct_score:     int        = 0
            for try_dir in ["BUY", "SELL"]:
                ok_ct, det_ct, sc_ct = _is_counter_trend_valid(
                    df=df_t, direction=try_dir, entry=price_now,
                    atr=atr, tf=trigger_tf,
                    min_counter_confluence=min_counter_confluence,
                    is_scalping=is_scalping, data_by_tf=data_by_tf,
                )
                if ok_ct and sc_ct > ct_score:
                    ct_direction, ct_detail, ct_score = try_dir, det_ct, sc_ct

            if ct_direction is None:
                _reject(df_t, f"BIAS_FAIL+CT_FAIL({bias_detail}) state={market_state}")
                return None
            direction   = ct_direction
            _is_counter = True
            ok_trig, trig_score, trig_full = _trigger_score(df_t, direction, min_score=1)
            trig_notes = f"{trig_full} [CT:{ct_detail} score={ct_score}]"
            if "EMA200-" in trig_full:
                _reject(df_t, f"CT_EMA200_FAIL({trig_full})"); return None
        elif range_rejection_enabled and is_scalping and market_state == "RANGE":
            _r_dir, _r_note, _r_sc = _range_rejection_setup(df_t, atr)
            if _r_dir is None:
                _reject(df_t, f"RANGE_NO_REJECTION[{_r_note}] state={market_state}({state_note})")
                return None
            direction, trig_score = _r_dir, _r_sc
            trig_notes = f"RANGE[{_r_note}]"
            _range_active = True
        else:
            _reject(df_t, f"BIAS_FAIL({bias_detail}) state={market_state}({state_note})")
            return None

    # LTF veto + flip lane: blokir sinyal searah bias saat momentum LTF berlawanan utuh,
    # evaluasi flip ke arah lawan dengan gate ketat (trigger + key level di GATE 5).
    if direction in ("BUY", "SELL") and not (_pb_active or _range_active or _is_counter) and ltf_veto_enabled:
        _opp = "BUY" if direction == "SELL" else "SELL"
        _vetoed, _veto_note = _ltf_counter_veto(df_t, direction, atr)
        if not _vetoed:
            _hold, _hold_note = structure_holds(df_t, _opp)
            if _hold:
                _vetoed = True
                _veto_note = f"STRUCT_HOLD({_hold_note})"
        if _vetoed:
            _fok, _fsc, _fnt = _trigger_score(df_t, _opp, min_score=2)
            _v2, _v2_note = _ltf_counter_veto(df_t, _opp, atr)
            _tstart, _ts_note = structure_trend_start(df_t, _opp, atr)
            if (_fsc >= flip_min_trigger or (_fsc >= 2 and _tstart)) and not _v2:
                direction, trig_score, trig_notes = _opp, _fsc, f"FLIP[{_fnt}] {_veto_note}"
                if _ts_note:
                    trig_notes += f" STR[{_ts_note}]"
                _flip_active = True
            else:
                _reject(df_t, f"{_veto_note} flip_fail[trig={_fsc} str={_ts_note or '-'} {_v2_note}]")
                return None

    # Anti-chase: tolak bila harga sudah menyimpang dari setup candle (chasing)
    _setup_ohlc = df_t.iloc[-2] if len(df_t) >= 2 else df_t.iloc[-1]
    _set_close  = float(_setup_ohlc["close"])
    _set_hi     = float(_setup_ohlc["high"])
    _set_lo     = float(_setup_ohlc["low"])
    _ez_half    = 0.3 * atr
    _ez_top     = _set_hi + _ez_half
    _ez_bot     = _set_lo - _ez_half
    _chase      = (_set_close - price_now) if direction == "SELL" else (price_now - _set_close)
    _chase_max  = 1.5 * atr
    if _chase > _chase_max:
        _reject(df_t, f"LATE_ENTRY(chase={_chase:.2f}/max={_chase_max:.2f})"); return None
    if direction == "SELL" and price_now > _ez_top:
        _reject(df_t, f"ZONE_PASSED(price={price_now:.2f}>top={_ez_top:.2f})"); return None
    if direction == "BUY" and price_now < _ez_bot:
        _reject(df_t, f"ZONE_PASSED(price={price_now:.2f}<bot={_ez_bot:.2f})"); return None

    # ATR Spike Filter: reject jika ATR melonjak (> 2× median 100 periode)
    if "atr_14" not in df_t.columns or len(df_t) < 102:
        _reject(df_t, "ATR_DATA_INSUFFICIENT")
        return None
    atr_window = df_t["atr_14"].iloc[-101:-1]
    n_valid = int(atr_window.notna().sum())
    if n_valid < 50:
        _reject(df_t, "ATR_DATA_INSUFFICIENT")
        return None
    atr_baseline = atr_window.median()
    if atr_baseline > 0 and atr > 2.0 * atr_baseline:
        _reject(df_t, "ATR_SPIKE")
        return None

    # GATE 4 — SL/TP (Pure ATR-based system)
    plan = swing_based_sltp(
        direction=direction, price_now=price_now, df=df_t, atr=atr,
        spread=spread, is_scalping=is_scalping,
    )
    
    if plan is not None and plan.reject_reason:
        _reject(df_t, plan.reject_reason)
        return None
    
    if plan is None:
        _reject(df_t, "SLTP_NONE")
        return None
    sl_method = plan.sl_source

    # GATE 5 — Confluence
    eff_tp1_rr = plan.rr_tp1
    eff_tp2_rr = plan.rr_tp2
    eff_tp3_rr = plan.rr_tp3
    conf_score, conf_notes, conf_detail = _confluence_score(
        df=df_t, direction=direction, entry=price_now, atr=atr,
        tf=trigger_tf, is_scalping=is_scalping, sl=float(plan.sl),
        tp1_rr=eff_tp1_rr, data_by_tf=data_by_tf, now_utc=now_utc,
        sweep_enabled=scalping_sweep_enabled, fvg_enabled=scalping_fvg_enabled,
    )
    if conf_score == -99:
        _reject(df_t, f"ASIAN_NO_KEY_LEVEL [{conf_notes}]" if "ASIAN_NO_KEY_LEVEL" in conf_notes else f"SNR_BLOCKED [{conf_notes}]"); return None
    if conf_score < eff_conf:
        _reject(df_t, f"CONFLUENCE_FAIL conf={conf_score}/{eff_conf}[{conf_notes}] cond={market_cond}")
        return None

    # RANGE lane wajib key level (SnR/SnD)
    if _range_active and not _has_key_level(conf_notes):
        _reject(df_t, f"RANGE_NO_KEY_LEVEL[{conf_notes}]")
        return None

    # H1 wajib key level (WR historis 19% tanpa gate ini)
    if trigger_tf == "H1" and h1_require_key_level and not _has_key_level(conf_notes):
        _reject(df_t, f"H1_NO_KEY_LEVEL[{conf_notes}]")
        return None

    # FLIP wajib key level (entry melawan bias HTF hanya valid di level)
    if _flip_active and flip_require_key_level and not _has_key_level(conf_notes):
        _reject(df_t, f"FLIP_NO_KEY_LEVEL[{conf_notes}]")
        return None

    # RANGE/sideways continuation wajib level berkualitas (SnR 3-touch / FIB_GOLDEN)
    if range_quality_key_level and not (_pb_active or _range_active or _flip_active or _is_counter):
        if market_state in ("RANGE", "CLEAN") or market_cond == "sideways":
            if not _has_quality_key_level(conf_notes):
                _reject(df_t, f"RANGE_QUALITY_NO_KEY_LEVEL[{conf_notes}]")
                return None

    # MOM_RECOVERY wajib level dekat entry (SnR/SnD/FIB_GOLDEN)
    _is_mom_recovery = "MOM_RECOVERY:" in bias_detail and "MOM_RECOVERY_FAIL" not in bias_detail
    if _is_mom_recovery and not (_pb_active or _range_active or _flip_active or _is_counter):
        if not (_has_key_level(conf_notes) or "FIB_GOLDEN" in conf_notes):
            _reject(df_t, f"MOM_RECOVERY_NO_LEVEL[{conf_notes}] bias={bias_detail}")
            return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr            = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
    rr_tp2_actual = calc_rr(direction, entry_for_rr, plan.sl, plan.tp2)
    # Overextension guard: tolak entry yang terlalu jauh dari EMA20
    if is_scalping:
        _closed = df_t.iloc[:-1]
        if len(_closed) >= 30 and "close" in _closed.columns:
            _ema20 = _closed["close"].ewm(span=20, adjust=False).mean().iloc[-1]
            _over  = (price_now - _ema20) if direction == "BUY" else (_ema20 - price_now)
            _oe_max = scalping_overextend_atr_mult * atr
            if _over > _oe_max:
                _reject(df_t, f"OVEREXTENSION(ema20_dist={_over:.2f}/max={_oe_max:.2f})"); return None

    # Dedup lintas-TF: kirim duplikat arah-sama hanya bila konfluensi lebih tinggi
    _conf_key   = (symbol, direction)
    _now_ts     = close_time_ts.timestamp()
    _curr_conf  = float(conf_score)
    _prev_emit  = _LAST_LIVE_EMIT.get(_conf_key)
    if _prev_emit and (_now_ts - _prev_emit[0]) <= _CONFLICT_WINDOW_SEC:
        if _curr_conf <= _prev_emit[1]:
            _reject(df_t, f"CONFLICT_SUPPRESS(prev_conf={_prev_emit[1]:.0f}>=now={_curr_conf:.0f})")
            return None
    _LAST_LIVE_EMIT[_conf_key] = (_now_ts, _curr_conf)

    ts_to_save = close_time_ts.tz_localize(None) if close_time_ts.tzinfo is not None else close_time_ts
    _LAST_SIGNAL_TIME[key] = ts_to_save
    _save_cooldown_state()
    _reject(df_t, "OK")

    setup_mode, setup_note = classify_entry_setup(df_t, direction, atr)
    _state_mode: str | None = None
    if _mom_active:
        _state_mode = "BREAKOUT_MOMENTUM" if market_state == "BREAKOUT" else "MOMENTUM"
    elif _range_active:
        _state_mode = "RANGE_REJECT"
    base_mode = "FLIP" if _flip_active else (_state_mode or ("PULLBACK" if _pb_active else ("REVERSAL" if _is_counter else "CONTINUATION")))
    final_mode = base_mode if _flip_active else (setup_mode if setup_mode else base_mode)
    mkt_tag = f" [{market_cond.upper()}/{market_state}]" if market_cond else ""

    trade_mode, exec_tf = _detect_trade_mode(trigger_tf)
    enter_tag = f" [setup={final_mode}]" if setup_mode else ""
    return Signal(
        symbol=symbol, tf=trigger_tf, direction=direction, close_time=close_time,
        signal_type="LIVE",
        signal_mode=final_mode,
        entry=float(entry_for_rr), entry_low=float(plan.entry_low),
        entry_high=float(plan.entry_high), sl=float(plan.sl),
        tp=float(plan.tp1), tp2=float(plan.tp2), tp3=float(plan.tp3),
        rr=float(rr), rr_tp2_actual=float(rr_tp2_actual or 0.0),
        sl_method=sl_method, atr_value=float(atr),
        tp1_rr=float(eff_tp1_rr), tp2_rr=float(eff_tp2_rr), tp3_rr=float(eff_tp3_rr),
        trigger_score=trig_score, trigger_max=6, confluence_score=conf_score,
        htf_bias=bias_detail, htf_bias_all=_all_tf_bias(data_by_tf),
        trigger_notes=f"{trig_notes}{mkt_tag}",
        confluence_notes=conf_notes,
        pattern_names=conf_detail["pattern_names"],
        fib_detail=conf_detail["fib_detail"], snr_detail=conf_detail["snr_detail"],
        snd_detail=conf_detail["snd_detail"], divergence_detail=conf_detail["div_detail"],
        sweep_detail=conf_detail["sweep_detail"], fvg_detail=conf_detail["fvg_detail"],
        session_name=sess,
        trade_mode=trade_mode, exec_tf=exec_tf, is_setup_plan=False,
    )
