"""
file-metadata-fn — ASCOS Stage 6.

HeadObject on {user_id}/{file_id} (key constructed from the JWT-
derived user_id + route fileId — no discovery). Returns filename
(from x-amz-meta-filename), size, last modified, content type, and
storage class (the object's current Hot/Warm/Cold tier, read
natively from S3 — no separate tracking table needed, per the
Stage 6 file-metadata design).

It also summarises the file's access history from the access_event table
(GSI user-file-index, one Query per request, only ever the caller's own
user_id#file_id partition):
    lastAccessedAt   - newest download/share event (ISO), or null if none
    recentAccessCount - number of download/share events in the last
                        ACCESS_WINDOW_DAYS days (accessWindowDays in the reply)
Uploads (write) and deletes do not count as an "access". Events arrive via
CloudTrail, so a new access can take a few minutes to show up. If the lookup
fails, both fields are null (unknown) - never 0 - so the UI can say
"unavailable" instead of showing a wrong "never accessed".

IAM: s3:GetObject (HeadObject uses this same permission) +
dynamodb:Query on the access_event user-file-index GSI.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
access_event_table = dynamodb.Table(os.environ["ACCESS_EVENT_TABLE"])
ACCESS_INDEX_NAME = os.environ.get("ACCESS_EVENT_INDEX", "user-file-index")
ACCESS_WINDOW_DAYS = int(os.environ.get("ACCESS_WINDOW_DAYS", "30"))
ACCESS_MAX_QUERY_PAGES = int(os.environ.get("ACCESS_MAX_QUERY_PAGES", "10"))
# access_event.event_type values that count as someone accessing the file.
ACCESS_EVENT_TYPES = ("download", "share")


def _decode_filename(stored):
    """x-amz-meta-filename is stored percent-encoded (S3 metadata headers must
    be ASCII). Return the real name; None stays None."""
    if not stored:
        return None
    try:
        return unquote(stored)
    except Exception:  # pragma: no cover - unquote does not raise on str input
        return stored


def _parse_ts(value):
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _access_summary(user_id, file_id):
    """(last_accessed_iso | None, recent_count) or (None, None) if the lookup failed.

    Newest-first Query of this file's events; stops as soon as it has seen the
    newest access AND walked past the window. Capped at ACCESS_MAX_QUERY_PAGES
    pages, so a very busy file's count is a lower bound, never an overcount.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACCESS_WINDOW_DAYS)
    last_accessed = None
    count = 0
    kwargs = {
        "IndexName": ACCESS_INDEX_NAME,
        "KeyConditionExpression": "user_id_file_id = :k",
        "FilterExpression": "event_type IN (:d, :s)",
        "ExpressionAttributeValues": {
            ":k": f"{user_id}#{file_id}",
            ":d": ACCESS_EVENT_TYPES[0],
            ":s": ACCESS_EVENT_TYPES[1],
        },
        "ScanIndexForward": False,
    }
    try:
        for _ in range(ACCESS_MAX_QUERY_PAGES):
            page = access_event_table.query(**kwargs)
            for item in page.get("Items", []):
                ts = _parse_ts(item.get("timestamp"))
                if ts is None:
                    continue
                if last_accessed is None:
                    last_accessed = item["timestamp"]
                if ts >= cutoff:
                    count += 1
                else:
                    return last_accessed, count
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    except ClientError as e:
        logger.warning("file-metadata-fn: access_event lookup failed for user_id=%s file_id=%s: %s", user_id, file_id, e)
        return None, None
    return last_accessed, count


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
        logger.warning("file-metadata-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    key = f"{user_id}/{file_id}"

    try:
        head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("file-metadata-fn: HeadObject error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    metadata = head.get("Metadata", {})  # boto3 strips the x-amz-meta- prefix

    last_accessed_at, recent_count = _access_summary(user_id, file_id)

    result = {
        "fileId": file_id,
        "filename": _decode_filename(metadata.get("filename")),
        "size": head.get("ContentLength"),
        "lastModified": head["LastModified"].isoformat() if head.get("LastModified") else None,
        # Server-recorded upload time (absent on files uploaded before it was
        # stamped). S3 LastModified above also moves on tier changes.
        "uploadedAt": metadata.get("uploaded-at"),
        "lastAccessedAt": last_accessed_at,
        "recentAccessCount": recent_count,
        "accessWindowDays": ACCESS_WINDOW_DAYS,
        "contentType": head.get("ContentType"),
        # Defaults to STANDARD when the API omits it (i.e. the
        # object is in the Hot tier) — S3 doesn't echo StorageClass
        # for Standard objects on HeadObject.
        "storageClass": head.get("StorageClass", "STANDARD"),
    }

    logger.info("file-metadata-fn: user_id=%s fileId=%s", user_id, file_id)
    return _response(200, result)
