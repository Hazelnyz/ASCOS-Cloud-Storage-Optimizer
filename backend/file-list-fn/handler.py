"""
file-list-fn — ASCOS Stage 6 (updated: resolves real filenames + tier).

Lists the authenticated user's files via S3 ListObjectsV2, scoped
strictly to the {user_id}/ prefix derived from the validated
Cognito JWT claims (never from client input).

UPDATE FROM ORIGINAL SCAFFOLD:
    The original version deliberately skipped HeadObject per item to
    avoid the extra cost/latency, returning only fileId/size/lastModified -
    meaning the list showed raw file_id UUIDs instead of real filenames,
    since the filename only exists as S3 object metadata
    (x-amz-meta-filename), not in ListObjectsV2's response.

    Decision: add one HeadObject per file (Option A), accepting the
    extra S3 request per file, so the list shows real filenames and the
    object's real current tier instead of raw UUIDs. At this project's
    scale (a handful of real users, not a high-file-count production
    workload) this is a deliberate, accepted tradeoff - revisit only if
    file counts per user grow large enough for N+1 HeadObject calls to
    become a real latency/cost concern.

    A HeadObject failure for a single file (e.g. an eventual-consistency
    edge case) degrades that one row to filename=null rather than
    failing the entire list - one bad file shouldn't hide every other
    file from the user.

PINNED STATE (added with the Pin feature):
    Each file also carries `protected` (true/false) and `pinnedAt` (ISO
    timestamp, or null for pins created before timestamps were stored). Both
    come from ONE Query on protected_files (PK user_id, SK file_id) per list
    request - not one lookup per file. If that Query fails, the list is still
    returned with protected=null ("unknown") for every file, so the frontend
    can show the files without claiming anything is or is not pinned. A pin
    lookup problem must never hide the user's files.

IAM: s3:ListBucket AND s3:GetObject (HeadObject uses the same
permission as GetObject), plus dynamodb:Query on protected_files - see the
accompanying Terraform change.
"""

import json
import logging
import os

from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
protected_table = dynamodb.Table(os.environ["PROTECTED_FILES_TABLE"])


def _decode_filename(stored):
    """x-amz-meta-filename is stored percent-encoded (S3 metadata headers must
    be ASCII). Return the real name; None stays None."""
    if not stored:
        return None
    try:
        return unquote(stored)
    except Exception:  # pragma: no cover - unquote does not raise on str input
        return stored


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


def _head_object_safe(key):
    """Best-effort HeadObject - returns {} on failure so one bad file
    degrades gracefully (filename=null, tier defaults to STANDARD)
    instead of failing the whole list.
    """
    try:
        return s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        logger.warning("file-list-fn: HeadObject failed for key=%s: %s", key, e)
        return {}


def _load_pins(user_id):
    """Return {file_id: pinned_at_or_None} for this user's pinned files, or
    None if the lookup failed (callers then report protected=null/unknown).

    protected_files is row-exists-means-protected, keyed (user_id, file_id), so
    one paginated Query on the user's partition returns every pin.
    """
    pins = {}
    try:
        kwargs = {
            "KeyConditionExpression": Key("user_id").eq(user_id),
            "ProjectionExpression": "file_id, pinned_at",
        }
        while True:
            resp = protected_table.query(**kwargs)
            for item in resp.get("Items", []):
                pins[item["file_id"]] = item.get("pinned_at")
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                return pins
            kwargs["ExclusiveStartKey"] = last_key
    except ClientError as e:
        logger.error("file-list-fn: protected_files query failed for user_id=%s: %s", user_id, e)
        return None


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("file-list-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    prefix = f"{user_id}/"
    pins = _load_pins(user_id)  # None = unknown (lookup failed), never "nobody is pinned"

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

                head = _head_object_safe(key)
                metadata = head.get("Metadata", {})  # boto3 strips x-amz-meta-

                files.append({
                    "fileId": file_id,
                    "filename": _decode_filename(metadata.get("filename")),
                    "size": obj["Size"],
                    "lastModified": obj["LastModified"].isoformat(),
                    # When the file was really uploaded (absent on older files).
                    "uploadedAt": metadata.get("uploaded-at"),
                    # Defaults to STANDARD when the API omits it (i.e. the
                    # object is in the Hot tier) — S3 doesn't echo
                    # StorageClass for Standard objects.
                    "storageClass": head.get("StorageClass", "STANDARD"),
                    # True/False when the pin lookup worked, None when it failed.
                    "protected": None if pins is None else file_id in pins,
                    "pinnedAt": None if pins is None else pins.get(file_id),
                })

        logger.info("file-list-fn: user_id=%s returned %d files", user_id, len(files))
        return _response(200, {"files": files})

    except ClientError as e:
        logger.error("file-list-fn: S3 error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})
