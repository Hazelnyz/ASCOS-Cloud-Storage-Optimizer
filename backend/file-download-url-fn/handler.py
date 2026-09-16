"""
file-download-url-fn — ASCOS Stage 6.

Generates a presigned GET URL for {user_id}/{file_id}, where
user_id comes only from the validated JWT and file_id from the
route — the key is constructed directly, no discovery step.
Because the key always starts with the authenticated user's own
user_id, a client supplying another user's fileId simply produces
a different key that user does not own; S3 will 404 rather than
leak another user's file.

IAM: s3:GetObject.
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
DOWNLOAD_URL_EXPIRY_SECONDS = int(os.environ.get("DOWNLOAD_URL_EXPIRY_SECONDS", "900"))


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
        logger.warning("file-download-url-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    key = f"{user_id}/{file_id}"

    try:
        # Confirm the object actually exists (and belongs to this
        # user, by construction of the key) before signing a URL
        # for it, so we can return a clean 404 instead of handing
        # back a URL that will fail when used.
        s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("file-download-url-fn: HeadObject error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    try:
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=DOWNLOAD_URL_EXPIRY_SECONDS,
        )
    except ClientError as e:
        logger.error("file-download-url-fn: presign error for user_id=%s key=%s: %s", user_id, key, e)
        return _response(500, {"error": "Internal server error"})

    logger.info("file-download-url-fn: user_id=%s fileId=%s", user_id, file_id)
    return _response(200, {"fileId": file_id, "downloadUrl": download_url})
