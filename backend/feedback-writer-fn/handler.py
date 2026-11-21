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

def _safe_log_context(event):
    """Summarize the invoking request without ever including headers or body.
    For an API-Gateway-triggered Lambda, the raw event's headers include the
    caller's live Authorization (JWT) header - logging json.dumps(event)
    whole would put that in plaintext in CloudWatch Logs. This is safe to log."""
    rc = event.get("requestContext", {}) if isinstance(event, dict) else {}
    http = rc.get("http", {})
    return {
        "requestId": rc.get("requestId"),
        "routeKey": event.get("routeKey"),
        "method": http.get("method"),
        "path": http.get("path"),
        "sourceIp": http.get("sourceIp"),
    }


def handler(event, context):
    logger.info("feedback-writer-fn invoked (Stage 5 scaffolding). Context: %s", json.dumps(_safe_log_context(event)))

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
