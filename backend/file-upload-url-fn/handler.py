"""
file-upload-url-fn — ASCOS Stage 6.

Generates a UUID fileId, constructs S3 key {user_id}/{file_id},
and returns a presigned PUT URL that REQUIRES the client to send
the x-amz-meta-filename header (enforced by including it in the
signed request — S3 rejects the upload if the header doesn't
match what was signed, so the client cannot omit it).

IAM: s3:PutObject.
"""

import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
UPLOAD_URL_EXPIRY_SECONDS = int(os.environ.get("UPLOAD_URL_EXPIRY_SECONDS", "300"))


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
        logger.warning("file-upload-url-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    filename = body.get("filename")
    if not filename or not isinstance(filename, str) or not filename.strip():
        return _response(400, {"error": "filename is required"})

    file_id = str(uuid.uuid4())
    key = f"{user_id}/{file_id}"

    try:
        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": key,
                # Including Metadata in the signed params means S3
                # requires the client's actual PUT request to send
                # a matching x-amz-meta-filename header, or the
                # request's signature won't validate. This is what
                # actually enforces the header, not just documents it.
                "Metadata": {"filename": filename},
            },
            ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
        )
    except ClientError as e:
        logger.error("file-upload-url-fn: presign error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})

    logger.info("file-upload-url-fn: user_id=%s generated fileId=%s", user_id, file_id)
    return _response(200, {"fileId": file_id, "uploadUrl": upload_url})
