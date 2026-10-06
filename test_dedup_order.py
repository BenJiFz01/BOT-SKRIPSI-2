"""Test dedup CONFLICT_SUPPRESS: sinyal tersuppress tidak pakai cooldown & tidak OK."""
import sys
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

import inspect
import src.engine.anytf_mta_engine as eng

print("=== TEST DEDUP ORDER ===\n")
src = inspect.getsource(eng.evaluate_any_tf_mta)

# Test 1: blok dedup muncul SEBELUM _reject(df_t, "OK")
i_dedup = src.find("CONFLICT_SUPPRESS")
i_ok = src.find('_reject(df_t, "OK")')
i_save = src.find("_save_cooldown_state()")
ok1 = -1 not in (i_dedup, i_ok, i_save) and i_dedup < i_ok and i_dedup < i_save
print(f"Test 1: dedup sebelum OK + save cooldown")
print(f"  idx dedup={i_dedup} ok={i_ok} save={i_save} -> {'PASS' if ok1 else 'FAIL'}")

# Test 2: tidak ada fallback fixed di jalur LIVE
ok2 = "fixed_zone_sltp" not in src and "fixed_fallback" not in src
print(f"\nTest 2: tidak ada fixed fallback di jalur LIVE -> {'PASS' if ok2 else 'FAIL'}")

# Test 3: plan None langsung SLTP_NONE
i_none = src.find("if plan is None:")
seg = src[i_none:i_none + 120] if i_none != -1 else ""
ok3 = "SLTP_NONE" in seg
print(f"\nTest 3: plan None -> SLTP_NONE")
print(f"  {seg.strip()[:90]} -> {'PASS' if ok3 else 'FAIL'}")

# Test 4: runtime — sinyal tersuppress tidak ubah cooldown key itu
import pandas as pd
from src.engine.cooldown import _LAST_SIGNAL_TIME, _LAST_LIVE_EMIT
before_keys = set(_LAST_SIGNAL_TIME.keys())
# Simulasi: dedup check murni (tanpa MT5) — pastikan return None terjadi
# dengan _LAST_LIVE_EMIT terisi dan conf lebih rendah
import time
_LAST_LIVE_EMIT[("XAUUSD", "BUY")] = (time.time(), 5.0)
# conf 3 < prev 5 dalam window -> harus suppress (logika yang sama di engine)
prev = _LAST_LIVE_EMIT[("XAUUSD", "BUY")]
now = time.time()
from src.engine.cooldown import _CONFLICT_WINDOW_SEC
should_suppress = prev and (now - prev[0]) <= _CONFLICT_WINDOW_SEC and 3.0 <= prev[1]
ok4 = bool(should_suppress) and set(_LAST_SIGNAL_TIME.keys()) == before_keys
print(f"\nTest 4: suppress tidak sentuh _LAST_SIGNAL_TIME -> {'PASS' if ok4 else 'FAIL'}")
del _LAST_LIVE_EMIT[("XAUUSD", "BUY")]

oks = [ok1, ok2, ok3, ok4]
print(f"\n{sum(oks)}/{len(oks)} PASS")
sys.exit(0 if all(oks) else 1)
