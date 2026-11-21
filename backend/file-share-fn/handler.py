"""
file-share-fn — ASCOS Stage 6.

Generates a 24-hour presigned GET URL for {user_id}/{file_id} and
writes a "share" row to access_event — the one event type that's
application-logged directly (ML schema §1: there's no S3 API call
for CloudTrail to observe for a share action, unlike
read/write/delete/download, which arrive via CloudTrail S3 data
events in Stage 7 instead).

Never makes the object public — this is a temporary, scoped,
private-object presigned URL only. Block Public Access on the
bucket is untouched by this function.

IAM: s3:GetObject + dynamodb:PutItem on access_event.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
SHARE_URL_EXPIRY_SECONDS = int(os.environ.get("SHARE_URL_EXPIRY_SECONDS", "86400"))
ACCESS_EVENT_TABLE = os.environ["ACCESS_EVENT_TABLE"]

access_event_table = dynamodb.Table(ACCESS_EVENT_TABLE)


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body_dict),
    }


def _get_authenticated_user_id(event):
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        return claims["sub"]
    except (KeyError, TypeError):
        return None


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("file-share-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    key = f"{user_id}/{file_id}"

    try:
        s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("file-share-fn: HeadObject error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    try:
        share_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=SHARE_URL_EXPIRY_SECONDS,
        )
    except ClientError as e:
        logger.error("file-share-fn: presign error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    # Write the share event. access_event schema (Stage 4, locked):
    #   PK = user_id
    #   SK = timestamp_event_id, a single composite string
    #        "<ISO8601 timestamp>#<event_id>" — timestamp alone
    #        isn't guaranteed unique, event_id is the tiebreaker.
    #   GSI user-file-index PK = user_id_file_id = "<user_id>#<file_id>"
    now_iso = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())
    try:
        access_event_table.put_item(Item={
            "user_id": user_id,
            "timestamp_event_id": f"{now_iso}#{event_id}",
            "user_id_file_id": f"{user_id}#{file_id}",
            "event_id": event_id,
            "file_id": file_id,
            "event_type": "share",
            "timestamp": now_iso,
        })
    except ClientError as e:
        # The presigned URL was already generated successfully — a
        # failure to log the share event shouldn't necessarily block
        # returning the URL to the user, but it must be logged
        # server-side as a real problem, since it means this share
        # won't show up in access history for the ML pipeline.
        logger.error("file-share-fn: access_event write failed for user_id=%s file_id=%s: %s", user_id, file_id, e)

    logger.info("file-share-fn: user_id=%s fileId=%s", user_id, file_id)
    return _response(200, {"fileId": file_id, "shareUrl": share_url})
