"""
tier-change-fn — ASCOS Stage 5 scaffolding.

SCOPE (per master reference §33 Stage 5 + §15/§16):
    Eventually responsible for executing Hot/Warm/Cold storage-class
    transitions (CopyObject for objects <=5GB, multipart UploadPartCopy
    for objects >5GB per §16), and for checking the protected_files
    hard gate (§5 Step 1) before performing any automated tier change.

STAGE 5 STATUS:
    This is infrastructure scaffolding only. The actual tier-change
    business logic (which storage class to move to, ETag/conditional
    checks per §17, restore-then-copy for Cold per §13) is NOT
    implemented yet — it depends on the policy engine and ML pipeline
    (Stage 10) to decide *what* to do, and on Stage 6/7 wiring to
    decide *when* this function is actually invoked.

    This handler exists to prove the function deploys, runs, logs
    correctly, and has exactly the IAM permissions it's currently
    justified to hold (S3 tier-change operations on the app bucket,
    protected_files:GetItem for the hard gate) — nothing more.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info("tier-change-fn invoked (Stage 5 scaffolding). Event: %s", json.dumps(event))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "tier-change-fn",
            "message": (
                "Stage 5 scaffolding only. Tier-change execution logic "
                "arrives with Stage 6/7 (event wiring) and Stage 10 "
                "(policy engine)."
            ),
        }),
    }
