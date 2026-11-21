"""
ml/inference/bandit.py

ML_SCHEMA Sec5 Step 3 -- real contextual Thompson Sampling over the
candidate set policy.py produces (not a placeholder pick). Beta
distributions per context, persisted so learning survives across
invocations.

STATE STORAGE DECISION (documented, not silently guessed): reuses the
existing `user_baseline` DynamoDB table (PK: user_id, no SK -- Stage 4,
locked) rather than creating a new table. dynamodb.tf's own comment
already describes user_baseline as "per-user baseline state" for
ML/anomaly use; a `bandit_state` map attribute fits that without a
Terraform change. If context cardinality ever grows large enough to
need its own table, that is a clean, additive migration later -- not
required for first integration.

Context (Sec5 Step 3): user_id, p_access bucket, file_type, file_age
bucket, current_tier. user_id is already the table's partition key, so
the per-user map's inner key is built from the other four.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from decimal import Decimal

import boto3

_dynamodb = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(os.environ["USER_BASELINE_TABLE"])


def _p_access_bucket(p_access: float) -> str:
    if p_access >= 0.7:
        return "high"
    if p_access >= 0.3:
        return "mid"
    return "low"


def _file_age_bucket(file_age_days: float) -> str:
    if file_age_days < 30:
        return "new"
    if file_age_days < 180:
        return "established"
    return "old"


def context_key(p_access: float, file_type: str, file_age_days: float, current_tier: str) -> str:
    return "|".join([
        _p_access_bucket(p_access),
        str(file_type),
        _file_age_bucket(file_age_days),
        str(current_tier),
    ])


def _load_state(user_id: str) -> dict:
    resp = _table().get_item(Key={"user_id": user_id})
    item = resp.get("Item", {})
    return item.get("bandit_state", {})  # {context: {tier: {"alpha": N, "beta": N}}}


def _save_state(user_id: str, state: dict) -> None:
    _table().update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET bandit_state = :s",
        ExpressionAttributeValues={":s": state},
    )


@dataclass
class BanditChoice:
    chosen_tier: str
    context: str


def choose_tier(
    user_id: str,
    candidates: list[str],
    p_access: float,
    file_type: str,
    file_age_days: float,
    current_tier: str,
) -> BanditChoice:
    """
    Thompson Sampling over `candidates` (1 or 2 arms, per policy.py's
    boundary-vs-confident bands). A 1-arm candidate set deterministically
    returns that arm -- matches ML_SCHEMA Sec5 Step 2's own note that no
    special-casing is needed for the single-candidate case.
    """
    if len(candidates) == 1:
        return BanditChoice(candidates[0], "trivial_single_candidate")

    ctx = context_key(p_access, file_type, file_age_days, current_tier)
    state = _load_state(user_id)
    arms = state.get(ctx, {})

    best_tier = candidates[0]
    best_sample = -1.0
    for tier in candidates:
        params = arms.get(tier, {"alpha": 1, "beta": 1})  # uniform prior
        alpha, beta_v = float(params["alpha"]), float(params["beta"])
        sample = random.betavariate(alpha, beta_v)
        if sample > best_sample:
            best_sample = sample
            best_tier = tier

    return BanditChoice(best_tier, ctx)


def update_reward(user_id: str, context: str, chosen_tier: str, reward: int) -> None:
    """
    reward: +1 confirmed, -1 overridden, 0 no_response.
    Per Sec5 Step 3, no_response is a FLAT zero -- it does NOT update
    alpha/beta at all (means "we don't know," not "slightly good").
    Called from the feedback path (feedback-writer-fn), not from
    prediction generation itself.
    """
    if context == "trivial_single_candidate" or reward == 0:
        return

    state = _load_state(user_id)
    arms = state.setdefault(context, {})
    params = arms.setdefault(chosen_tier, {"alpha": Decimal(1), "beta": Decimal(1)})

    if reward == 1:
        params["alpha"] = Decimal(params["alpha"]) + 1
    elif reward == -1:
        params["beta"] = Decimal(params["beta"]) + 1

    _save_state(user_id, state)
