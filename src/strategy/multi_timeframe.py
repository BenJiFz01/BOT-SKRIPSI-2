"""multi_timeframe.py — Urutan timeframe untuk analisis multi-timeframe."""
from __future__ import annotations


TF_ORDER = ["M5", "M15", "H1", "H4", "D1"]


def higher_timeframes(trigger_tf: str, enabled_tfs: list[str]) -> list[str]:
    """Kembalikan TF yang lebih besar dari trigger_tf dan ada di enabled_tfs."""
    trigger_tf = trigger_tf.upper()
    if trigger_tf not in TF_ORDER:
        return []
    i = TF_ORDER.index(trigger_tf)
    return [tf for tf in TF_ORDER[i + 1:] if tf in enabled_tfs]
