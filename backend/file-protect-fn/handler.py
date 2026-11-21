"""
file-protect-fn — ASCOS Stage 9 (real implementation: manual pin/unpin,
including the Cold-tier restore-on-pin behavior).

Routes:
    POST   /files/{fileId}/protect   -> pins the file, restoring it from
                                         Cold to Hot first if needed
    DELETE /files/{fileId}/protect   -> unpins the file (removes the row
                                         only - never touches the file
                                         itself or its S3 data. This is a
                                         different route from
                                         DELETE /files/{fileId}, which is
                                         the real file delete.)

SCOPE, per ML_SCHEMA.md section 5:
    protected_flag is row-exists-means-protected (master reference
    section 24's DynamoDB design) and bypasses *automatic* ML-driven tier
    changes only - never blocks a manual tier change, and is read
    separately by the policy engine (Stage 10) as a hard gate, never fed
    to the model as a feature.

COLD-TIER RESTORE ON PIN (ML_SCHEMA.md section 5, Step 1):
    "Pinning a file is a strong explicit signal - it should get the user
    OUT of Cold now, not just stop future archiving." Implemented here:
    pinning a file currently in Cold triggers an immediate CopyObject to
    Hot before the pin is written. Because Cold is locked to S3 Glacier
    Instant Retrieval (master reference section 26), this needs no
    RestoreObject/wait step - same plain CopyObject idiom as
    tier-change-fn, not a duplicated restore-poll workflow.

    Ordering is deliberate: the Cold->Hot copy is attempted FIRST: if it
    fails, the function returns an error and the protected_files row is
    never written - no "pinned but silently still Cold" state. If the
    copy succeeds but the subsequent PutItem fails, the file is correctly
    in Hot but not yet marked protected - the safer of the two possible
    partial-failure states, since re-pinning just re-attempts the (now
    trivial, same-tier) write.

    The copy logic is intentionally duplicated from tier-change-fn rather
    than invoked cross-Lambda (lambda:InvokeFunction + reconstructing an
    API-Gateway-shaped event) - simpler, no new IAM surface for invoking
    another function, and the duplicated logic is ~10 lines that mirrors
    a locked, stable design decision (section 26), not likely to drift.

WHY ONE FUNCTION FOR PROTECT+UNPROTECT, NOT TWO:
    Confirmed as an accepted deliberate exception to Stage 6's one-
    function-per-route pattern - see prior version's docstring for the
    full reasoning. Adding the restore-on-pin logic only strengthens the
    case: protect's IAM now overlaps even more with tier-change-fn's
    than with unprotect's, so "split by route" was never the meaningful
    boundary here anyway.

PIN TIMESTAMP (added with the Pin feature):
    The protected_files row now stores `pinned_at` (UTC ISO8601) so My Files can
    list the most recently pinned files first. The write is conditional
    (attribute_not_exists) so pinning an already-pinned file is an idempotent
    success that KEEPS the original timestamp instead of resetting it (the
    response then has pinnedAt=null, meaning "unchanged"). Rows
    written before this change simply have no pinned_at (reported as null).

IAM (updated from the pin-only version): dynamodb:PutItem + DeleteItem
on protected_files, PLUS s3:GetObject + s3:PutObject on the app bucket
(HeadObject + CopyObject, for the restore-on-pin path). Needs
S3_BUCKET_NAME in addition to PROTECTED_FILES_TABLE.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
PROTECTED_FILES_TABLE = os.environ["PROTECTED_FILES_TABLE"]
protected_table = dynamodb.Table(PROTECTED_FILES_TABLE)

# Same locked mapping as tier-change-fn (master reference section 26).
STORAGE_CLASS_TO_TIER = {
    "STANDARD": "HOT",
    "STANDARD_IA": "WARM",
    "GLACIER_IR": "COLD",
}


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


def _handle_protect(user_id, file_id):
    key = f"{user_id}/{file_id}"

    try:
        head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return _response(404, {"error": "File not found"})
        logger.error("file-protect-fn: HeadObject error for key=%s: %s", key, e)
        return _response(500, {"error": "Internal server error"})

    current_tier = _current_tier(head)
    tier_changed = False

    if current_tier == "COLD":
        try:
            s3.copy_object(
                Bucket=BUCKET_NAME,
                Key=key,
                CopySource={"Bucket": BUCKET_NAME, "Key": key},
                CopySourceIfMatch=head.get("ETag"),
                StorageClass="STANDARD",
                MetadataDirective="COPY",
            )
            tier_changed = True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "PreconditionFailed":
                return _response(412, {
                    "error": "This file changed while being restored from Cold. Please retry.",
                })
            logger.error("file-protect-fn: restore-on-pin CopyObject failed for key=%s: %s", key, e)
            return _response(500, {"error": "Could not restore file from Cold storage."})

    pinned_at = datetime.now(timezone.utc).isoformat()
    try:
        protected_table.put_item(
            Item={"user_id": user_id, "file_id": file_id, "pinned_at": pinned_at},
            ConditionExpression="attribute_not_exists(file_id)",
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            # Already pinned: idempotent success. The stored pinned_at is kept as-is;
            # it is not read back here (that would need an extra dynamodb:GetItem
            # grant for a rare case), so report null and let the client keep the
            # timestamp it already has from the file list.
            pinned_at = None
        else:
            logger.error("file-protect-fn: PutItem failed for user_id=%s fileId=%s: %s", user_id, file_id, e)
            return _response(500, {"error": "Internal server error"})

    logger.info(
        "file-protect-fn: user_id=%s fileId=%s protected (restored_from_cold=%s)",
        user_id, file_id, tier_changed,
    )
    return _response(200, {
        "fileId": file_id,
        "protected": True,
        "tierChanged": tier_changed,
        "newTier": "HOT" if tier_changed else current_tier,
        "pinnedAt": pinned_at,
    })


def _handle_unprotect(user_id, file_id):
    try:
        protected_table.delete_item(Key={"user_id": user_id, "file_id": file_id})
    except ClientError as e:
        logger.error("file-protect-fn: DeleteItem failed for user_id=%s fileId=%s: %s", user_id, file_id, e)
        return _response(500, {"error": "Internal server error"})

    logger.info("file-protect-fn: user_id=%s fileId=%s unprotected", user_id, file_id)
    return _response(200, {"fileId": file_id, "protected": False})


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("file-protect-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    path_params = event.get("pathParameters") or {}
    file_id = path_params.get("fileId")
    if not file_id:
        return _response(400, {"error": "fileId is required"})

    method = event.get("requestContext", {}).get("http", {}).get("method")

    if method == "POST":
        return _handle_protect(user_id, file_id)
    if method == "DELETE":
        return _handle_unprotect(user_id, file_id)
    return _response(405, {"error": "Method not allowed"})
