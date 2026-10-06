"""Test format reject SL_OUT_OF_BOUNDS baru: grouping kategori + konteks terurai."""
import sys
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

import re
import pandas as pd
from src.risk.sl_tp import calc_sltp
from src.infra.reject_tracker import _categorize

print("=== TEST SL_OUT_OF_BOUNDS FORMAT BARU ===\n")

# Test 1: reason baru terurai ke kategori yang sama
raw_new = "SL_OUT_OF_BOUNDS(sl=7.3/max=11.1/atr=5.5/1.33x)"
cat = _categorize(raw_new)
ok1 = cat == "SL_OUT_OF_BOUNDS"
print(f"Test 1: _categorize('{raw_new}')")
print(f"  Got: {cat} -> {'PASS' if ok1 else 'FAIL'}")

# Test 2: reason bisa diurai regex untuk replay
pat = re.compile(r"SL_OUT_OF_BOUNDS\(sl=([\d.]+)/max=([\d.]+)/atr=([\d.]+)/([\d.]+)x\)")
m = pat.search(raw_new)
ok2 = m is not None and m.groups() == ("7.3", "11.1", "5.5", "1.33")
print(f"\nTest 2: regex replay")
print(f"  Groups: {m.groups() if m else None} -> {'PASS' if ok2 else 'FAIL'}")

# Test 3: calc_sltp BUY menghasilkan reason format baru + sl_source terisi
# Lembah strict di bar 30 (4155 < semua 3 bar kiri-kanan), entry 4195
# sl_dist = 4195 - (4155 - 0.3*4) = 41.2pt > max 8pt -> reject
lows = [4192.0] * 60
lows[27], lows[28], lows[29], lows[30], lows[31], lows[32], lows[33] = 4165.0, 4160.0, 4158.0, 4155.0, 4158.0, 4160.0, 4165.0
highs = [l + 6.0 for l in lows]
df = pd.DataFrame({
    "high": highs,
    "low": lows,
    "close": [4195.0] * 60,
    "open": [4195.0] * 60,
    "atr_14": [4.0] * 60,
})
plan = calc_sltp("BUY", 4195.0, atr=4.0, spread=0.30, is_scalping=True, df=df)
ok3 = plan is not None and plan.reject_reason.startswith("SL_OUT_OF_BOUNDS(sl=") and plan.sl_source == "swing+atr"
print(f"\nTest 3: BUY swing jauh -> reject berkonteks")
print(f"  reason: {plan.reject_reason if plan else None}")
print(f"  sl_source: {plan.sl_source if plan else None} -> {'PASS' if ok3 else 'FAIL'}")

# Test 4: SELL simetris (puncak strict di bar 30: 4245, entry 4205)
highs_s = [4208.0] * 60
highs_s[27], highs_s[28], highs_s[29], highs_s[30], highs_s[31], highs_s[32], highs_s[33] = 4235.0, 4240.0, 4242.0, 4245.0, 4242.0, 4240.0, 4235.0
lows_s = [h - 6.0 for h in highs_s]
df_s = pd.DataFrame({
    "high": highs_s,
    "low": lows_s,
    "close": [4205.0] * 60,
    "open": [4205.0] * 60,
    "atr_14": [4.0] * 60,
})
plan_s = calc_sltp("SELL", 4205.0, atr=4.0, spread=0.30, is_scalping=True, df=df_s)
ok4 = plan_s is not None and plan_s.reject_reason.startswith("SL_OUT_OF_BOUNDS(sl=") and plan_s.sl_source == "swing+atr"
print(f"\nTest 4: SELL swing jauh -> reject berkonteks")
print(f"  reason: {plan_s.reject_reason if plan_s else None}")
print(f"  sl_source: {plan_s.sl_source if plan_s else None} -> {'PASS' if ok4 else 'FAIL'}")

oks = [ok1, ok2, ok3, ok4]
print(f"\n{sum(oks)}/{len(oks)} PASS")
sys.exit(0 if all(oks) else 1)
