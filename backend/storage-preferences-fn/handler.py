"""Read and persist a user's storage execution preference."""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)
_resources = {}


def _table():
    name = "STORAGE_PREFERENCES_TABLE"
    if name not in _resources:
        _resources[name] = boto3.resource("dynamodb").Table(os.environ[name])
    return _resources[name]


def _response(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _user_id(event):
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _method(event):
    try:
        return event["requestContext"]["http"]["method"]
    except (KeyError, TypeError):
        return None


def handler(event, context):
    user_id = _user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = _method(event)
    try:
        table = _table()
        if method == "GET":
            result = table.get_item(Key={"user_id": user_id}, ConsistentRead=True)
            item = result.get("Item")
            return _response(200, {"auto_tier_enabled": item.get("auto_tier_enabled") is True if item else False})

        if method != "PUT":
            return _response(405, {"error": "Method not allowed"})

        raw_body = event.get("body")
        if not isinstance(raw_body, str) or not raw_body:
            return _response(400, {"error": "A JSON body is required"})
        try:
            body = json.loads(raw_body)
        except (TypeError, json.JSONDecodeError):
            return _response(400, {"error": "Invalid JSON body"})
        if not isinstance(body, dict) or set(body) != {"auto_tier_enabled"}:
            return _response(400, {"error": "auto_tier_enabled is required"})
        enabled = body["auto_tier_enabled"]
        if type(enabled) is not bool:
            return _response(400, {"error": "auto_tier_enabled must be a boolean"})

        # PutItem replaces the whole row. If a second setting is added, switch to read-merge-write or separately approve UpdateItem so this setting is not wiped.
        table.put_item(Item={
            "user_id": user_id,
            "auto_tier_enabled": enabled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return _response(200, {"auto_tier_enabled": enabled})
    except (ClientError, KeyError, ValueError) as error:
        logger.exception("storage-preferences-fn failed for user_id=%s: %s", user_id, error)
        return _response(500, {"error": "Internal server error"})
