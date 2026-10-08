"""Test unit untuk penyempurnaan Tracker:
1. Persistensi BE & trailing saat restart bot (add_signal memulihkan status)
2. Arah Breakeven SELL: entry - spread (mengamankan spread)
3. Pencatatan outcome_price pada level rencana (bukan sekadar tick observasi)
4. Deteksi rollover (spread >= 3.0 atau jam pergantian hari)
5. Kalkulasi MAE & MFE dalam satuan ATR
6. Observasi 12-bar M5 pasca-SL (mendeteksi jika harga akhirnya sentuh TP1)
"""
import sys, os
sys.path.insert(0, r"D:\BOT SKRIPSI 2")
os.environ["PYTHONIOENCODING"] = "utf-8"

from datetime import datetime, timedelta
import unittest.mock as mock
import threading

import src.infra.signal_tracker as tracker_mod
from src.infra.signal_tracker import TrackedSignal
from src.utils.time_utils import TZ_WIB

print("=== TEST TRACKER ADVANCED (BE PERSIST, MAE/MFE, POST-SL, ROLLOVER) ===\n")

# Mock logger
mock_logger = mock.MagicMock()
tracker_inst = object.__new__(tracker_mod.SignalTracker)
tracker_inst._logger = mock_logger
tracker_inst._notify = lambda msg: None
tracker_inst._refresh_report = None
tracker_inst._startup_signal_ids = set()
tracker_inst._lock = threading.Lock()
tracker_inst._active = {}
tracker_inst._post_sl_active = {}
tracker_inst._poll_interval = 10

# -------------------------------------------------------------
# Test 1: Persistensi status saat restart (add_signal restore BE & Trail)
# -------------------------------------------------------------
rec_saved = {
    "signal_id": "XAUUSD_M15_20261008_100000",
    "symbol": "XAUUSD",
    "timeframe": "M15",
    "direction": "BUY",
    "entry": 4120.0,
    "entry_low": 4119.5,
    "entry_high": 4120.5,
    "sl": 4110.0,
    "tp1": 4130.0,
    "tp2": 4140.0,
    "tp3": 4150.0,
    "timestamp": "2026-10-08T10:00:00",
    "atr_value": 8.0,
    "sl_source": "atr_far_swing",
    "entry_spread": 0.35,
    "tp1_hit": True,
    "breakeven_sl": 4120.35,
    "trailing_sl": 4130.0,
    "min_price_seen": 4115.0,
    "max_price_seen": 4135.0,
    "crossed_rollover": True,
}

tracker_inst.add_signal(rec_saved)
ts_restored = tracker_inst._active["XAUUSD_M15_20261008_100000"]

ok1 = (
    ts_restored.tp1_hit is True
    and abs(ts_restored.breakeven_sl - 4120.35) < 0.001
    and abs(ts_restored.trailing_sl - 4130.0) < 0.001
    and ts_restored.sl_source == "atr_far_swing"
    and abs(ts_restored.spread - 0.35) < 0.001
    and ts_restored.crossed_rollover is True
    and abs(ts_restored.min_price_seen - 4115.0) < 0.001
    and abs(ts_restored.max_price_seen - 4135.0) < 0.001
)
print(f"Test 1: Restore state BE/Trailing/Rollover dari restart:")
print(f"  tp1_hit={ts_restored.tp1_hit}, BE={ts_restored.breakeven_sl}, Trail={ts_restored.trailing_sl}, sl_src={ts_restored.sl_source} -> {'PASS' if ok1 else 'FAIL'}")

# -------------------------------------------------------------
# Test 2: Arah BE untuk SELL: entry - spread (mengamankan spread)
# -------------------------------------------------------------
ts_sell = TrackedSignal(
    signal_id="XAUUSD_H1_SELL_01",
    symbol="XAUUSD",
    direction="SELL",
    entry=4200.0,
    entry_low=4199.5,
    entry_high=4200.5,
    sl=4215.0,
    tp1=4185.0,
    tp2=4170.0,
    tp3=4155.0,
    start_time=datetime.now(tz=TZ_WIB),
    atr_value=10.0,
    spread=0.30,
    timeframe="H1",
    entry_zone_hit=True,
)
tracker_inst._evaluate(ts_sell, bid=4190.0, ask=4190.30) # profit +10pt >= 50% TP1 (7.5pt)
ok2 = ts_sell.breakeven_sl is not None and abs(ts_sell.breakeven_sl - (4200.0 - 0.30)) < 0.001
print(f"\nTest 2: Arah BE untuk SELL (entry - spread):")
print(f"  entry={ts_sell.entry}, spread={ts_sell.spread} -> BE={ts_sell.breakeven_sl} (expected 4199.70) -> {'PASS' if ok2 else 'FAIL'}")

# -------------------------------------------------------------
# Test 3: Outcome price dicatat pada level rencana (SL/TP struktural)
# -------------------------------------------------------------
outcomes_logged = []
def fake_update_outcome(sid, outcome, price=0.0, notes="", duration_m=0, **kwargs):
    outcomes_logged.append({
        "sid": sid, "outcome": outcome, "price": price, "notes": notes, "kwargs": kwargs
    })

