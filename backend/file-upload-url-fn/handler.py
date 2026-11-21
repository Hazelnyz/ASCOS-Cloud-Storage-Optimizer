"""
file-upload-url-fn — ASCOS Stage 6.

Generates a UUID fileId, constructs S3 key {user_id}/{file_id},
and returns a presigned PUT URL that REQUIRES the client to send
the x-amz-meta-filename header (enforced by including it in the
signed request — S3 rejects the upload if the header doesn't
match what was signed, so the client cannot omit it).

It also stamps the object with x-amz-meta-uploaded-at (server clock, ISO-8601
UTC). S3's own LastModified is reset by every CopyObject (tier change, pin
restore), so it cannot tell us when a file was really uploaded. The signed
headers are returned in the response as `headers`; the client MUST send them
exactly as given (they are part of the signature). Percent-encoding of the
filename means the raw name must never be sent instead.

IAM: s3:PutObject.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

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
    metadata = {
        "filename": quote(filename, safe=""),
        "uploaded-at": datetime.now(timezone.utc).isoformat(),
    }

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
                "Metadata": metadata,
            },
            ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
        )
    except ClientError as e:
        logger.error("file-upload-url-fn: presign error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})

    logger.info("file-upload-url-fn: user_id=%s generated fileId=%s", user_id, file_id)
    return _response(200, {
        "fileId": file_id,
        "uploadUrl": upload_url,
        "headers": {f"x-amz-meta-{k}": v for k, v in metadata.items()},
        "expiresInSeconds": UPLOAD_URL_EXPIRY_SECONDS,
    })
