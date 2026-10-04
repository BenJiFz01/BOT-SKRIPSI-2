"""Test SL_TOO_TIGHT rejection (sl_dist < spread x min_spread_mult)."""
import sys
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

import pandas as pd
from src.risk.sl_tp import calc_sltp

print("=== TEST SL_TOO_TIGHT REJECTION ===\n")

# Config: scalping min_spread_mult = 3.0, spread = 0.30
# Min SL = 0.30 x 3.0 = 0.90pt

entry = 4180.0
spread = 0.30
atr = 0.5  # ATR kecil untuk trigger tight SL

print(f"Setup: Entry={entry}, spread={spread}, min_spread_mult=3.0")
print(f"Min SL distance = {spread} x 3.0 = {spread * 3.0:.2f}pt\n")

# Test 1: SL terlalu tight (sl_dist < min)
print("Test 1: ATR=0.5, sl_mult=1.2 -> sl_dist=0.6pt < 0.9pt (REJECT)")
plan1 = calc_sltp("BUY", entry, atr=0.5, spread=spread, is_scalping=True, df=None)
if plan1 and plan1.reject_reason == "SL_TOO_TIGHT":
    print(f"  Reject: {plan1.reject_reason}")
    print(f"  sl_dist: {plan1.sl_dist:.2f}pt")
    print(f"  PASS\n")
elif plan1:
    print(f"  FAIL: Not rejected, sl_dist={plan1.sl_dist:.2f}pt\n")
else:
    print(f"  FAIL: plan=None\n")

# Test 2: SL cukup (sl_dist >= min)
print("Test 2: ATR=1.0, sl_mult=1.2 -> sl_dist=1.2pt >= 0.9pt (ACCEPT)")
plan2 = calc_sltp("BUY", entry, atr=1.0, spread=spread, is_scalping=True, df=None)
if plan2 and not plan2.reject_reason:
    print(f"  Accept: sl_dist={plan2.sl_dist:.2f}pt")
    print(f"  SL={plan2.sl:.2f}, TP1={plan2.tp1:.2f}")
    print(f"  PASS\n")
elif plan2 and plan2.reject_reason:
    print(f"  FAIL: Rejected dengan {plan2.reject_reason}\n")
else:
    print(f"  FAIL: plan=None\n")

# Test 3: Sedikit di atas threshold (sl_dist > min, ACCEPT)
print("Test 3: ATR=0.8, sl_mult=1.2 -> sl_dist=0.96pt > 0.9pt (ACCEPT)")
plan3 = calc_sltp("BUY", entry, atr=0.8, spread=spread, is_scalping=True, df=None)
if plan3 and not plan3.reject_reason:
    print(f"  Accept: sl_dist={plan3.sl_dist:.2f}pt")
    print(f"  PASS\n")
elif plan3 and plan3.reject_reason:
    print(f"  FAIL: Rejected dengan {plan3.reject_reason}, sl_dist={plan3.sl_dist:.2f}pt\n")
else:
    print(f"  FAIL: plan=None\n")

# Test 4: Intraday (min_spread_mult=5.0, min=1.5pt)
print("Test 4: Intraday min_spread_mult=5.0 -> min=1.5pt")
print("  ATR=1.0, sl_mult=1.5 -> sl_dist=1.5pt == 1.5pt (ACCEPT)")
plan4 = calc_sltp("BUY", entry, atr=1.0, spread=spread, is_scalping=False, df=None)
if plan4 and not plan4.reject_reason:
    print(f"  Accept: sl_dist={plan4.sl_dist:.2f}pt")
    print(f"  PASS\n")
elif plan4 and plan4.reject_reason:
    print(f"  FAIL: Rejected dengan {plan4.reject_reason}\n")
else:
    print(f"  FAIL: plan=None\n")

# Test 5: SELL symmetri
print("Test 5: SELL ATR=0.5 -> sl_dist=0.6pt < 0.9pt (REJECT)")
plan5 = calc_sltp("SELL", entry, atr=0.5, spread=spread, is_scalping=True, df=None)
if plan5 and plan5.reject_reason == "SL_TOO_TIGHT":
    print(f"  Reject: {plan5.reject_reason}")
    print(f"  sl_dist: {plan5.sl_dist:.2f}pt")
    print(f"  PASS\n")
elif plan5:
    print(f"  FAIL: Not rejected\n")
else:
    print(f"  FAIL: plan=None\n")

print("=== SUMMARY ===")
print("SL_TOO_TIGHT rejection (sl_dist < spread x min_spread_mult):")
print("1. Scalping min=0.9pt, ATR 0.5 -> 0.6pt: REJECT")
print("2. Scalping min=0.9pt, ATR 1.0 -> 1.2pt: ACCEPT")
print("3. Scalping slightly above threshold 0.96pt: ACCEPT")
print("4. Intraday min=1.5pt, ATR 1.0 -> 1.5pt: ACCEPT")
print("5. SELL symmetri: REJECT")
