"""
anomaly-scorer-fn — ASCOS Stage 7 update (was Stage 5 scaffolding).

SCOPE (master reference §18, §19; ML schema §7):
Invoked by EventBridge (Stage 7.4) with the same CloudTrail-
derived S3 data events access-event-writer-fn records.

STAGE 7 STATUS — LOGGING-ONLY STUB, NOTHING ELSE:
severity is hardcoded to "Low". This stage establishes the
security PLUMBING (EventBridge trigger wired; security_state
IAM already in place since Stage 5; SNS publish IAM arrives with
Stage 7.6, not this file) but deliberately does NOT exercise
containment or alerting yet — Stage 7 is infrastructure, not
anomaly intelligence (that's Stage 10, ML schema §7, Isolation
Forest).

_contain_user() and _publish_alert() below are Stage 10
ACTIVATION PATHS ONLY. They exist so Stage 10 has a place to wire
real logic into, but the Stage 7 handler never calls them — not
even speculatively, and not even though severity can currently
only ever be "Low". This is deliberate: Stage 7 must not produce
any security_state row or SNS alert under any circumstance,
regardless of what the (currently trivial) severity value is.

DEFENSE IN DEPTH: the EventBridge rule (eventbridge.tf) already
filters to GetObject/PutObject/DeleteObject only, but this
handler independently re-checks eventName before doing anything
— same principle already applied in access-event-writer-fn
(Stage 7.3). Never trust upstream filtering alone; a future edit
to the EventBridge pattern shouldn't be able to silently widen
what this function acts on.
"""
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

SECURITY_STATE_TABLE = os.environ.get("SECURITY_STATE_TABLE")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")

# Same allowlist as access-event-writer-fn — kept as a local
# constant here rather than shared/imported, consistent with each
# Lambda being an independent, single-purpose deployment unit
# (§19) with no shared code module between them.
ALLOWED_EVENT_NAMES = {"GetObject", "PutObject", "DeleteObject"}


def handler(event, context):
    detail = event.get("detail", {})
    event_name = detail.get("eventName")

    if event_name not in ALLOWED_EVENT_NAMES:
        logger.info("Ignoring non-access eventName=%s", event_name)
        return {"status": "ignored", "event_name": event_name}

    user_id = _extract_user_id(detail)
    if not user_id:
        logger.warning("Could not extract user_id from event — logging only, no scoring possible")

    # STAGE 7 STUB — see module docstring. Real Isolation Forest
    # scoring (ML schema §7) replaces this single line in Stage 10.
    severity = "Low"

    # STAGE 7: logging only, always — regardless of severity value.
    # Containment (_contain_user) and alerting (_publish_alert) are
    # NOT called here on purpose. Stage 10 activates them once real
    # scoring exists to justify a Medium/High result.
    logger.info("severity=%s for user=%s eventName=%s — Stage 7 logging only, no enforcement/alerting", severity, user_id, event_name)

    return {"status": "logged", "severity": severity, "user_id": user_id}


def _extract_user_id(detail):
    request_params = detail.get("requestParameters") or {}
    object_key = request_params.get("key") or ""
    if "/" not in object_key:
        return None
    user_id = object_key.split("/", 1)[0]
    return user_id or None


def _contain_user(user_id):
    """STAGE 10 ACTIVATION PATH — not called by Stage 7's handler."""
    if not user_id or not SECURITY_STATE_TABLE:
        logger.warning("Cannot contain — missing user_id or SECURITY_STATE_TABLE")
        return
    dynamodb.Table(SECURITY_STATE_TABLE).put_item(Item={"user_id": user_id})
    logger.info("Wrote containment row for user=%s", user_id)


def _publish_alert(user_id, detail):
    """STAGE 10 ACTIVATION PATH — not called by Stage 7's handler."""
    if not SNS_TOPIC_ARN:
        logger.warning("Cannot publish alert — SNS_TOPIC_ARN not set")
        return
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject="ASCOS — High severity anomaly detected",
        Message=json.dumps({"user_id": user_id, "detail": detail}, default=str),
    )
    logger.info("Published High-severity alert for user=%s", user_id)