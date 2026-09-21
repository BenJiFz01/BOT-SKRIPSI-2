"""signal.py — Model data sinyal trading output dari engine."""
from typing import Literal
from pydantic import BaseModel


Direction  = Literal["BUY", "SELL"]
SignalMode = Literal["CONTINUATION", "REVERSAL", "BREAKOUT"]


class Signal(BaseModel):
    # Identitas
    symbol:     str
    tf:         str
    direction:  Direction
    close_time: str

    # Klasifikasi
    signal_type: str       = "LIVE"          # "LIVE" | "SETUP"
    signal_mode: SignalMode = "CONTINUATION"  # "CONTINUATION" | "REVERSAL" | "BREAKOUT"
    is_setup_plan: bool    = False

    # Entry
    entry:       float
    entry_low:   float | None = None
    entry_high:  float | None = None

    # SL / TP
    sl:   float | None = None
    tp:   float | None = None
    tp2:  float | None = None
    tp3:  float | None = None
    rr:   float | None = None
    # RR struktural (runner) — acuan gate RR; TP1 scalping ATR-based, RR bisa <1
    rr_tp2_actual: float = 0.0

    sl_method: str   = "fixed"
    tp1_rr:    float = 1.0
    tp2_rr:    float = 2.0
    tp3_rr:    float = 3.0

    # Scoring
    trigger_score:    int = 0
    trigger_max:      int = 6
    confluence_score: int = 0
    confidence:       int = 0
    htf_bias:         str = ""

    # Detail komponen
    trigger_notes:     str = ""
    confluence_notes:  str = ""
    pattern_names:     str = ""
    fib_detail:        str = ""
    snr_detail:        str = ""
    snd_detail:        str = ""
    divergence_detail: str = ""

    # Metadata
    session_name: str   = ""
    atr_value:    float = 0.0
    trade_mode:   str   = "intraday"
    exec_tf:      str   = ""
    reason:       str   = ""

    # Manajemen posisi
    breakeven_sl:    float | None = None
    trailing_sl_tp2: float | None = None
    lot_split_tp1:   int = 50
    lot_split_tp2:   int = 30
    lot_split_tp3:   int = 20
