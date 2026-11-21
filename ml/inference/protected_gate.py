"""
ml/inference/protected_gate.py

ML_SCHEMA Sec5 Step 1 -- the hard gate, checked BEFORE candidate-tier
generation runs at all, entirely outside the bandit. Kept as its own
module (not folded into policy.py) so "protected files always win"
can never be accidentally refactored away inside the policy logic.

This module only DECIDES. It never calls tier-change-fn or S3 itself --
policy != storage execution stays enforced here (Master Reference Sec37).
Actually executing a restore/CopyObject remains tier-change-fn's job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import boto3
from boto3.dynamodb.conditions import Key

_dynamodb = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(os.environ["PROTECTED_FILES_TABLE"])


@dataclass
class GateResult:
    is_protected: bool
    action: str  # "proceed" | "bypass_bandit_no_change" | "bypass_bandit_restore_to_hot"
    reason: str


def check_hard_gate(user_id: str, file_id: str, current_storage_tier: str) -> GateResult:
    """
    if protected_flag == true -> recommend "no change" to auto-tiering
       BUT: if current_storage_tier == Cold -> trigger an immediate
       restore (RestoreObject -> CopyObject) anyway. Pinning is a
       strong explicit signal -- it should get the user OUT of Cold
       now, not just stop future archiving (ML_SCHEMA Sec5 Step 1).
    """
    resp = _table().get_item(Key={"user_id": user_id, "file_id": file_id})
    is_protected = "Item" in resp

    if not is_protected:
        return GateResult(False, "proceed", "not protected")

    if current_storage_tier == "COLD":
        return GateResult(
            True,
            "bypass_bandit_restore_to_hot",
            "protected file currently Cold -- immediate restore per Sec5 Step 1",
        )

    return GateResult(True, "bypass_bandit_no_change", "protected -- automated tiering skipped")


def is_protected(user_id: str, file_id: str) -> bool:
    resp = _table().get_item(Key={"user_id": user_id, "file_id": file_id})
    return "Item" in resp
