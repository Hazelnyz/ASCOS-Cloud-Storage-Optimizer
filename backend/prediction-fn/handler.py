"""
prediction-fn — ASCOS Stage 5 scaffolding.

SCOPE (per ML schema §4, §9):
    Eventually runs LightGBM.predict_proba() via ONNX Runtime inside
    this Lambda, producing p_access and, via SHAP, the top_reasons
    explanation for the ML Explanation UI feature.

STAGE 5 STATUS:
    Infrastructure scaffolding only. No model exists yet (that's
    Stage 10), so this function has nothing real to execute. No
    DynamoDB permissions are granted at this stage — access_event
    and user_baseline reads, and predictions writes, are deferred
    until Stage 10 actually builds the feature-engineering and
    inference logic that would use them. Granting those permissions
    now would not be justified by any current implementation.
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
    logger.info("prediction-fn invoked (Stage 5 scaffolding). Context: %s", json.dumps(_safe_log_context(event)))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "prediction-fn",
            "message": (
                "Stage 5 scaffolding only. LightGBM/SHAP inference "
                "logic arrives with Stage 10 (ML pipeline)."
            ),
        }),
    }
