"""
access-event-writer-fn — ASCOS Stage 7.3.

SCOPE (master reference §22, §23; ML schema §1):
Invoked by EventBridge (Stage 7.4) with CloudTrail-derived S3
data events (GetObject/PutObject/DeleteObject on the app storage
bucket). Writes one row into access_event per real event — the
authoritative raw log the future ML pipeline (Stage 10) trains on.

user_id/file_id are recovered from the S3 object key prefix
({user_id}/{file_id}, locked Stage 6 design) — NEVER from
CloudTrail's userIdentity field, since presigned URLs are signed
by this project's own Lambda execution roles, not the end user.
split("/", 1) is used deliberately so a file_id containing its
own "/" characters is preserved intact. Both resulting halves
are validated as non-empty — a key like "/file.txt" or
"user123/" would otherwise silently produce a corrupt
(empty-string) user_id or file_id in the authoritative log.

Idempotent by design: CloudTrail's own eventID is reused as
access_event's event_id, and the write is conditional on the
composite sort key not already existing, so CloudTrail's
at-least-once delivery guarantee never produces duplicate rows.

BOTH eventID and eventTime are validated as present BEFORE
constructing that sort key, and both raise (rather than
falling back to a synthetic value) if missing:
  - eventID missing -> would silently produce a corrupt
    "...#None" key in the authoritative training log.
  - eventTime missing -> a fallback to the current wall-clock
    time would (a) break idempotency itself, since a genuine
    CloudTrail redelivery could compute a different fallback
    timestamp on retry and produce a second, undetected sort
    key for the same real event, and (b) silently corrupt the
    ML temporal features (access_hour_sin/cos, day_of_week,
    etc. — ML schema §2) that this timestamp eventually feeds,
    which is exactly the kind of leakage/corruption the
    project's golden no-leakage rule exists to prevent
    elsewhere. Real CloudTrail events reliably carry eventTime,
    so refusing a malformed one is the safer failure mode.

Deliberately does nothing else: no scoring, no baseline updates,
no security logic — that separation is intentional (§19).
"""
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["ACCESS_EVENT_TABLE"])

# Defense in depth — the EventBridge rule (Stage 7.4) already
# filters to just these eventNames, but never trust upstream
# filtering alone.
ALLOWED_EVENT_NAMES = {
    "GetObject": "download",
    "PutObject": "write",
    "DeleteObject": "delete",
}


def handler(event, context):
    detail = event.get("detail", {})
    event_name = detail.get("eventName")

    if event_name not in ALLOWED_EVENT_NAMES:
        logger.info("Ignoring non-access eventName=%s", event_name)
        return {"status": "ignored", "event_name": event_name}

    event_id = detail.get("eventID")
    if not event_id:
        logger.warning("Missing CloudTrail eventID — refusing to write a corrupt sort key")
        raise ValueError("Missing CloudTrail eventID")

    timestamp = detail.get("eventTime")
    if not timestamp:
        logger.warning(
            "Missing CloudTrail eventTime for event_id=%s — refusing rather than "
            "substituting a synthetic timestamp (would break idempotency and "
            "corrupt downstream ML temporal features)",
            event_id,
        )
        raise ValueError("Missing CloudTrail eventTime")

    request_params = detail.get("requestParameters") or {}
    object_key = request_params.get("key")
    if not object_key or "/" not in object_key:
        logger.warning("Malformed or missing object key: %r", object_key)
        raise ValueError(f"Cannot derive user_id/file_id from key: {object_key!r}")

    user_id, file_id = object_key.split("/", 1)
    if not user_id or not file_id:
        logger.warning("Malformed object key — empty user_id or file_id: %r", object_key)
        raise ValueError(f"Cannot derive user_id/file_id from key: {object_key!r}")

    event_type = ALLOWED_EVENT_NAMES[event_name]
    timestamp_event_id = f"{timestamp}#{event_id}"

    item = {
        "user_id": user_id,
        "timestamp_event_id": timestamp_event_id,
        "user_id_file_id": f"{user_id}#{file_id}",
        "event_id": event_id,
        "file_id": file_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "source_ip": detail.get("sourceIPAddress"),
        "device_context": detail.get("userAgent"),
    }

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(timestamp_event_id)",
        )
        logger.info("Wrote access_event %s user=%s file=%s type=%s", event_id, user_id, file_id, event_type)
        return {"status": "written", "event_id": event_id}
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("Duplicate delivery ignored for event_id=%s", event_id)
            return {"status": "duplicate_ignored", "event_id": event_id}
        raise