"""
training-orchestrator-fn — ASCOS Stage 5 scaffolding.

SCOPE (per ML schema §8):
    Eventually triggers the real, heavier LightGBM training job,
    which explicitly does NOT run inside a request-serving Lambda
    (§8: "NOT inside a request-serving Lambda; training is heavier
    and slower than inference and must not block the API path").
    This function's actual job is orchestration only — e.g. kicking
    off a scheduled EC2/Fargate training run — never running the
    training itself.

STAGE 5 STATUS:
    Infrastructure scaffolding only, and deliberately kept minimal.
    There is nothing real to orchestrate yet (no EC2 training
    pipeline exists until Stage 10), so this function is granted no
    permissions beyond basic logging. Adding orchestration
    permissions (e.g. ec2:StartInstances) now would not be justified
    by any current implementation.
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
    logger.info("training-orchestrator-fn invoked (Stage 5 scaffolding). Context: %s", json.dumps(_safe_log_context(event)))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "training-orchestrator-fn",
            "message": (
                "Stage 5 scaffolding only. Real orchestration logic "
                "(triggering the Stage 10 EC2 training job) arrives "
                "with Stage 10."
            ),
        }),
    }
