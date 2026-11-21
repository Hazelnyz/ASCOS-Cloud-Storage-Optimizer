"""
tier-change-fn — ASCOS Stage 9 (real implementation: manual tier change).

Executes a user-requested Hot/Warm/Cold storage-class change for one file,
per master reference section 15 (User-driven tier change).

SCOPE OF THIS IMPLEMENTATION:
    Manual, user-initiated tier changes only - reached via
    POST /files/{fileId}/tier/change. Automated ML/bandit-driven tiering
    (master reference section 5's policy engine) does not exist yet
    (Stage 10) and has no caller into this function today.

    Per ML_SCHEMA.md section 5's own clarification: protected_flag bypasses
    *automatic* tier changes only - it is not a general "locked file" flag,
    and manual tier changes remain fully allowed regardless of protection
    status. So this function does NOT block on protected_flag - it only
    reads it (protected_files:GetItem, already granted) to include an
    informational "protected" field in the response, matching the
    reference UI's own copy ("Manual tier changes are still allowed -
    protection only blocks automated ML-driven changes").

WHY THIS IS SIMPLER THAN THE GENERAL MASTER-REFERENCE CASE:
    Section 13/26 locked COLD to S3 Glacier Instant Retrieval specifically
    *because* it needs no RestoreObject step (real-time access, unlike
    Flexible Retrieval/Deep Archive). So every transition in this
    deployment - Hot<->Warm, Hot<->Cold, Warm<->Cold - is a single
    CopyObject with a different StorageClass, never a restore-then-copy
    sequence. The general restore-wait path in the master reference
    doesn't apply to this specific, already-locked configuration.

LARGE-OBJECT HANDLING (section 16):
    CopyObject only supports objects <=5GB in one call; objects >5GB
    require multipart UploadPartCopy. That path is NOT implemented in
    this pass - an oversized object returns a clear 501, not a silent
    failure or a pretend-success. Multipart copy is real, separate work
    to add when/if a file that large is actually tested.

CONCURRENCY (section 17):
    Uses CopySourceIfMatch with the ETag read at HeadObject time, so a
    file modified between the HeadObject read and the CopyObject write
    fails the request cleanly (412) instead of silently clobbering
    whatever the newer version was.

IAM: s3:GetObject + s3:PutObject on the app bucket (already granted at
Stage 5 - CopyObject needs both, not a literal "s3:CopyObject" action,
which doesn't exist - see docs/AWS_SETUP_LOG.md known-issue #6), plus
protected_files:GetItem (already granted, used for the informational
flag described above). No new IAM required for this implementation.

ASSUMPTION TO VERIFY: this assumes an env var PROTECTED_FILES_TABLE
exists on this function, matching the naming pattern used elsewhere
(ACCESS_EVENT_TABLE, SECURITY_STATE_TABLE). Confirm against the real
lambda.tf environment block for tier-change-fn - add it if missing.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
PROTECTED_FILES_TABLE = os.environ["PROTECTED_FILES_TABLE"]
protected_table = dynamodb.Table(PROTECTED_FILES_TABLE)

TIER_TO_STORAGE_CLASS = {
    "HOT": "STANDARD",
    "WARM": "STANDARD_IA",
    "COLD": "GLACIER_IR",
}
STORAGE_CLASS_TO_TIER = {v: k for k, v in TIER_TO_STORAGE_CLASS.items()}

MAX_SINGLE_COPY_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB - CopyObject's real limit


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


def _current_tier(head):
    storage_class = head.get("StorageClass", "STANDARD")
    return STORAGE_CLASS_TO_TIER.get(storage_class, "HOT")


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("tier-change-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})

    target_tier = str(body.get("targetTier", "")).upper()
    if target_tier not in TIER_TO_STORAGE_CLASS:
        return _response(400, {"error": "targetTier must be one of HOT, WARM, COLD"})

    key = f"{user_id}/{file_id}"

    try:
        head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("tier-change-fn: HeadObject error for key=%s: %s", key, e)
        return _response(500, {"error": "Internal server error"})

    current_tier = _current_tier(head)
    etag = head.get("ETag")
    size = head.get("ContentLength", 0)

    protected = False
    try:
        item = protected_table.get_item(Key={"user_id": user_id, "file_id": file_id}).get("Item")
        protected = item is not None
    except ClientError as e:
        logger.warning("tier-change-fn: protected_files lookup failed for key=%s: %s", key, e)

    if current_tier == target_tier:
        return _response(200, {
            "fileId": file_id,
            "previousTier": current_tier,
            "newTier": target_tier,
            "status": "no_action_needed",
            "protected": protected,
        })

    if size > MAX_SINGLE_COPY_BYTES:
        logger.warning("tier-change-fn: object too large for single CopyObject, key=%s size=%d", key, size)
        return _response(501, {
            "error": "This file is larger than 5GB; multipart tier-change is not implemented yet.",
        })

    try:
        s3.copy_object(
            Bucket=BUCKET_NAME,
            Key=key,
            CopySource={"Bucket": BUCKET_NAME, "Key": key},
            CopySourceIfMatch=etag,
            StorageClass=TIER_TO_STORAGE_CLASS[target_tier],
            MetadataDirective="COPY",
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "PreconditionFailed":
            return _response(412, {
                "error": "This file changed while the tier change was being processed. Please retry.",
            })
        logger.error("tier-change-fn: CopyObject error for key=%s: %s", key, e)
        return _response(500, {"error": "Internal server error"})

    try:
        verified_head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        logger.exception("tier-change-fn: post-copy HeadObject verification failed for key=%s", key)
        return _response(500, {"error": "Could not verify the new storage class"})

    expected_storage_class = TIER_TO_STORAGE_CLASS[target_tier]
    actual_storage_class = verified_head.get("StorageClass", "STANDARD")
    if actual_storage_class != expected_storage_class:
        logger.error(
            "tier-change-fn: storage class verification mismatch for key=%s expected=%s actual=%s",
            key, expected_storage_class, actual_storage_class,
        )
        return _response(500, {"error": "Storage class verification failed"})

    logger.info(
        "tier-change-fn: user_id=%s fileId=%s %s -> %s",
        user_id, file_id, current_tier, target_tier,
    )
    return _response(200, {
        "fileId": file_id,
        "previousTier": current_tier,
        "newTier": target_tier,
        "status": "changed",
        "protected": protected,
    })
