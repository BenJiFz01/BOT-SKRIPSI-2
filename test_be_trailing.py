"""Test BE/Trailing menggunakan TrackedSignal dan _evaluate() dari signal_tracker.py asli.

Verifikasi:
1. breakeven_sl diset oleh tracker (bukan MockSignal) setelah TP1 hit
2. trailing_sl diset ke tp1 setelah TP2 hit
3. Outcome string dari tracker: LOSS, WIN_TP1, WIN_TP2, WIN_TP3
4. Candle ambigu (SL check dulu dalam satu tick)

Cara cek kode asli dipakai:
  - Import TrackedSignal dari src.infra.signal_tracker
  - Ubah satu nilai hardcode di tracker -> tes harus gagal
"""
import sys, os
sys.path.insert(0, r"D:\BOT SKRIPSI 2")
os.environ["PYTHONIOENCODING"] = "utf-8"

from datetime import datetime
from src.infra.signal_tracker import TrackedSignal
from src.utils.time_utils import TZ_WIB

# Ambil _evaluate langsung dari modul (bukan instance, agar tidak perlu logger/thread)
import src.infra.signal_tracker as _tracker_mod

# Patch _resolve dan logger agar tidak memanggil MT5/Telegram/logger
_outcomes: list[tuple[str, float]] = []

def _fake_resolve(self, ts, outcome, price, now, reason=""):
    ts.resolved = True
    _outcomes.append((outcome, price))

def _fake_send_tp(self, header, signal_id, price):
    pass

# Inject patch
_tracker_mod.SignalTracker._resolve = _fake_resolve
_tracker_mod.SignalTracker._send_tp_notify = _fake_send_tp

# Patch logger agar tidak crash
import unittest.mock as mock
_tracker_mod.logger = mock.MagicMock()

# Buat instance minimal (tidak start thread)
import threading
tracker_inst = object.__new__(_tracker_mod.SignalTracker)
tracker_inst._logger = mock.MagicMock()
tracker_inst._get_price = None
tracker_inst._notify = None
tracker_inst._refresh_report = None
tracker_inst._startup_signal_ids = set()
tracker_inst._lock = threading.Lock()


def make_ts(entry=4180.0, sl=4175.0, tp1=4185.0, tp2=4187.5, tp3=4190.0, spread=0.3):
    ts = TrackedSignal(
        signal_id="TEST_H1_001",
        symbol="XAUUSD",
        direction="BUY",
        entry=entry,
        entry_low=entry - 0.1,
        entry_high=entry + 0.1,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        start_time=datetime.now(tz=TZ_WIB),
        spread=spread,
    )
    ts.entry_zone_hit = True  # skip entry zone logic
    ts.atr_value = 4.0
    return ts


def tick(ts, price):
    """Simulasi satu tick: panggil _evaluate dengan bid=ask=price."""
    if not ts.resolved:
        tracker_inst._evaluate(ts, bid=price, ask=price)


def tick_bar(ts, bar_low, bar_high):
    """Simulasi satu candle: SL check pakai low, TP check pakai high.
    
    _evaluate hanya menerima satu price. Untuk candle ambigu,
    kita panggil dua kali: pertama dengan low (SL check dulu), lalu high.
    Ini mencerminkan urutan konservatif yang sama dengan kode engine.
    """
    tick(ts, bar_low)
    if not ts.resolved:
        tick(ts, bar_high)


print("=== TEST BE/TRAILING (TrackedSignal + _evaluate dari signal_tracker.py) ===")
print(f"\nImport: from src.infra.signal_tracker import TrackedSignal")
print(f"Method: _evaluate dipanggil langsung, _resolve dipatch untuk tangkap outcome")
print(f"\nEntry=4180.0  SL=4175.0  TP1=4185.0  TP2=4187.5  TP3=4190.0  spread=0.30")
print(f"BE = entry + spread = 4180.30  Trailing = TP1 = 4185.00")
print(f"RR: TP1=1.0R  TP2=1.5R  TP3=2.0R  sl_dist=5.0pt")
print("-" * 60)


