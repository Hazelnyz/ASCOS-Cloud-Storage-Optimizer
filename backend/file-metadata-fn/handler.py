"""
file-metadata-fn — ASCOS Stage 6.

HeadObject on {user_id}/{file_id} (key constructed from the JWT-
derived user_id + route fileId — no discovery). Returns filename
(from x-amz-meta-filename), size, last modified, content type, and
storage class (the object's current Hot/Warm/Cold tier, read
natively from S3 — no separate tracking table needed, per the
Stage 6 file-metadata design).

IAM: s3:GetObject (HeadObject uses this same permission).
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

    result = {
        "fileId": file_id,
        "filename": metadata.get("filename"),
        "size": head.get("ContentLength"),
        "lastModified": head["LastModified"].isoformat() if head.get("LastModified") else None,
        "contentType": head.get("ContentType"),
        # Defaults to STANDARD when the API omits it (i.e. the
        # object is in the Hot tier) — S3 doesn't echo StorageClass
        # for Standard objects on HeadObject.
        "storageClass": head.get("StorageClass", "STANDARD"),
    }

    logger.info("file-metadata-fn: user_id=%s fileId=%s", user_id, file_id)
    return _response(200, result)
