"""
signal_engine.py
================
Entry point evaluasi sinyal -- wrapper tipis di atas anytf_mta_engine.

Bertanggung jawab untuk normalisasi input (uppercase TF, key dict)
sebelum diteruskan ke engine utama.
"""
from __future__ import annotations

import pandas as pd

from src.engine.anytf_mta_engine import evaluate_any_tf_mta
from src.models.signal import Signal


def evaluate_signal(
    data_by_tf:           dict[str, pd.DataFrame],
    symbol:               str,
    trigger_tf:           str,
    enabled_tfs:          list[str],
    # Gate thresholds
    min_rr:               float = 1.5,
    min_confirm_votes:    int   = 1,
    min_trigger_score:    int   = 4,
    min_confluence_score: int   = 2,
    cooldown_bars:        int   = 3,
    atr_min_pct:          float = 0.0006,
    # ATR SL/TP
    sl_atr_mult:          float = 1.5,
    tp1_rr:               float = 1.5,
    tp2_rr:               float = 2.5,
    tp3_rr:               float = 4.0,
    # Fixed SL/TP fallback
    sl_pips:              float = 50.0,
    tp1_pips:             float = 70.0,
    tp2_pips:             float = 100.0,
    tp3_pips:             float = 140.0,
    pip_size:             float = 0.1,
    # Session filter
    session_filter:       bool  = True,
) -> Signal | None:
    """
    Evaluasi sinyal trading untuk satu (symbol, trigger_tf).

    Normalisasi semua key ke uppercase sebelum diteruskan ke engine.

    Returns:
        Signal jika semua gate lulus, None jika tidak.
    """
    trigger_tf_u  = trigger_tf.upper()
    enabled_tfs_u = [tf.upper() for tf in enabled_tfs]
    data_by_tf_u  = {k.upper(): v for k, v in data_by_tf.items()}

    if trigger_tf_u not in data_by_tf_u:
        return None

    return evaluate_any_tf_mta(
        data_by_tf           = data_by_tf_u,
        symbol               = symbol,
        trigger_tf           = trigger_tf_u,
        enabled_tfs          = enabled_tfs_u,
        min_rr               = float(min_rr),
        min_confirm_votes    = int(min_confirm_votes),
        min_trigger_score    = int(min_trigger_score),
        min_confluence_score = int(min_confluence_score),
        cooldown_bars        = int(cooldown_bars),
        atr_min_pct          = float(atr_min_pct),
        sl_atr_mult          = float(sl_atr_mult),
        tp1_rr               = float(tp1_rr),
        tp2_rr               = float(tp2_rr),
        tp3_rr               = float(tp3_rr),
        sl_pips              = float(sl_pips),
        tp1_pips             = float(tp1_pips),
        tp2_pips             = float(tp2_pips),
        tp3_pips             = float(tp3_pips),
        pip_size             = float(pip_size),
        session_filter       = bool(session_filter),
    )
