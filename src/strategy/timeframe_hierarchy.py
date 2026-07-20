"""
timeframe_hierarchy.py
======================
Hierarki timeframe untuk analisis multi-timeframe (top-down).

Urutan dari terkecil ke terbesar: M5 -> M15 -> H1 -> H4 -> D1.
"""
from __future__ import annotations


TF_ORDER = ["M5", "M15", "H1", "H4", "D1"]


def higher_timeframes(trigger_tf: str, enabled_tfs: list[str]) -> list[str]:
    """
    Kembalikan daftar timeframe yang lebih besar dari `trigger_tf`.

    Hanya timeframe yang ada di `enabled_tfs` yang dikembalikan.

    Args:
        trigger_tf:  Timeframe trigger, contoh "M5".
        enabled_tfs: Daftar timeframe yang aktif.

    Returns:
        List timeframe lebih besar, terurut dari kecil ke besar.
        Contoh: higher_timeframes("M15", ["M5","M15","H1","H4","D1"])
                -> ["H1", "H4", "D1"]
    """
    trigger_tf = trigger_tf.upper()
    if trigger_tf not in TF_ORDER:
        return []

    i      = TF_ORDER.index(trigger_tf)
    higher = TF_ORDER[i + 1:]
    return [tf for tf in higher if tf in enabled_tfs]
