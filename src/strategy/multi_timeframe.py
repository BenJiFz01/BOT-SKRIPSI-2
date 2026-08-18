"""multi_timeframe.py — Urutan timeframe dan helper HTF selection."""

TF_ORDER = ["M5", "M15", "H1", "H4", "D1"]


def higher_timeframes(trigger_tf: str, enabled_tfs: list[str]) -> list[str]:
    """Kembalikan TF yang lebih tinggi dari trigger_tf (dari enabled_tfs)."""
    trigger_tf  = trigger_tf.upper()
    enabled_up  = [t.upper() for t in enabled_tfs]
    if trigger_tf not in TF_ORDER:
        return enabled_up
    idx = TF_ORDER.index(trigger_tf)
    return [tf for tf in TF_ORDER[idx + 1:] if tf in enabled_up]
