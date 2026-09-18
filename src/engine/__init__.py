"""engine — Rule-Based DSS trading engine.

Modul aktif:
  anytf_mta_engine — Engine utama 5-gate (evaluate_any_tf_mta + scan_setup_plan)

Modul lain (tersedia tapi tidak aktif di main loop):
  evaluator, classifier, bias, trigger, confluence, analysis_core, helpers
"""

from src.engine.anytf_mta_engine import evaluate_any_tf_mta, scan_setup_plan

__all__ = [
    "evaluate_any_tf_mta",
    "scan_setup_plan",
]