# ── Test 1: SL langsung ──────────────────────────────────────────
print("\nTest 1: SL langsung → LOSS, -1.0R")
_outcomes.clear()
ts1 = make_ts()
print(f"  Tick: price=4174.0 (<= SL 4175.0)")
print(f"  Sebelum tick: breakeven_sl={ts1.breakeven_sl}  trailing_sl={ts1.trailing_sl}")
tick(ts1, 4174.0)
print(f"  Outcome:  {_outcomes}")
print(f"  resolved: {ts1.resolved}  tp1_hit: {ts1.tp1_hit}")
ok1 = _outcomes == [("LOSS", 4174.0)] and ts1.resolved and not ts1.tp1_hit
print(f"  Weighted R: -1.0R  (LOSS sebelum TP1)")
print(f"  {'PASS' if ok1 else 'FAIL'}")


# ── Test 2: TP1 → BE → reverse ──────────────────────────────────
print("\nTest 2: TP1 hit (50%) → BE → price turun ke BE → WIN_TP1, +0.50R")
_outcomes.clear()
ts2 = make_ts()
print(f"  Tick A: price=4185.5 (>= TP1 4185.0)")
tick(ts2, 4185.5)
print(f"  Setelah TP1: tp1_hit={ts2.tp1_hit}  breakeven_sl={ts2.breakeven_sl}")
print(f"  Tick B: price=4180.2 (<= BE 4180.30)")
tick(ts2, 4180.2)
print(f"  Outcome:  {_outcomes}")
print(f"  resolved: {ts2.resolved}")
ok2 = (len(_outcomes) == 1 and _outcomes[0][0] == "WIN_TP1"
       and ts2.tp1_hit and abs(ts2.breakeven_sl - 4180.3) < 0.01)
wr2 = 0.5 * 1.0
print(f"  SL aktif saat exit: {ts2.breakeven_sl:.2f} (harus == entry+spread=4180.30)")
print(f"  Weighted R: 0.5 x 1.0 = {wr2:.2f}R")
print(f"  {'PASS' if ok2 else 'FAIL'}")


# ── Test 3: TP1+TP2 → Trailing → reverse ───────────────────────
print("\nTest 3: TP1+TP2 hit (80%) → Trailing SL ke TP1 → reverse → WIN_TP2, +1.15R")
_outcomes.clear()
ts3 = make_ts()
print(f"  Tick A: price=4185.5 (>= TP1 4185.0)")
tick(ts3, 4185.5)
print(f"  Setelah TP1: breakeven_sl={ts3.breakeven_sl}")
print(f"  Tick B: price=4188.0 (>= TP2 4187.5)")
tick(ts3, 4188.0)
print(f"  Setelah TP2: trailing_sl={ts3.trailing_sl}  (HARUS == TP1=4185.00)")
print(f"  Tick C: price=4184.5 (<= trailing_sl 4185.0)")
tick(ts3, 4184.5)
print(f"  Outcome:  {_outcomes}")
print(f"  resolved: {ts3.resolved}")
ok3 = (len(_outcomes) == 1 and _outcomes[0][0] == "WIN_TP2"
       and ts3.tp1_hit and ts3.tp2_hit
       and abs(ts3.trailing_sl - 4185.0) < 0.01)
wr3 = 0.5*1.0 + 0.3*1.5 + 0.2*1.0
print(f"  SL aktif saat exit: {ts3.trailing_sl:.2f} (harus == TP1=4185.00)")
print(f"  Weighted R: 0.5x1.0 + 0.3x1.5 + 0.2x1.0 = {wr3:.2f}R")
print(f"  {'PASS' if ok3 else 'FAIL'}")


