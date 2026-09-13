"""
feedback-writer-fn — ASCOS Stage 5 scaffolding.

SCOPE (per ML schema §6):
    Eventually writes a feedback record (feedback_event_id,
    prediction_id, action_taken, reward, bandit-context fields, etc.)
    whenever a user confirms or overrides a recommendation.

STAGE 5 STATUS:
    Infrastructure scaffolding only. This function is granted
    feedback:PutItem — the one permission directly justified by its
    named purpose. It does NOT yet have predictions:GetItem, since
    the master reference does not specify whether this function
    looks up prediction context itself or receives it already
    supplied by the caller (e.g. the frontend, which already has the
    prediction_id and recommended_tier in hand when it displayed the
    recommendation). That data-flow question is deferred to Stage
    6/7, and the permission will only be added then if the actual
    wiring justifies it.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info("feedback-writer-fn invoked (Stage 5 scaffolding). Event: %s", json.dumps(event))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "feedback-writer-fn",
            "message": (
                "Stage 5 scaffolding only. Feedback-write logic "
                "arrives once Stage 6/7 wires this function to real "
                "user actions."
            ),
        }),
    }
