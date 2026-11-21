"""
frequently-used-fn — ASCOS Stage 6.

Queries the existing predictions table's user-index GSI (Stage 4)
for this user's recent predictions across all their files, powering
the "Frequently Used" dashboard section (master reference §12).

GSI shape (Stage 4, locked):
  PK: user_id
  SK: prediction_timestamp_id ("<ISO8601 timestamp>#<prediction_id>")

Queried in descending SK order (most recent first) with a Limit —
never a table Scan.

After GSI query, uses BatchGetItem on the base table to fetch top_reasons
for each prediction (not projected in the GSI to avoid destroy/recreate).

IAM: dynamodb:Query on the predictions table + user-index GSI,
     dynamodb:BatchGetItem on the predictions table base.
"""

import json
import logging
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RESULT_LIMIT = 20
BATCH_GET_MAX_RETRIES = 3
BATCH_GET_RETRY_BACKOFF = 0.1

# Lazy-initialized DynamoDB resources (for testability)
_table_cache = None
_client_cache = None


def _get_predictions_table_name():
    """Get the predictions table name from environment."""
    return os.environ["PREDICTIONS_TABLE"]


def _get_table():
    """Lazy getter for DynamoDB table resource (cached)."""
    global _table_cache
    if _table_cache is None:
        dynamodb = boto3.resource("dynamodb")
        _table_cache = dynamodb.Table(_get_predictions_table_name())
    return _table_cache


def _get_client():
    """Lazy getter for DynamoDB low-level client (cached)."""
    global _client_cache
    if _client_cache is None:
        _client_cache = boto3.client("dynamodb")
    return _client_cache


def _reset_cache():
    """Reset cached DynamoDB resources (for testing only)."""
    global _table_cache, _client_cache
    _table_cache = None
    _client_cache = None


def _decimal_default(obj):
    # DynamoDB's boto3 resource interface returns numeric attributes
    # (like p_access) as Decimal, which json.dumps() cannot serialize
    # natively. Convert to float for the JSON response — acceptable
    # precision loss for a probability value returned to the client.
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body_dict, default=_decimal_default),
    }


def _get_authenticated_user_id(event):
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        return claims["sub"]
    except (KeyError, TypeError):
        return None


def _fetch_top_reasons_batch(prediction_ids: list[str]) -> dict[str, list]:
    """
    Fetch top_reasons for given prediction_ids using BatchGetItem on the base table.
    Returns a dict mapping prediction_id -> top_reasons list.
    Handles UnprocessedKeys with bounded retry. Fails open on errors.
    """
    if not prediction_ids:
        return {}

    client = _get_client()
    keys = [{"prediction_id": {"S": pid}} for pid in prediction_ids]
    
    request_items = {
        _get_predictions_table_name(): {
            "Keys": keys,
            "ProjectionExpression": "prediction_id, top_reasons"
        }
    }

    top_reasons_map: dict[str, list] = {}
    unprocessed_keys = request_items

    for attempt in range(BATCH_GET_MAX_RETRIES):
        try:
            response = client.batch_get_item(RequestItems=unprocessed_keys)
            
            # Process returned items
            table_name = _get_predictions_table_name()
            for item in response.get("Responses", {}).get(table_name, []):
                pid = item.get("prediction_id", {}).get("S")
                reasons_attr = item.get("top_reasons", {})
                
                if pid:
                    if "L" in reasons_attr:
                        # Parse list format from DynamoDB
                        reasons = []
                        for r in reasons_attr["L"]:
                            if "M" in r:
                                reason = r["M"]
                                reasons.append({
                                    "feature": reason.get("feature", {}).get("S", ""),
                                    "contribution": reason.get("contribution", {}).get("S", ""),
                                    "direction": reason.get("direction", {}).get("S", "")
                                })
                        top_reasons_map[pid] = reasons
                    else:
                        top_reasons_map[pid] = []
            
            # Check for unprocessed keys
            unprocessed_keys = response.get("UnprocessedKeys", {})
            if not unprocessed_keys:
                break
            
            # Small backoff before retry
            time.sleep(BATCH_GET_RETRY_BACKOFF * (attempt + 1))
            
        except ClientError as e:
            logger.warning(
                "frequently-used-fn: BatchGetItem attempt %d failed: %s. "
                "Failing open with empty top_reasons.",
                attempt + 1, e
            )
            # Fail open: return empty map for all prediction_ids
            return {pid: [] for pid in prediction_ids}
    
    # If we still have unprocessed keys after max retries, fail open for those
    if unprocessed_keys:
        logger.warning(
            "frequently-used-fn: BatchGetItem still has UnprocessedKeys after %d attempts. "
            "Failing open with empty top_reasons for remaining items.",
            BATCH_GET_MAX_RETRIES
        )
        for pid in prediction_ids:
            if pid not in top_reasons_map:
                top_reasons_map[pid] = []
    
    # Ensure all prediction_ids have an entry (empty if not found)
    for pid in prediction_ids:
        if pid not in top_reasons_map:
            top_reasons_map[pid] = []
    
    return top_reasons_map


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("frequently-used-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    try:
        result = _get_table().query(
            IndexName="user-index",
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,  # most recent predictions first
            Limit=RESULT_LIMIT,
        )
    except ClientError as e:
        logger.error("frequently-used-fn: Query error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})

    items = result.get("Items", [])
    prediction_ids = [item.get("prediction_id") for item in items if item.get("prediction_id")]
    
    # Fetch top_reasons via BatchGetItem on base table
    top_reasons_map = _fetch_top_reasons_batch(prediction_ids)
    
    predictions = [
        {
            "fileId": item.get("file_id"),
            "pAccess": item.get("p_access"),
            "candidateTiers": item.get("candidate_tiers"),
            "banditChoice": item.get("bandit_choice"),
            "predictionTimestamp": item.get("prediction_timestamp"),
            "topReasons": top_reasons_map.get(item.get("prediction_id"), []),
        }
        for item in items
    ]

    logger.info("frequently-used-fn: user_id=%s returned %d predictions", user_id, len(predictions))
    return _response(200, {"predictions": predictions})
