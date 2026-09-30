"""Pemetaan label & catatan mode sinyal lintas laporan (update_hasil + report sheets).

Dipisah di satu modul supaya label FLIP/REVERSAL/PULLBACK konsisten di mana pun
ditampilkan, dan hasilnya bisa dipecah per mode untuk evaluasi.
"""

MODE_LABELS: dict[str, str] = {
    "CONTINUATION":       "Trend Following",
    "MOMENTUM":           "Momentum",
    "BREAKOUT":           "Breakout",
    "BREAKOUT_MOMENTUM":  "Breakout Momentum",
    "PULLBACK":           "Pullback",
    "REVERSAL":           "Reversal (Lawan HTF)",
    "FLIP":               "FLIP (Awal Tren LTF)",
}

MODE_NOTES: dict[str, str] = {
    "CONTINUATION":       "Mengikuti arah bias HTF",
    "MOMENTUM":           "Momentum kuat searah bias HTF",
    "BREAKOUT":           "Breakout level kunci",
    "BREAKOUT_MOMENTUM":  "Breakout level + momentum",
    "PULLBACK":           "Pullback/retracement menuju bias HTF",
    "REVERSAL":           "Counter trend melawan bias HTF",
    "FLIP":               "Arah berlawanan bias HTF (base/swing break LTF)",
}


def mode_label(mode: str) -> str:
    return MODE_LABELS.get((mode or "").upper(), mode or "")


def mode_note(mode: str) -> str:
    return MODE_NOTES.get((mode or "").upper(), "")