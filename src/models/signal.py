from __future__ import annotations
from pydantic import BaseModel
from typing import Literal

Direction = Literal["BUY", "SELL"]

class Signal(BaseModel):
    symbol: str
    tf: str
    direction: Direction
    close_time: str
    entry: float
    sl: float | None = None
    tp: float | None = None
    rr: float | None = None
    reason: str
