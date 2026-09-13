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


def handler(event, context):
    logger.info("prediction-fn invoked (Stage 5 scaffolding). Event: %s", json.dumps(event))

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
