"""
anomaly-scorer-fn — ASCOS Stage 5 scaffolding.

SCOPE (per master reference §18, §19, ML schema §7):
    Eventually runs Isolation Forest per-user anomaly scoring against
    short-horizon rolling-window features, determines severity
    (Low/Medium/High), and manages the security_state containment
    record for High-severity responses.

STAGE 5 STATUS:
    Infrastructure scaffolding only. The anomaly-detection algorithm
    itself is not implemented yet. This function IS granted real,
    justified permissions today (security_state GetItem/PutItem/
    DeleteItem) because §19 directly and explicitly names this
    table/Lambda relationship as the containment mechanism — this
    isn't a guess about future logic, it's the cited architecture.
    The actual scoring logic (reading access_event/user_baseline,
    computing anomaly scores) is deferred to the later
    security/anomaly-detection implementation stage.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info("anomaly-scorer-fn invoked (Stage 5 scaffolding). Event: %s", json.dumps(event))

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "stage5_scaffold",
            "function": "anomaly-scorer-fn",
            "message": (
                "Stage 5 scaffolding only. Isolation Forest scoring "
                "and severity logic arrive with the security/anomaly-"
                "detection implementation stage. security_state "
                "read/write permissions are already granted per §19."
            ),
        }),
    }
