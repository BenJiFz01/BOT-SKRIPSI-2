"""engine — Rule-Based DSS trading engine.

anytf_mta_engine — Orchestrator 5-gate (evaluate_any_tf_mta + scan_setup_plan).
Implementasi tiap gate dipecah ke submodul: bias, state, trigger, confluence,
setup_plan, cooldown, utils.
"""

from src.engine.anytf_mta_engine import evaluate_any_tf_mta, scan_setup_plan

__all__ = [
    "evaluate_any_tf_mta",
    "scan_setup_plan",
]
