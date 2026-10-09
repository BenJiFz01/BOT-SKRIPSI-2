"""Comprehensive test for SL OOB mode: reject vs atr_fallback in BUY & SELL."""
import sys, os
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

import pandas as pd
from src.risk import sl_tp

print("=================================================================")
print("TEST COMPREHENSIVE: SL_OOB_MODE (reject vs atr_fallback)")
print("=================================================================\n")

def make_test_df(swing_type: str):
    """
    Buat df 60 bar dengan swing khusus di bar 30:
    - 'far_low': pivot low di 4155 (jauh dari entry 4195, dist ~41.2pt > max 8.0pt)
    - 'far_high': pivot high di 4245 (jauh dari entry 4205, dist ~41.2pt > max 8.0pt)
    - 'normal_low': pivot low di 4190 (dekat entry 4195, dist ~6.2pt < max 8.0pt)
    - 'tight_low': pivot low di 4194.8 (sangat dekat, dist ~0.5pt < min 0.90pt)
    """
    if swing_type == 'far_low':
        lows = [4192.0] * 60
        lows[27:34] = [4165.0, 4160.0, 4158.0, 4155.0, 4158.0, 4160.0, 4165.0]
        highs = [l + 6.0 for l in lows]
        return pd.DataFrame({"high": highs, "low": lows, "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [4.0]*60})
    elif swing_type == 'far_high':
        highs = [4208.0] * 60
        highs[27:34] = [4235.0, 4240.0, 4242.0, 4245.0, 4242.0, 4240.0, 4235.0]
        lows = [h - 6.0 for h in highs]
        return pd.DataFrame({"high": highs, "low": lows, "close": [4205.0]*60, "open": [4205.0]*60, "atr_14": [4.0]*60})
    elif swing_type == 'normal_low':
        lows = [4194.0] * 60
        lows[27:34] = [4192.0, 4191.0, 4190.5, 4190.0, 4190.5, 4191.0, 4192.0]
        highs = [l + 6.0 for l in lows]
        return pd.DataFrame({"high": highs, "low": lows, "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [4.0]*60})

# Helper untuk memaksa cfg oob_mode di cache
def run_plan(direction, price, atr, mode, df):
    # Buat custom config tuple dengan mode yang diinginkan
    from src.config.settings import load_settings
    s = load_settings()
    custom_cfg = sl_tp._AtrSlConfig(
        atr_len=s.scalping_atr_len,
        sl_atr_mult=1.2,
        sl_buffer_atr=0.3,
        min_spread_mult=3.0,
        max_atr_mult=2.0,
        oob_mode=mode,
        sl_min_points=0.0,
        tp1_rr=1.0,
        tp2_rr=1.5,
        tp3_rr=2.0,
        close_pct=(0.5, 0.3, 0.2),
    )
    sl_tp._CACHE_SCALPING = custom_cfg
    return sl_tp.calc_sltp(direction, price, atr=atr, spread=0.30, is_scalping=True, df=df)

# Skenario 1: BUY Swing Jauh (mode reject vs atr_fallback)
print("--- SKENARIO 1: BUY | Entry=4195.0, ATR=4.0, max_sl=2.0x4=8.0pt, Swing low=4155.0 ---")
df_far_buy = make_test_df('far_low')

p_rej = run_plan("BUY", 4195.0, 4.0, "reject", df_far_buy)
print(f"[Mode 'reject']:")
print(f"  reject_reason : {p_rej.reject_reason}")
print(f"  sl_dist       : {p_rej.sl_dist:.2f}pt")
print(f"  sl_source     : {p_rej.sl_source}")

p_fall = run_plan("BUY", 4195.0, 4.0, "atr_fallback", df_far_buy)
print(f"[Mode 'atr_fallback']:")
print(f"  reject_reason : '{p_fall.reject_reason}' (lolos)")
print(f"  sl_source     : {p_fall.sl_source}")
print(f"  sl_dist       : {p_fall.sl_dist:.2f}pt (1.2 x 4.0 = 4.8pt)")
print(f"  SL            : {p_fall.sl:.2f} (Entry 4195.0 - 4.8 = 4190.20)")
print(f"  TP1           : {p_fall.tp1:.2f} (Entry 4195.0 + 1.0*4.8 = 4199.80)")
print(f"  TP2           : {p_fall.tp2:.2f} (Entry 4195.0 + 1.5*4.8 = 4202.20)")
print(f"  TP3           : {p_fall.tp3:.2f} (Entry 4195.0 + 2.0*4.8 = 4204.60)")
print(f"  method        : {p_fall.method}\n")

# Skenario 2: SELL Swing Jauh (mode reject vs atr_fallback)
print("--- SKENARIO 2: SELL | Entry=4205.0, ATR=4.0, max_sl=2.0x4=8.0pt, Swing high=4245.0 ---")
df_far_sell = make_test_df('far_high')

p_rej_s = run_plan("SELL", 4205.0, 4.0, "reject", df_far_sell)
print(f"[Mode 'reject']:")
print(f"  reject_reason : {p_rej_s.reject_reason}")
print(f"  sl_dist       : {p_rej_s.sl_dist:.2f}pt")
print(f"  sl_source     : {p_rej_s.sl_source}")

p_fall_s = run_plan("SELL", 4205.0, 4.0, "atr_fallback", df_far_sell)
print(f"[Mode 'atr_fallback']:")
print(f"  reject_reason : '{p_fall_s.reject_reason}' (lolos)")
print(f"  sl_source     : {p_fall_s.sl_source}")
print(f"  sl_dist       : {p_fall_s.sl_dist:.2f}pt (1.2 x 4.0 = 4.8pt)")
print(f"  SL            : {p_fall_s.sl:.2f} (Entry 4205.0 + 4.8 = 4209.80)")
print(f"  TP1           : {p_fall_s.tp1:.2f} (Entry 4205.0 - 1.0*4.8 = 4200.20)")
print(f"  TP2           : {p_fall_s.tp2:.2f} (Entry 4205.0 - 1.5*4.8 = 4197.80)")
print(f"  TP3           : {p_fall_s.tp3:.2f} (Entry 4205.0 - 2.0*4.8 = 4195.40)")
print(f"  method        : {p_fall_s.method}\n")

# Skenario 3: SL_TOO_TIGHT tetap menolak (tidak tertukar dengan OOB fallback)
print("--- SKENARIO 3: sl_dist < sl_min (0.90pt) tetap REJECT SL_TOO_TIGHT di kedua mode ---")
# ATR 0.5 -> sl_dist = 1.2*0.5 = 0.60pt < 0.90pt
p_tight_rej  = run_plan("BUY", 4195.0, 0.5, "reject", None)
p_tight_fall = run_plan("BUY", 4195.0, 0.5, "atr_fallback", None)
print(f"  Mode reject       -> reason: {p_tight_rej.reject_reason}")
print(f"  Mode atr_fallback -> reason: {p_tight_fall.reject_reason} (TETAP REJECT, TIDAK DILONGGARKAN)\n")

# Skenario 4: Swing Normal dalam batas (sl_dist <= sl_max)
print("--- SKENARIO 4: Swing normal dalam batas (sl_dist <= sl_max) ---")
df_norm = make_test_df('normal_low')
p_norm = run_plan("BUY", 4195.0, 4.0, "atr_fallback", df_norm)
print(f"  sl_source : {p_norm.sl_source} (bukan atr_far_swing, karena swing valid)")
print(f"  sl_dist   : {p_norm.sl_dist:.2f}pt")
print(f"  SL        : {p_norm.sl:.2f}")

print("\n=================================================================")
print("HASIL VERIFIKASI:")
v1 = p_rej.reject_reason.startswith("SL_OUT_OF_BOUNDS")
v2 = p_fall.reject_reason == "" and p_fall.sl_source == "atr_far_swing" and abs(p_fall.sl_dist - 4.8) < 0.01
v3 = p_rej_s.reject_reason.startswith("SL_OUT_OF_BOUNDS")
v4 = p_fall_s.reject_reason == "" and p_fall.sl_source == "atr_far_swing" and abs(p_fall.sl_dist - 4.8) < 0.01
v5 = p_tight_fall.reject_reason == "SL_TOO_TIGHT"
v6 = p_norm.sl_source == "swing+atr"
all_ok = v1 and v2 and v3 and v4 and v5 and v6
print(f"  1. BUY reject mode           : {'PASS' if v1 else 'FAIL'}")
print(f"  2. BUY atr_fallback mode     : {'PASS' if v2 else 'FAIL'}")
print(f"  3. SELL reject mode          : {'PASS' if v3 else 'FAIL'}")
print(f"  4. SELL atr_fallback mode    : {'PASS' if v4 else 'FAIL'}")
print(f"  5. SL_TOO_TIGHT guard intact : {'PASS' if v5 else 'FAIL'}")
print(f"  6. Normal swing uses swing   : {'PASS' if v6 else 'FAIL'}")
print(f"ALL CHECKS: {'PASS' if all_ok else 'FAIL'}")
print("=================================================================")
