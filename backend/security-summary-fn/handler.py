"""Return real, user-scoped account security status and recent activity."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EVENT_TYPES = ("download", "write", "delete", "share")
ACTIVITY_QUERY_LIMIT = 5000
ACTIVITY_PAGE_SIZE = 500
DETECTION_QUERY_LIMIT = 5000
DETECTIONS_RETURN_LIMIT = 10
_tables = {}


def _table(env_name):
    if env_name not in _tables:
        _tables[env_name] = boto3.resource("dynamodb").Table(os.environ[env_name])
    return _tables[env_name]


def _reset_tables():
    _tables.clear()


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=lambda value: float(value) if isinstance(value, Decimal) else value),
    }


def _claims(event):
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
        return claims if isinstance(claims, dict) and claims.get("sub") else None
    except (KeyError, TypeError):
        return None


def _last_sign_in(auth_time):
    if auth_time is None:
        return None
    try:
        return datetime.fromtimestamp(float(auth_time), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_event_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _protected_count(user_id):
    table = _table("PROTECTED_FILES_TABLE")
    kwargs = {
        "KeyConditionExpression": "#user_id = :user_id",
        "ExpressionAttributeNames": {"#user_id": "user_id"},
        "ExpressionAttributeValues": {":user_id": user_id},
        "Select": "COUNT",
    }
    count = 0
    while True:
        response = table.query(**kwargs)
        count += response.get("Count", 0)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return count
        kwargs["ExclusiveStartKey"] = last_key


def _anomaly_summary(user_id, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    detections_table = _table("ANOMALY_DETECTIONS_TABLE")
    marker = detections_table.get_item(
        Key={"user_id": "_system", "sk": "last_run"},
        ProjectionExpression="#ran_at",
        ExpressionAttributeNames={"#ran_at": "ran_at"},
    ).get("Item", {})
    last_run = marker.get("ran_at")
    last_run_dt = _parse_event_timestamp(last_run)
    active = bool(last_run_dt and timedelta(0) <= now - last_run_dt <= timedelta(minutes=60))

    detection_start = (now - timedelta(days=90)).isoformat().replace("+00:00", "Z") + "#"
    detection_end = now.isoformat().replace("+00:00", "Z") + "#\uffff"
    expression_names = {
        "#user_id": "user_id", "#sk": "sk", "#rule": "rule", "#severity": "severity",
        "#status": "status", "#count": "count", "#threshold": "threshold", "#mode": "mode",
        "#window_start": "window_start", "#detected_at": "detected_at",
    }
    kwargs = {
        "KeyConditionExpression": "#user_id = :user_id AND #sk BETWEEN :start_key AND :end_key",
        "ExpressionAttributeNames": expression_names,
        "ExpressionAttributeValues": {
            ":user_id": user_id,
            ":start_key": detection_start,
            ":end_key": detection_end,
        },
        "ProjectionExpression": "#user_id, #sk, #rule, #severity, #status, #count, #threshold, #mode, #window_start, #detected_at",
        "ScanIndexForward": False,
        "Limit": 100,
    }
    result_detections = []
    open_count = 0
    read_count = 0
    last_key = None
    while read_count < DETECTION_QUERY_LIMIT:
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        response = detections_table.query(**kwargs)
        items = response.get("Items", [])
        read_count += len(items)
        for item in items:
            if item.get("user_id") == "_system":
                continue
            window_start = item.get("window_start") or item.get("sk", "").split("#", 1)[0]
            detected_at = item.get("detected_at") or window_start
            detected_at_dt = _parse_event_timestamp(detected_at)
            if detected_at_dt and detected_at_dt >= now - timedelta(hours=24):
                open_count += 1
            if len(result_detections) < DETECTIONS_RETURN_LIMIT:
                result_detections.append({
                    "rule": item.get("rule"),
                    "severity": item.get("severity"),
                    "status": item.get("status"),
                    "count": item.get("count", 0),
                    "threshold": item.get("threshold", 0),
                    "mode": item.get("mode"),
                    "windowStart": window_start,
                    "detectedAt": detected_at,
                })
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
    return {
        "status": "active" if active else "not_connected",
        "rule": "baseline",
        "lastRun": last_run if last_run_dt else None,
        "openCount": open_count,
        "detections": result_detections,
    }


def _activity_counts(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    start_7d = now - timedelta(days=7)
    start_24h = now - timedelta(hours=24)
    counts_24h = {event_type: 0 for event_type in EVENT_TYPES}
    counts_7d = {event_type: 0 for event_type in EVENT_TYPES}
    table = _table("ACCESS_EVENT_TABLE")
    kwargs = {
        "KeyConditionExpression": "#user_id = :user_id AND #timestamp_event_id BETWEEN :start_key AND :end_key",
        "ExpressionAttributeNames": {
            "#user_id": "user_id",
            "#timestamp_event_id": "timestamp_event_id",
            "#event_type": "event_type",
            "#timestamp": "timestamp",
        },
        "ExpressionAttributeValues": {
            ":user_id": user_id,
            ":start_key": start_7d.strftime("%Y-%m-%dT%H:%M:%S"),
            ":end_key": now.strftime("%Y-%m-%dT%H:%M:%S") + "Z\uffff",
        },
        "ProjectionExpression": "#event_type, #timestamp, #timestamp_event_id",
        "ScanIndexForward": False,
        "Limit": ACTIVITY_PAGE_SIZE,
    }
    scanned = 0
    last_key = None
    while scanned < ACTIVITY_QUERY_LIMIT:
        kwargs["Limit"] = min(ACTIVITY_PAGE_SIZE, ACTIVITY_QUERY_LIMIT - scanned)
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        response = table.query(**kwargs)
        items = response.get("Items", [])
        scanned += len(items)
        for item in items:
            event_type = item.get("event_type")
            if event_type not in counts_7d:
                continue
            timestamp = _parse_event_timestamp(item.get("timestamp"))
            if timestamp is None:
                sort_key_timestamp = item.get("timestamp_event_id", "").split("#", 1)[0]
                timestamp = _parse_event_timestamp(sort_key_timestamp)
            if timestamp is None or timestamp < start_7d or timestamp > now:
                continue
            counts_7d[event_type] += 1
            if timestamp >= start_24h:
                counts_24h[event_type] += 1
        last_key = response.get("LastEvaluatedKey")
        if not last_key or not items:
            break
    return {
        "last24h": counts_24h,
        "last7d": counts_7d,
        "truncated": scanned >= ACTIVITY_QUERY_LIMIT,
    }


def handler(event, context):
    claims = _claims(event)
    if not claims:
        return _response(401, {"error": "Unauthorized"})

    user_id = claims["sub"]
    try:
        anomaly = _anomaly_summary(user_id)
        body = {
            "authentication": {
                "provider": "Cognito",
                "lastSignIn": _last_sign_in(claims.get("auth_time")),
            },
            "protectedFiles": {"count": _protected_count(user_id)},
            "anomaly": {key: value for key, value in anomaly.items() if key != "detections"},
            "detections": anomaly["detections"],
            "activity": _activity_counts(user_id),
        }
        return _response(200, body)
    except ClientError as error:
        logger.exception("security-summary-fn failed for user_id=%s: %s", user_id, error)
        return _response(500, {"error": "Internal server error"})