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

IAM: dynamodb:Query on the predictions table + user-index GSI.
"""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
PREDICTIONS_TABLE = os.environ["PREDICTIONS_TABLE"]
predictions_table = dynamodb.Table(PREDICTIONS_TABLE)

RESULT_LIMIT = 20


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


def handler(event, context):
    user_id = _get_authenticated_user_id(event)
    if not user_id:
        logger.warning("frequently-used-fn: missing/invalid JWT claims")
        return _response(401, {"error": "Unauthorized"})

    try:
        result = predictions_table.query(
            IndexName="user-index",
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,  # most recent predictions first
            Limit=RESULT_LIMIT,
        )
    except ClientError as e:
        logger.error("frequently-used-fn: Query error for user_id=%s: %s", user_id, e)
        return _response(500, {"error": "Internal server error"})

    items = result.get("Items", [])
    predictions = [
        {
            "fileId": item.get("file_id"),
            "pAccess": item.get("p_access"),
            "candidateTiers": item.get("candidate_tiers"),
            "banditChoice": item.get("bandit_choice"),
            "predictionTimestamp": item.get("prediction_timestamp"),
        }
        for item in items
    ]

    logger.info("frequently-used-fn: user_id=%s returned %d predictions", user_id, len(predictions))
    return _response(200, {"predictions": predictions})
