"""signal.py — Model data sinyal trading output dari DSS engine."""

from typing import Literal
from pydantic import BaseModel


Direction = Literal["BUY", "SELL"]


class Signal(BaseModel):
    symbol:     str
    tf:         str
    direction:  Direction
    close_time: str

    entry:      float
    entry_low:  float | None = None
    entry_high: float | None = None
    sl:         float | None = None
    tp:         float | None = None
    tp2:        float | None = None
    tp3:        float | None = None
    rr:         float | None = None
    sl_method:  str   = "fixed"
    tp1_rr:     float = 1.5
    tp2_rr:     float = 2.5
    tp3_rr:     float = 4.0

    trigger_score:    int = 0
    trigger_max:      int = 6
    confluence_score: int = 0
    confluence_max:   int = 7   # maks aktual: Pattern(2)+Div(1)+Fib(2)+SnR(1)+SnD(1)
    htf_bias:         str = ""

    trigger_notes:     str   = ""
    confluence_notes:  str   = ""
    pattern_names:     str   = ""
    fib_detail:        str   = ""
    snr_detail:        str   = ""
    snd_detail:        str   = ""
    divergence_detail: str   = ""
    session_name:      str   = ""
    atr_value:         float = 0.0

    signal_mode:   str  = "trend"
    trade_mode:    str  = "intraday"
    is_setup_plan: bool = False
    exec_tf:       str  = ""
    reason:        str  = ""   # alasan/label internal, dipakai oleh setup plan
