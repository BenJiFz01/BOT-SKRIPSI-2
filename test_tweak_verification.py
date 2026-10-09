"""Test suite for SL_MIN_POINTS, OOB fallback ordering, swing_ratio_before_fallback, and tracker restore."""
import sys, os
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

import pandas as pd
from src.risk import sl_tp
from src.config import settings

def make_test_df(swing_type: str):
    if swing_type == 'near_low': # swing dekat di 4192.5 (dist ~2.5pt < 5.0pt)
        lows = [4194.0]*60; lows[27:34] = [4193.5, 4193.0, 4192.5, 4192.0, 4192.5, 4193.0, 4193.5]
        return pd.DataFrame({"high": [l+4.0 for l in lows], "low": lows, "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [3.0]*60})
    elif swing_type == 'near_high': # swing dekat di 4197.5 (dist ~2.5pt < 5.0pt)
        highs = [4196.0]*60; highs[27:34] = [4196.5, 4197.0, 4197.5, 4198.0, 4197.5, 4197.0, 4196.5]
        return pd.DataFrame({"high": highs, "low": [h-4.0 for h in highs], "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [3.0]*60})
    elif swing_type == 'far_low_40': # swing low di 4155.0 (dist ~40.9pt > max)
        lows = [4192.0]*60; lows[27:34] = [4165.0, 4160.0, 4158.0, 4155.0, 4158.0, 4160.0, 4165.0]
        return pd.DataFrame({"high": [l+6.0 for l in lows], "low": lows, "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [3.0]*60})
    elif swing_type == 'far_high_40': # swing high di 4235.0 (dist ~40.9pt > max)
        highs = [4198.0]*60; highs[27:34] = [4225.0, 4230.0, 4232.0, 4235.0, 4232.0, 4230.0, 4225.0]
        return pd.DataFrame({"high": highs, "low": [h-6.0 for h in highs], "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [3.0]*60})
    elif swing_type == 'normal_low': # swing low valid dalam batas (dist ~5.5pt)
        lows = [4194.0]*60; lows[27:34] = [4192.0, 4191.0, 4190.5, 4190.0, 4190.5, 4191.0, 4192.0]
        return pd.DataFrame({"high": [l+6.0 for l in lows], "low": lows, "close": [4195.0]*60, "open": [4195.0]*60, "atr_14": [4.0]*60})

def run_scalp(direction, price, atr, sl_min_pts=5.0, oob="atr_fallback", df=None):
    sl_tp._CACHE_SCALPING = sl_tp._AtrSlConfig(
        atr_len=14, sl_atr_mult=1.2, sl_buffer_atr=0.3,
        min_spread_mult=3.0, max_atr_mult=2.0, oob_mode=oob,
        sl_min_points=sl_min_pts, tp1_rr=1.0, tp2_rr=1.5, tp3_rr=2.0,
        close_pct=(0.5, 0.3, 0.2),
    )
    return sl_tp.calc_sltp(direction, price, atr=atr, spread=0.30, is_scalping=True, df=df)

def run_intra(direction, price, atr, df=None):
    sl_tp._CACHE_INTRADAY = sl_tp._AtrSlConfig(
        atr_len=14, sl_atr_mult=1.5, sl_buffer_atr=0.5,
        min_spread_mult=5.0, max_atr_mult=2.5, oob_mode="atr_fallback",
        sl_min_points=0.0, tp1_rr=1.0, tp2_rr=2.0, tp3_rr=3.0,
        close_pct=(0.4, 0.3, 0.3),
    )
    return sl_tp.calc_sltp(direction, price, atr=atr, spread=0.30, is_scalping=False, df=df)

# Test a: BUY dan SELL, ATR 3.0, swing dekat -> SL = 5.0 pt (batas minimum aktif). ATR 5.0 -> SL = 6.0 pt.
df_nl = make_test_df('near_low')
df_nh = make_test_df('near_high')

p_buy_3 = run_scalp("BUY", 4195.0, 3.0, 5.0, "atr_fallback", df_nl)
p_sell_3 = run_scalp("SELL", 4195.0, 3.0, 5.0, "atr_fallback", df_nh)
p_buy_5 = run_scalp("BUY", 4195.0, 5.0, 5.0, "atr_fallback", df_nl)
p_sell_5 = run_scalp("SELL", 4195.0, 5.0, 5.0, "atr_fallback", df_nh)

ok_a1 = abs(p_buy_3.sl_dist - 5.0) < 0.01 and abs(p_sell_3.sl_dist - 5.0) < 0.01
ok_a2 = abs(p_buy_5.sl_dist - 6.0) < 0.01 and abs(p_sell_5.sl_dist - 6.0) < 0.01
res_a = ok_a1 and ok_a2

# Test b: Swing jauh (40 pt), ATR 3.0: mode reject -> SL_OUT_OF_BOUNDS; mode atr_fallback -> lolos, SL 5.0, sumber atr_far_swing, swing_ratio_before_fallback > 0.
df_fl = make_test_df('far_low_40')
p_b_rej = run_scalp("BUY", 4195.0, 3.0, 5.0, "reject", df_fl)
p_b_fall = run_scalp("BUY", 4195.0, 3.0, 5.0, "atr_fallback", df_fl)

ok_b1 = p_b_rej.reject_reason.startswith("SL_OUT_OF_BOUNDS")
ok_b2 = (p_b_fall.reject_reason == "" and abs(p_b_fall.sl_dist - 5.0) < 0.01 and
         p_b_fall.sl_source == "atr_far_swing" and p_b_fall.swing_ratio_before_fallback > 0)
res_b = ok_b1 and ok_b2

# Test c: Swing normal (sl_dist <= sl_max) -> sumber swing+atr, swing_ratio_before_fallback = 0.
df_norm = make_test_df('normal_low')
p_c = run_scalp("BUY", 4195.0, 4.0, 5.0, "atr_fallback", df_norm)
res_c = p_c.sl_source == "swing+atr" and p_c.swing_ratio_before_fallback == 0.0 and p_c.reject_reason == ""

# Test d: Mode intraday -> tidak terpengaruh SL_MIN_POINTS (ATR 2.0 -> sl_dist = 1.5*2.0 = 3.0pt, bukan 5.0pt).
p_d = run_intra("BUY", 4195.0, 2.0, df=None)
res_d = p_d.reject_reason == "" and abs(p_d.sl_dist - 3.0) < 0.01

# Test e: Settings: SL_MIN_POINTS=7.0 dengan SCALPING_ATR_MIN_POINTS=3.0 harus ValueError.
res_e = False
try:
    os.environ["SL_MIN_POINTS"] = "7.0"
    os.environ["SCALPING_ATR_MIN_POINTS"] = "3.0"
    settings.load_settings()
except ValueError as ve:
    res_e = "SL_MIN_POINTS=7.00 melebihi batas maksimum" in str(ve)
finally:
    os.environ.pop("SL_MIN_POINTS", None)
    os.environ.pop("SCALPING_ATR_MIN_POINTS", None)

# Test review 1: swing 41.2 pt, ATR 4.0, mode atr_fallback -> swing_ratio_before_fallback ~ 10.3; swing normal -> 0
df_fl_4 = make_test_df('far_low_40') # entry 4195, low 4155 - 0.3*4(1.2) = 4153.8 -> sl_dist = 41.2 -> 41.2/4.0 = 10.3
p_rev1 = run_scalp("BUY", 4195.0, 4.0, 5.0, "atr_fallback", df_fl_4)
res_rev1 = abs(p_rev1.swing_ratio_before_fallback - 10.3) <= 0.05

# Test review 2: restore tracker recalculate BE (BUY & SELL) jika tp1_hit tapi breakeven_sl kosong
from src.infra import signal_tracker as st_mod
import unittest.mock as mock
import threading
from datetime import datetime
from src.utils.time_utils import TZ_WIB

tr = object.__new__(st_mod.SignalTracker)
tr._logger = mock.MagicMock()
tr._active = {}
tr._lock = threading.Lock()

# BUY
rec_buy = {
    "signal_id": "TEST_RESTORE_BUY", "symbol": "XAUUSD", "direction": "BUY",
    "entry": 4200.0, "sl": 4190.0, "tp1": 4210.0, "tp1_hit": True,
    "entry_spread": 0.30, "breakeven_sl": None,
}
tr.add_signal(rec_buy)
ts_b = tr._active["TEST_RESTORE_BUY"]
ok_r_buy = abs(ts_b.breakeven_sl - 4200.30) < 0.001

# SELL
rec_sell = {
    "signal_id": "TEST_RESTORE_SELL", "symbol": "XAUUSD", "direction": "SELL",
    "entry": 4200.0, "sl": 4210.0, "tp1": 4190.0, "tp1_hit": True,
    "entry_spread": 0.30, "breakeven_sl": None,
}
tr.add_signal(rec_sell)
ts_s = tr._active["TEST_RESTORE_SELL"]
ok_r_sell = abs(ts_s.breakeven_sl - 4199.70) < 0.001
res_rev2 = ok_r_buy and ok_r_sell

# Test review 3: signal_logger dummy signal + pandas verify columns at end
from src.infra.signal_logger import SignalLogger, CSV_FIELDS
from src.models.signal import Signal
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    cp = Path(td) / "dummy.csv"
    jp = Path(td) / "dummy.json"
    logger_test = SignalLogger(csv_path=cp, json_path=jp)
    sig_dummy = Signal(
        symbol="XAUUSD", tf="M5", direction="BUY", close_time="2026-10-08T10:00:00",
        signal_type="LIVE", signal_mode="CONTINUATION",
        entry=4150.0, sl=4145.0, tp=4155.0, tp2=4160.0, tp3=4165.0,
        sl_method="dynamic_atr", atr_value=4.0, sl_source="atr_far_swing",
        sl_oob_mode="atr_fallback", swing_ratio_before_fallback=10.3,
        cfg_tag="atrmin3.0|slmin5.0|oob=atr_fallback",
    )
    logger_test.log_signal(sig_dummy)
    df_read = pd.read_csv(cp)
    col_idx = {c: i for i, c in enumerate(df_read.columns)}
    # Pastikan kolom-kolom baru berada di ujung setelah notes
    notes_i = col_idx["notes"]
    ok_pos = (col_idx["sl_source"] > notes_i and col_idx["sl_oob_mode"] > notes_i and
              col_idx["swing_ratio_before_fallback"] > notes_i and col_idx["cfg_tag"] > notes_i)
    # Pastikan data terbaca benar
    val_oob = df_read["sl_oob_mode"].iloc[0] == "atr_fallback"
    val_sw  = abs(df_read["swing_ratio_before_fallback"].iloc[0] - 10.3) < 0.01
    val_tag = df_read["cfg_tag"].iloc[0] == "atrmin3.0|slmin5.0|oob=atr_fallback"
    res_rev3 = ok_pos and val_oob and val_sw and val_tag

print(f"Kasus a (SL_MIN_POINTS 5.0pt aktif vs ATR 5.0)  : {'PASS' if res_a else 'FAIL'}")
print(f"Kasus b (Swing jauh OOB reject vs fallback)     : {'PASS' if res_b else 'FAIL'}")
print(f"Kasus c (Swing normal ratio=0)                  : {'PASS' if res_c else 'FAIL'}")
print(f"Kasus d (Intraday tidak terpengaruh)            : {'PASS' if res_d else 'FAIL'}")
print(f"Kasus e (ValueError SL_MIN > max*atrmin)        : {'PASS' if res_e else 'FAIL'}")
print(f"Review 1 (swing 41.2pt ratio ~10.3)             : {'PASS' if res_rev1 else 'FAIL'}")
print(f"Review 2 (Restore BE recalculate BUY & SELL)    : {'PASS' if res_rev2 else 'FAIL'}")
print(f"Review 3 (CSV fields at end + pandas verify)    : {'PASS' if res_rev3 else 'FAIL'}")

all_checks = [res_a, res_b, res_c, res_d, res_e, res_rev1, res_rev2, res_rev3]
sys.exit(0 if all(all_checks) else 1)
