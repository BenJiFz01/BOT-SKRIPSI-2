"""engine — Rule-Based DSS trading engine.

Modul:
  helpers    — ATR proxy, calc_rr, market condition, utilitas
  bias       — Deteksi HTF bias dan voting multi-TF
  trigger    — Trigger Score Layer-1 dan validasi counter trend
  confluence — Confluence Score Layer-2
  setup_plan — Scan setup plan antisipasi entry
  evaluator  — Gate utama evaluasi sinyal live (5 gate)
"""
from src.engine.evaluator  import evaluate_any_tf_mta
from src.engine.setup_plan import scan_setup_plan
from src.engine.helpers    import calc_rr, detect_market_condition

__all__ = ["evaluate_any_tf_mta", "scan_setup_plan", "calc_rr", "detect_market_condition"]
