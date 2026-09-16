"""
file-delete-fn — ASCOS Stage 6.

Deletes {user_id}/{file_id}, where user_id comes only from the
validated JWT. Because the key always starts with the
authenticated user's own user_id, this cannot delete another
user's object regardless of what fileId a client supplies.

IAM: s3:DeleteObject.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
BUCKET_NAME = os.environ["S3_BUCKET_NAME"]


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
        logger.warning("file-delete-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    key = f"{user_id}/{file_id}"

    try:
        # Confirm existence first so a delete of a non-existent
        # fileId returns a clean 404 rather than a false-success —
        # S3's DeleteObject returns 204 even if the key never
        # existed, which would otherwise be misleading to the caller.
        s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("file-delete-fn: HeadObject error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        logger.error("file-delete-fn: DeleteObject error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    logger.info("file-delete-fn: user_id=%s deleted fileId=%s", user_id, file_id)
    return _response(200, {"fileId": file_id, "deleted": True})
