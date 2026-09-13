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


def handler(event, context):
    logger.info("training-orchestrator-fn invoked (Stage 5 scaffolding). Event: %s", json.dumps(event))

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
