from __future__ import annotations

TF_ORDER = ["M5", "M15", "H1", "H4", "D1"]

def higher_timeframes(trigger_tf: str, enabled_tfs: list[str]) -> list[str]:
    """
    Ambil daftar timeframe yang lebih besar dari trigger_tf,
    tapi hanya yang ada di enabled_tfs.
    """
    trigger_tf = trigger_tf.upper()
    if trigger_tf not in TF_ORDER:
        return []

    i = TF_ORDER.index(trigger_tf)
    higher = TF_ORDER[i+1:]
    return [tf for tf in higher if tf in enabled_tfs]