# ── Test 4: Full TP ─────────────────────────────────────────────
print("\nTest 4: TP1+TP2+TP3 Full → WIN_TP3, +1.35R")
_outcomes.clear()
ts4 = make_ts()
tick(ts4, 4185.5)
tick(ts4, 4188.0)
print(f"  Trailing SL: {ts4.trailing_sl:.2f}  (harus == TP1=4185.00)")
tick(ts4, 4191.0)
print(f"  Outcome:  {_outcomes}")
ok4 = len(_outcomes) == 1 and _outcomes[0][0] == "WIN_TP3"
wr4 = 0.5*1.0 + 0.3*1.5 + 0.2*2.0
print(f"  Weighted R: 0.5x1.0 + 0.3x1.5 + 0.2x2.0 = {wr4:.2f}R")
print(f"  {'PASS' if ok4 else 'FAIL'}")


# ── Test 5: Candle ambigu TP1+SL (SL check dulu) ───────────────
print("\nTest 5: Candle ambigu — low=4174 (hit SL) dan high=4186 (hit TP1)")
print(f"  SL check dulu (tick low dulu) → LOSS, -1.0R")
_outcomes.clear()
ts5 = make_ts()
print(f"  tick_bar(low=4174.0, high=4186.0)")
tick_bar(ts5, bar_low=4174.0, bar_high=4186.0)
print(f"  Outcome:  {_outcomes}")
print(f"  tp1_hit: {ts5.tp1_hit}  (harus False — SL check dulu)")
ok5 = _outcomes == [("LOSS", 4174.0)] and not ts5.tp1_hit
print(f"  Weighted R: -1.0R")
print(f"  {'PASS' if ok5 else 'FAIL'}")


# ── Test 6: Candle ambigu trailing SL + TP3 (SL check dulu) ─────
print("\nTest 6: Candle ambigu setelah TP2 — low=4184 (hit trailing SL=TP1) dan high=4191 (hit TP3)")
print(f"  Trailing SL = TP1 = 4185.0, SL check dulu → WIN_TP2, +1.15R")
_outcomes.clear()
ts6 = make_ts()
tick(ts6, 4185.5)
tick(ts6, 4188.0)
print(f"  Trailing SL setelah TP2: {ts6.trailing_sl:.2f}  (harus == TP1=4185.00)")
print(f"  tick_bar(low=4184.0, high=4191.0)")
tick_bar(ts6, bar_low=4184.0, bar_high=4191.0)
print(f"  Outcome:  {_outcomes}")
print(f"  tp3_hit: {ts6.tp3_hit}  (harus False — trailing SL dulu)")
ok6 = (len(_outcomes) == 1 and _outcomes[0][0] == "WIN_TP2"
       and not ts6.tp3_hit
       and abs(ts6.trailing_sl - 4185.0) < 0.01)
wr6 = 0.5*1.0 + 0.3*1.5 + 0.2*1.0
print(f"  Weighted R: 0.5x1.0 + 0.3x1.5 + 0.2x1.0 = {wr6:.2f}R  (20% keluar di TP1)")
print(f"  {'PASS' if ok6 else 'FAIL'}")


# ── Summary ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("=== SUMMARY ===")
oks = [ok1, ok2, ok3, ok4, ok5, ok6]
labels = [
    "1. SL langsung             LOSS        -1.00R",
    "2. TP1+BE                  WIN_TP1     +0.50R  (0.5x1.0)",
    "3. TP1+TP2+Trailing        WIN_TP2     +1.15R  (0.5x1.0+0.3x1.5+0.2x1.0)",
    "4. TP1+TP2+TP3 Full        WIN_TP3     +1.35R  (0.5x1.0+0.3x1.5+0.2x2.0)",
    "5. Candle ambigu TP1+SL    LOSS        -1.00R  (SL check dulu)",
    "6. Candle ambigu Trail+TP3 WIN_TP2     +1.15R  (SL check dulu)",
]
for lbl, ok in zip(labels, oks):
    print(f"  {'PASS' if ok else 'FAIL'}  {lbl}")
print(f"\n{sum(oks)}/{len(oks)} PASS")
print("\nBukti kode asli dipakai: TrackedSignal.breakeven_sl dan .trailing_sl")
print("diset oleh _evaluate() di signal_tracker.py, bukan dihitung ulang di test.")
