"""
signal.py
=========
Model data sinyal trading output dari DSS engine.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


Direction = Literal["BUY", "SELL"]


class Signal(BaseModel):
    # ── Identitas ────────────────────────────────────────────────────
    symbol:     str
    tf:         str
    direction:  Direction
    close_time: str        # ISO timestamp candle yang memicu sinyal

    # ── Harga ────────────────────────────────────────────────────────
    entry:      float
    entry_low:  float | None = None
    entry_high: float | None = None
    sl:         float | None = None
    tp:         float | None = None    # TP1
    tp2:        float | None = None
    tp3:        float | None = None
    rr:         float | None = None
    sl_method:  str          = "fixed" # "dynamic_atr" | "fixed"
    tp1_rr:     float        = 1.5     # RR target TP1
    tp2_rr:     float        = 2.5     # RR target TP2
    tp3_rr:     float        = 4.0     # RR target TP3

    # ── Skor keputusan (Layer 1 & 2) ─────────────────────────────────
    trigger_score:    int = 0          # 0-6
    trigger_max:      int = 6
    confluence_score: int = 0          # 0-5+
    confluence_max:   int = 5
    htf_bias:         str = ""         # contoh: "M15:BULL H4:BULL D1:BULL"

    # ── Catatan analisis (untuk Telegram & CSV logger) ────────────────
    trigger_notes:     str   = ""      # contoh: "EMA200+ EMA50+ ALIGN+ RSI+(55)"
    confluence_notes:  str   = ""      # contoh: "Pattern+ Fib+ SnR+ SnD+ Div+"
    pattern_names:     str   = ""      # contoh: "CDLENGULFING, CDLMORNINGSTAR"
    fib_detail:        str   = ""      # contoh: "FIB_STRONG(fib_0.618=3311.50)"
    snr_detail:        str   = ""      # contoh: "S~3305.20 R~3340.00"
    snd_detail:        str   = ""      # contoh: "SND_DEMAND(3308.50-3313.00)"
    divergence_detail: str   = ""      # contoh: "RSI_DIV+MACD_DIV"
    session_name:      str   = ""      # contoh: "London", "New York", "Overlap L+NY"
    atr_value:         float = 0.0

    # ── Legacy reason string (dipertahankan untuk kompatibilitas log) ─
    reason: str = ""
