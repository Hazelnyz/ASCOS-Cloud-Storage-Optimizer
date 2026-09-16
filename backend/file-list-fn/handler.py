"""
file-list-fn — ASCOS Stage 6.

Lists the authenticated user's files via S3 ListObjectsV2, scoped
strictly to the {user_id}/ prefix derived from the validated
Cognito JWT claims (never from client input).

IAM: s3:ListBucket only (see header note in api-lambdas.tf — this
function does NOT call HeadObject per item, so it does not need
s3:GetObject; filenames are not returned by this endpoint).
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
    """Extract the Cognito sub from the JWT claims API Gateway
    attaches to the request. Never trust a client-supplied user_id.
    """
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        return claims["sub"]
    except (KeyError, TypeError):
        return None


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("file-list-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    prefix = f"{user_id}/"

    try:
        files = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # key shape: {user_id}/{file_id} — strip the prefix
                # to get the fileId. Skip anything that doesn't
                # match the expected shape (e.g. a stray "folder"
                # marker object) rather than erroring the whole list.
                file_id = key[len(prefix):]
                if not file_id or "/" in file_id:
                    continue
                files.append({
                    "fileId": file_id,
                    "size": obj["Size"],
                    "lastModified": obj["LastModified"].isoformat(),
                })

        logger.info("file-list-fn: user_id=%s returned %d files", user_id, len(files))
        return _response(200, {"files": files})

    except ClientError as e:
        logger.error("file-list-fn: S3 error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})
