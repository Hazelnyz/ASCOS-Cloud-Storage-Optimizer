"""
ml/inference/policy.py

ML_SCHEMA Sec5 Step 2 -- candidate tier generation from p_access, using
POLICY_MARGIN from ml.config (single source of truth, untouched). Pure
function, no AWS calls, no randomness -- deterministic given p_access
and margin.

Only reached if protected_gate.check_hard_gate() said "proceed" -- this
module deliberately does not itself check protected_flag (Sec37:
policy != storage execution, and the hard gate is a separate, prior
concern per Sec5 Step 1).
"""

from __future__ import annotations

from ml.config import POLICY_MARGIN


def generate_candidate_tiers(p_access: float, margin: float = POLICY_MARGIN) -> list[str]:
    """
    Generate candidate storage tiers from p_access probability.

    Uses a margin around the 0.7/0.3 decision points to create
    multi-tier candidate sets where the model is uncertain.

    Args:
        p_access: Predicted access probability (0.0 to 1.0)
        margin: Decision margin (default 0.1 from config)

    Returns:
        List of candidate tier strings (e.g., ["HOT", "WARM"])
    """
    if not 0.0 <= p_access <= 1.0:
        raise ValueError(f"p_access must be in [0, 1], got {p_access}")

    # Round band edges to avoid float precision issues at boundaries
    hot_upper = round(0.7 + margin, 10)  # 0.8
    hot_lower = round(0.7 - margin, 10)  # 0.6
    cold_upper = round(0.3 + margin, 10)  # 0.4
    cold_lower = round(0.3 - margin, 10)  # 0.2

    if p_access >= hot_upper:
        return ["HOT"]
    if p_access >= hot_lower:
        return ["HOT", "WARM"]
    if p_access >= cold_upper:
        return ["WARM"]
    if p_access >= cold_lower:
        return ["WARM", "COLD"]
    return ["COLD"]


def apply_cost_safety_constraint(chosen_tier: str, retrieval_cost_penalty_high: bool) -> str:
    """
    Sec5 Step 4 -- always applied AFTER the bandit, never inside it.
    if chosen tier is Cold AND retrieval_cost_penalty is high relative
    to storage saving -> downgrade to Warm instead (false-archive
    protection).
    """
    if chosen_tier == "COLD" and retrieval_cost_penalty_high:
        return "WARM"
    return chosen_tier