mock_logger.update_outcome = fake_update_outcome

# Case A: Sinyal single-TP atau reversal ke BE setelah TP1 kena
# Set tp2=None agar resolve langsung di TP1
ts_sell.tp2 = None
ts_sell.tp3 = None
tracker_inst._evaluate(ts_sell, bid=4184.0, ask=4184.20)
# Tunggu thread _save_async selesai
import time
time.sleep(0.1)

last_call = outcomes_logged[-1] if outcomes_logged else {}
ok3 = last_call.get("outcome") == "WIN_TP1" and abs(last_call.get("price") - 4185.0) < 0.001
print(f"\nTest 3: Planned level exit (bukan sekadar harga tick observasi):")
print(f"  outcome={last_call.get('outcome')}, planned_price={last_call.get('price')} (obs tick=4184.20) -> {'PASS' if ok3 else 'FAIL'}")

# -------------------------------------------------------------
# Test 4: Kalkulasi MAE & MFE dalam satuan ATR
# -------------------------------------------------------------
# Untuk SELL ts_sell: entry=4200.0, atr=10.0
# Selama trade: harga naik ke ask=4200.30 (adverse move ~0.30pt)
# Dan turun ke bid=4184.0 (favorable move = 16.0pt -> MFE = 16.0/10 = 1.60R)
kw = last_call.get("kwargs", {})
mae = kw.get("mae_atr", 0.0)
mfe = kw.get("mfe_atr", 0.0)
ok4 = abs(mfe - 1.60) < 0.05
print(f"\nTest 4: MAE & MFE dalam satuan ATR:")
print(f"  MAE={mae}xATR, MFE={mfe}xATR (expected 1.60) -> {'PASS' if ok4 else 'FAIL'}")

# -------------------------------------------------------------
# Test 5: Deteksi Rollover saat spread melonjak >= 3.0 pt
# -------------------------------------------------------------
ts_roll = TrackedSignal(
    signal_id="XAUUSD_M5_ROLL_01",
    symbol="XAUUSD",
    direction="BUY",
    entry=4120.0,
    entry_low=4119.5,
    entry_high=4120.5,
    sl=4115.0,
    tp1=4125.0,
    tp2=4130.0,
    tp3=4135.0,
    start_time=datetime.now(tz=TZ_WIB),
    atr_value=5.0,
    entry_zone_hit=True,
)
tracker_inst._evaluate(ts_roll, bid=4120.0, ask=4124.5) # spread = 4.5 pt >= 3.0 pt
ok5 = ts_roll.crossed_rollover is True
print(f"\nTest 5: Deteksi lonjakan spread rollover (spread >= 3.0 pt):")
print(f"  crossed_rollover={ts_roll.crossed_rollover} -> {'PASS' if ok5 else 'FAIL'}")

# -------------------------------------------------------------
# Test 6: Observasi 12-bar M5 pasca-SL (mendeteksi jika harga akhirnya capai TP1)
# -------------------------------------------------------------
post_sl_hits = []
mock_logger.update_post_sl_hit = lambda sid, hit: post_sl_hits.append((sid, hit))

ts_loss = TrackedSignal(
    signal_id="XAUUSD_M5_LOSS_01",
    symbol="XAUUSD",
    direction="BUY",
    entry=4150.0,
    entry_low=4149.5,
    entry_high=4150.5,
    sl=4145.0,
    tp1=4160.0,
    tp2=4165.0,
    tp3=4170.0,
    start_time=datetime.now(tz=TZ_WIB),
    atr_value=5.0,
    entry_zone_hit=True,
)
# Step A: Kena SL
tracker_inst._evaluate(ts_loss, bid=4144.5, ask=4144.8)
ok6_sl = ts_loss.resolved and "XAUUSD_M5_LOSS_01" in tracker_inst._post_sl_active

# Step B: Dalam 12 bar M5, harga berbalik rally ke 4160.5 (menyentuh TP1 4160.0)
prices_cache = {"XAUUSD": (4161.0, 4161.3)}
tracker_inst._check_post_sl(prices_cache, datetime.now(tz=TZ_WIB))
ok6_tp = len(post_sl_hits) > 0 and post_sl_hits[-1] == ("XAUUSD_M5_LOSS_01", True)

ok6 = ok6_sl and ok6_tp
print(f"\nTest 6: Post-SL 12-bar M5 observation:")
print(f"  Active in post-SL queue: {ok6_sl}")
print(f"  Detected reaching TP1 after SL: {ok6_tp} (hits={post_sl_hits}) -> {'PASS' if ok6 else 'FAIL'}")

# Summary
all_oks = [ok1, ok2, ok3, ok4, ok5, ok6]
print("\n" + "="*65)
print(f"TOTAL RESULT: {sum(all_oks)}/{len(all_oks)} PASS")
print("="*65)
sys.exit(0 if all(all_oks) else 1)
