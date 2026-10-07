"""Test Early Breakeven (Proteksi Dini Khusus H1).

Skenario yang diuji:
1. Sinyal H1 bergerak profit >= 50% jarak ke TP1 -> Early Breakeven aktif.
2. Harga berbalik arah menyentuh BE -> outcome BREAKEVEN (bukan LOSS).
3. Sinyal M5 (scalping) tidak mengaktifkan Early BE (tetap pakai aturan normal BE saat TP1 hit).
4. Sinyal H1 yang langsung turun tanpa sempat profit 50% -> tetap LOSS.
"""
import sys, os
sys.path.insert(0, r"D:\BOT SKRIPSI 2")
os.environ["PYTHONIOENCODING"] = "utf-8"

from datetime import datetime
import unittest.mock as mock
import threading

import src.infra.signal_tracker as _tracker_mod
from src.infra.signal_tracker import TrackedSignal
from src.utils.time_utils import TZ_WIB

_outcomes = []
def _fake_resolve(self, ts, outcome, price, now, reason=""):
    ts.resolved = True
    _outcomes.append((outcome, price, reason))

_tracker_mod.SignalTracker._resolve = _fake_resolve
_tracker_mod.SignalTracker._send_tp_notify = lambda self, header, sid, px: None
_tracker_mod.logger = mock.MagicMock()

tracker_inst = object.__new__(_tracker_mod.SignalTracker)
tracker_inst._logger = mock.MagicMock()
tracker_inst._get_price = None
tracker_inst._notify = None
tracker_inst._refresh_report = None
tracker_inst._startup_signal_ids = set()
tracker_inst._lock = threading.Lock()

def make_signal(sid="XAUUSD_H1_999", tf="H1", entry=4200.0, sl=4190.0, tp1=4215.0, spread=0.3):
    ts = TrackedSignal(
        signal_id=sid,
        symbol="XAUUSD",
        direction="BUY",
        entry=entry,
        entry_low=entry - 0.1,
        entry_high=entry + 0.1,
        sl=sl,
        tp1=tp1,
        tp2=4225.0,
        tp3=4235.0,
        start_time=datetime.now(tz=TZ_WIB),
        spread=spread,
        timeframe=tf,
    )
    ts.entry_zone_hit = True
    return ts

print("=== TEST EARLY BREAKEVEN (H1 INTRADAY PROTECTION) ===\n")

# Test 1: Sinyal H1 profit mencapai 50% jarak TP1 (target=15pt, 50%=7.5pt -> harga 4208)
_outcomes.clear()
ts1 = make_signal("XAUUSD_H1_001", "H1", entry=4200.0, sl=4190.0, tp1=4215.0)
tracker_inst._evaluate(ts1, bid=4208.0, ask=4208.0)
ok1_be = ts1.breakeven_sl is not None and abs(ts1.breakeven_sl - 4200.3) < 0.01
print(f"Test 1: Floating profit +8pt (>= 7.5pt)")
print(f"  breakeven_sl: {ts1.breakeven_sl} (expected 4200.30) -> {'PASS' if ok1_be else 'FAIL'}")

# Test 2: Harga berbalik turun ke 4200.2 (<= BE 4200.30) -> BREAKEVEN, bukan LOSS!
tracker_inst._evaluate(ts1, bid=4200.2, ask=4200.2)
ok2 = len(_outcomes) == 1 and _outcomes[0][0] == "BREAKEVEN"
print(f"\nTest 2: Harga berbalik ke level BE")
print(f"  Outcome: {_outcomes[0] if _outcomes else None} -> {'PASS' if ok2 else 'FAIL'}")

# Test 3: Sinyal M5 (scalping) tidak mengaktifkan Early BE di +8pt sebelum TP1
_outcomes.clear()
ts_m5 = make_signal("XAUUSD_M5_001", "M5", entry=4200.0, sl=4190.0, tp1=4215.0)
tracker_inst._evaluate(ts_m5, bid=4208.0, ask=4208.0)
ok3 = ts_m5.breakeven_sl is None
print(f"\nTest 3: Sinyal M5 pada profit 50% (tidak aktifkan early BE)")
print(f"  breakeven_sl: {ts_m5.breakeven_sl} -> {'PASS' if ok3 else 'FAIL'}")

# Test 4: Sinyal H1 yang langsung turun tanpa sempat profit -> LOSS murni
_outcomes.clear()
ts4 = make_signal("XAUUSD_H1_004", "H1", entry=4200.0, sl=4190.0, tp1=4215.0)
tracker_inst._evaluate(ts4, bid=4189.0, ask=4189.0)
ok4 = len(_outcomes) == 1 and _outcomes[0][0] == "LOSS"
print(f"\nTest 4: Sinyal H1 langsung turun ke SL")
print(f"  Outcome: {_outcomes[0] if _outcomes else None} -> {'PASS' if ok4 else 'FAIL'}")

oks = [ok1_be, ok2, ok3, ok4]
print(f"\nTotal: {sum(oks)}/{len(oks)} PASS")
sys.exit(0 if all(oks) else 1)
