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
from src.engine.state import _decisive_adx, _market_state, detect_market_condition
from src.engine.trigger import _has_key_level, _range_rejection_setup, _scalp_pullback_setup, _trigger_score
from src.engine.utils import _atr_proxy, _latest_closed, _reject, calc_rr
from src.features.entry_setup import classify_entry_setup
from src.features.session import is_active_session, session_name, session_strictness
from src.models.signal import Signal
from src.risk.sl_tp import dynamic_atr_sltp, fixed_zone_sltp, swing_based_sltp
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
    scalping_atr_min_points:       float            = 3.0,
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
) -> Signal | None:
    """Evaluasi sinyal untuk satu (symbol, trigger_tf). Returns Signal jika 5 gate lulus."""
    trigger_tf  = trigger_tf.upper()
    enabled_tfs = [tf.upper() for tf in enabled_tfs]

    if trigger_tf not in data_by_tf:
        return None

    df_t = data_by_tf[trigger_tf]
    _reject(df_t, "INIT")

    # Circuit breaker: counter loss terpisah per mode (key "{symbol}_{mode}") —
    # loss scalping tak memblokir intraday dan sebaliknya.
    today_str   = datetime.now().strftime("%Y-%m-%d")
    _is_scalping_tf = trigger_tf in {"M5", "M15"}
    _cb_key     = f"{symbol}_{'scalping' if _is_scalping_tf else 'intraday'}"
    _cb_mode    = "scalping" if _is_scalping_tf else "intraday"

    # GATE 1 — Validasi teknis
    if len(df_t) < 200:
        _reject(df_t, f"NOT_ENOUGH_BARS({len(df_t)})"); return None

    last          = _latest_closed(df_t)
    close_time_ts = pd.to_datetime(last["time"])
    # Simpan sebagai UTC eksplisit (suffix +00:00) agar iso_to_wib_str() tahu perlu konversi
    close_time    = str(close_time_ts.to_pydatetime().replace(tzinfo=pytz.utc).isoformat())
    price_now     = float(last["close"])
    atr           = _atr_proxy(df_t)

    if atr <= 0:
        _reject(df_t, "ATR_INVALID"); return None
    if atr < price_now * atr_min_pct:
        _reject(df_t, f"ATR_TOO_LOW({atr:.4f})"); return None

    is_scalping = trigger_tf in {"M5", "M15"}

    # ATR absolut khusus scalping: tolak rentang paling sempit supaya SL/TP ATR-based
    # punya ruang; atr_min_pct (relatif) tetap menjaring pasar ultra-flat.
    if is_scalping and scalping_atr_min_points > 0 and atr < scalping_atr_min_points:
        _reject(df_t, f"ATR_TOO_LOW_SCALPING(atr={atr:.2f}/min={scalping_atr_min_points:.1f})")
        return None

    if is_scalping:
        base_trig  = scalping_min_trigger_score
        base_conf  = scalping_min_confluence_score
        # Cooldown per-TF: M5/M15 punya nilai sendiri, TF lain fallback ke umum.
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
    
    # Asian CONTINUATION: +1 trigger & +1 confluence. Bias baru diketahui di GATE 2,
    # maka session dicek di sini; hanya jalur CONTINUATION (REVERSAL/CT tak terpengaruh).
    if _asian_continuation_pending and session_strictness(now_utc, tf=trigger_tf) == "RELAXED":
        eff_trig += 1
        eff_conf += 1

    # Cap: sideways(+1) dan asian(+1) bisa numpuk — tanpa cap butuh semua komponen
    # sepakat (nyaris mustahil). Trig cap 5, conf cap 4.
    eff_trig = min(eff_trig, 5)
    eff_conf = min(eff_conf, 4)

    if session_filter and not is_active_session(now_utc, trigger_tf):
        _reject(df_t, f"OUT_OF_SESSION({sess})"); return None

    # GATE 2 — HTF Bias
    confirm_tfs       = higher_timeframes(trigger_tf, enabled_tfs)
    bias, bias_detail = _vote_bias(
        data_by_tf=data_by_tf, confirm_tfs=confirm_tfs,
        trigger_tf=trigger_tf, min_confirm_votes=min_confirm_votes,
        scalping_h1_only=scalping_h1_only,
        intraday_require_d1=intraday_require_d1,
    )

    # GATE 3 — Trigger Score (Market-State Dispatch)
    direction:    str | None = None
    trig_score:   int        = 0
    trig_notes:   str        = ""
    _is_counter:  bool       = False
    _pb_active:   bool       = False
    _mom_active:  bool       = False
    _range_active: bool      = False

    # Market State Detector (2026-09-24): klasifikasi kondisi pasar → PILIH JALUR entry.
    # State hanya menukar logic aktif, gate/threshold tetap utuh.
    market_state, state_note = _market_state(
        df_t, trigger_tf, data_by_tf,
        market_transition_adx_block, market_transition_adx_gray,
    )

    if bias in ("BULL", "BEAR"):
        dir_try = "BUY" if bias == "BULL" else "SELL"

        # MARKET TRANSITION: tren kehabisan tenaga — continuation diblokir sebelum
        # buang-buang perhitungan (reversal/breakout jalur ketat; reversal off default).
        if market_state == "TRANSITION":
            _reject(df_t, f"MARKET_TRANSITION(state={state_note})")
            return None

        # Jalur 1 — CONTINUATION (trigger standar, gate EMA200 ketat 0.2×ATR).
        ok, sc, nt = _trigger_score(df_t, dir_try, eff_trig)
        if ok:
            direction, trig_score, trig_notes = dir_try, sc, nt
        elif scalping_pullback_enabled and is_scalping:
            # Jalur 2 — PULLBACK (retrace 23-78.6% dlm tren kuat), diprioritaskan sebelum
            # momentum — hanya tanpa pullback, berlanjut ke jalur momentum.
            _pb_ok, _pb_note = _scalp_pullback_setup(df_t, dir_try, atr)
            if _pb_ok:
                direction, trig_score, trig_notes = dir_try, 0, f"PULLBACK[{_pb_note}]"
                _pb_active = True
            else:
                # Jalur 3 — MOMENTUM/BREAKOUT (tren kuat TANPA pullback → harga tak
                # kembali ke EMA200): gate EMA200 dilonggarkan via MOMENTUM_EMA200_TOLERANCE.
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

        # Market Transition Gate (zonasi ADX abu-abu): block..gray → +1 confluence.
        _dec_reason, _dec_bonus = _decisive_adx(
            trigger_tf, data_by_tf, market_transition_adx_block,
            market_transition_adx_gray,
        )
        if _dec_reason:
            _reject(df_t, _dec_reason)
            return None
        eff_conf = min(eff_conf + _dec_bonus, 5)
    else:
        # Bias HTF NEUTRAL → dua pilihan: CT/reversal (off default) atau RANGE lane.
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
            # RANGE lane: sideways ASLI (bias netral + ADX sinyal rendah) → rejection di
            # level kunci. Key level (SnR/SnD) diverifikasi di GATE 5; tanpa level = NO SIGNAL.
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

    # Late-entry: tolak harga terlalu jauh dari trigger candle (>1.5×ATR) — entry chasing
    # SL rawan kena retracement. Real-time (dist=0) otomatis lolos.
    _trig_close = float(df_t.iloc[-2]["close"]) if len(df_t) >= 2 else price_now
    _late_dist  = abs(price_now - _trig_close)
    _late_max   = 1.5 * atr
    if _late_dist > _late_max:
        _reject(df_t, f"LATE_ENTRY(dist={_late_dist:.2f}/max={_late_max:.2f})"); return None

    # GATE 4 — SL/TP
    # RR berbeda untuk scalping (ambil profit cepat) vs intraday
    eff_tp1_rr = scalping_tp1_rr if is_scalping else tp1_rr
    eff_tp2_rr = scalping_tp2_rr if is_scalping else tp2_rr
    eff_tp3_rr = scalping_tp3_rr if is_scalping else tp3_rr

    if is_scalping:
        plan = swing_based_sltp(
            direction=direction, price_now=price_now, df=df_t, atr=atr,
            is_scalping=True, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
            max_sl=max_sl_points, sl_atr_mult_override=scalping_sl_atr_mult,
            tp1_atr_mult_override=scalping_tp1_atr_mult,
        )
        if plan is None:
            plan = dynamic_atr_sltp(
                direction=direction, price_now=price_now, atr=atr,
                is_scalping=True, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
                max_sl=max_sl_points, df=df_t, sl_atr_mult_override=scalping_sl_atr_mult,
                tp1_atr_mult_override=scalping_tp1_atr_mult,
            )
        sl_method = "swing" if (plan is not None and "Swing" in (plan.method or "")) else "dynamic_atr"
    else:
        plan = dynamic_atr_sltp(
            direction=direction, price_now=price_now, atr=atr,
            is_scalping=False, tp1_rr=eff_tp1_rr, tp2_rr=eff_tp2_rr, tp3_rr=eff_tp3_rr,
            max_sl=max_sl_points, df=df_t, data_by_tf=data_by_tf,
            sl_atr_mult_override=sl_atr_mult,
        )
        sl_method = "dynamic_atr"
    if plan is None:
        plan = fixed_zone_sltp(
            direction=direction, price_now=price_now,
            entry_zone_pips=30, sl_pips=sl_pips,
            tp1_pips=tp1_pips, tp2_pips=tp2_pips, tp3_pips=tp3_pips,
            pip_size=pip_size,
        )
        sl_method = "fixed"
    if plan is None:
        _reject(df_t, "SLTP_NONE"); return None

    # GATE 5 — Confluence + RR
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

    # RANGE lane wajib punya key level (SnR/SnD) — rejection di level, bukan di tempat kosong.
    # (Tanpa level, konfluensi bisa lolos via Pattern/Fib — di range itu = noise.)
    if _range_active and not _has_key_level(conf_notes):
        _reject(df_t, f"RANGE_NO_KEY_LEVEL[{conf_notes}]")
        return None

    entry_for_rr = plan.entry_high if direction == "BUY" else plan.entry_low
    rr            = calc_rr(direction, entry_for_rr, plan.sl, plan.tp1)
    rr_tp2_actual = calc_rr(direction, entry_for_rr, plan.sl, plan.tp2)
    # Gate anti-chase (pengganti RR gate — TP proporsional SL membuat rr tetap): tolak entry
    # yang "ngejar" — harga lebih jauh dari EMA20 sinyal-TF dari batas (×ATR).
    if is_scalping:
        _closed = df_t.iloc[:-1]
        if len(_closed) >= 30 and "close" in _closed.columns:
            _ema20 = _closed["close"].ewm(span=20, adjust=False).mean().iloc[-1]
            _over  = (price_now - _ema20) if direction == "BUY" else (_ema20 - price_now)
            _oe_max = scalping_overextend_atr_mult * atr
            if _over > _oe_max:
                _reject(df_t, f"OVEREXTENSION(ema20_dist={_over:.2f}/max={_oe_max:.2f})"); return None

    # Normalisasi ke tz-naive sebelum simpan agar konsisten saat load ulang
    ts_to_save = close_time_ts.tz_localize(None) if close_time_ts.tzinfo is not None else close_time_ts
    _LAST_SIGNAL_TIME[key] = ts_to_save
    _save_cooldown_state()
    _reject(df_t, "OK")

    # [8-Strategi — ADITIF] Label setup classifier (display/dedup, tak ubah skor-gate-threshold)
    setup_mode, setup_note = classify_entry_setup(df_t, direction, atr)
    # Mode dasar diambil dr JALUR yang aktif (state-based): momentum lane di atas
    # tren kuat tanpa pullback dilabeli MOMENTUM (atau BREAKOUT kalau state breakout).
    _state_mode: str | None = None
    if _mom_active:
        _state_mode = "BREAKOUT_MOMENTUM" if market_state == "BREAKOUT" else "MOMENTUM"
    elif _range_active:
        _state_mode = "RANGE_REJECT"
    base_mode = _state_mode or ("PULLBACK" if _pb_active else ("REVERSAL" if _is_counter else "CONTINUATION"))
    final_mode = setup_mode if setup_mode else base_mode
    mkt_tag = f" [{market_cond.upper()}/{market_state}]" if market_cond else ""

    # [Conflict resolver — anti spam "3 sinyal sekaligus"] dedup LINTAS-TF per (symbol, direction):
    # kirim duplikat arah-sama dalam window hanya bila konfluensinya LEBIH TINGGI dr yg terakhir.
    _conf_key   = (symbol, direction)
    _now_ts     = close_time_ts.timestamp()
    _curr_conf  = float(conf_score)
    _prev_emit  = _LAST_LIVE_EMIT.get(_conf_key)
    if _prev_emit and (_now_ts - _prev_emit[0]) <= _CONFLICT_WINDOW_SEC:
        if _curr_conf <= _prev_emit[1]:
            _reject(df_t, f"CONFLICT_SUPPRESS(prev_conf={_prev_emit[1]:.0f}>=now={_curr_conf:.0f})")
            return None
    _LAST_LIVE_EMIT[_conf_key] = (_now_ts, _curr_conf)

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
