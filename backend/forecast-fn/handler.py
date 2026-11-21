"""
forecast-fn — ASCOS Stage 5 scaffolding.

SCOPE (per master reference §25):
    Eventually computes storage cost, retrieval cost, transition
    implications, and net cost impact for a proposed tier change,
    supporting all logical tier-to-tier comparisons (Hot<->Warm,
    Hot<->Cold, Warm<->Cold), single file or batch.

STAGE 5 STATUS:
    Infrastructure scaffolding only. Exactly HOW this function gets
    its inputs (does it query access_event itself, or receive
    pre-computed context from the caller?) is not yet specified by
    the master reference and was deliberately left undecided rather
    than assumed. No DynamoDB or S3 permissions beyond basic logging
    are granted yet — those will be added once Stage 6/7 clarifies
    the actual data flow into this function.
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
    logger.info("forecast-fn invoked (Stage 5 scaffolding). Context: %s", json.dumps(_safe_log_context(event)))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "forecast-fn",
            "message": (
                "Stage 5 scaffolding only. Cost-forecast logic arrives "
                "once Stage 6/7 clarifies this function's actual data "
                "inputs."
            ),
        }),
    }
