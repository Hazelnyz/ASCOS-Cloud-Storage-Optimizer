"""Scheduled per-user hourly volume anomaly scoring over real access events."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

SECURITY_STATE_TABLE = os.environ.get("SECURITY_STATE_TABLE")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
ACCESS_EVENT_TABLE = os.environ.get("ACCESS_EVENT_TABLE")
ANOMALY_DETECTIONS_TABLE = os.environ.get("ANOMALY_DETECTIONS_TABLE")

MAX_SCAN_ITEMS = 50_000
SCAN_PAGE_SIZE = 1_000
BASELINE_HOURS = 14 * 24
LEARNING_HOURS = 72
SCORED_RULES = {
    "download_volume": "download",
    "delete_volume": "delete",
}
SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3}
DEFAULT_CONFIG = {
    "min_floor": 10,
    "std_mult": 3.0,
    "sev_medium_ratio": 2.0,
    "sev_high_ratio": 4.0,
}


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _floor_hour(value):
    value = _utc(value)
    return value.replace(minute=0, second=0, microsecond=0)


def _parse_timestamp(value):
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str):
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _population_stats(values):
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance)


def _severity_for_ratio(ratio, config):
    if ratio >= config["sev_high_ratio"]:
        return "High"
    if ratio >= config["sev_medium_ratio"]:
        return "Medium"
    if ratio >= 1:
        return "Low"
    return None


def score_events(events, now, config=None):
    """Purely score supplied access rows; timestamps and `now` are UTC-aware."""
    now = _utc(now)
    settings = {**DEFAULT_CONFIG, **(config or {})}
    current_hour = _floor_hour(now)
    range_start = current_hour - timedelta(hours=BASELINE_HOURS)
    grouped = defaultdict(list)
    for event in events:
        timestamp = _parse_timestamp(event.get("timestamp"))
        user_id = event.get("user_id")
        event_type = event.get("event_type")
        if not user_id or user_id == "_system" or not timestamp:
            continue
        if timestamp < now - timedelta(days=14) or timestamp > now:
            continue
        grouped[user_id].append((timestamp, event_type))

    detections = []
    for user_id, user_events in grouped.items():
        first_event = min(timestamp for timestamp, _ in user_events)
        baseline_start = max(range_start, _floor_hour(first_event))
        baseline_hours = max(0, int((current_hour - baseline_start).total_seconds() // 3600))
        mode = "learning" if now - first_event < timedelta(hours=LEARNING_HOURS) else "baseline"

        for rule, event_type in SCORED_RULES.items():
            current_count = sum(
                1 for timestamp, kind in user_events
                if kind == event_type and current_hour <= timestamp < current_hour + timedelta(hours=1)
            )
            if not current_count:
                continue

            hourly_counts = [0] * baseline_hours
            for timestamp, kind in user_events:
                if kind != event_type:
                    continue
                hour = _floor_hour(timestamp)
                if baseline_start <= hour < current_hour:
                    index = int((hour - baseline_start).total_seconds() // 3600)
                    hourly_counts[index] += 1
            mean, std = _population_stats(hourly_counts)
            if mode == "learning":
                threshold = float(settings["min_floor"])
            else:
                threshold = max(float(settings["min_floor"]), mean + float(settings["std_mult"]) * std)
            ratio = current_count / threshold if threshold else math.inf
            severity = _severity_for_ratio(ratio, settings)
            if severity is None:
                continue
            detections.append({
                "user_id": user_id,
                "sk": f"{current_hour.isoformat().replace('+00:00', 'Z')}#{rule}",
                "rule": rule,
                "severity": severity,
                "count": current_count,
                "threshold": threshold,
                "baseline_mean": mean,
                "mode": mode,
                "window_start": current_hour.isoformat().replace("+00:00", "Z"),
                "detected_at": now.isoformat().replace("+00:00", "Z"),
                "status": "Logged",
                "expires_at": int((now + timedelta(days=90)).timestamp()),
            })
    return detections


def _config_from_env():
    return {
        "min_floor": int(os.environ.get("MIN_FLOOR", DEFAULT_CONFIG["min_floor"])),
        "std_mult": float(os.environ.get("STD_MULT", DEFAULT_CONFIG["std_mult"])),
        "sev_medium_ratio": float(os.environ.get("SEV_MEDIUM_RATIO", DEFAULT_CONFIG["sev_medium_ratio"])),
        "sev_high_ratio": float(os.environ.get("SEV_HIGH_RATIO", DEFAULT_CONFIG["sev_high_ratio"])),
    }


def _decimal(value):
    return Decimal(str(value))


def _detection_item(detection):
    return {
        **detection,
        "count": _decimal(detection["count"]),
        "threshold": _decimal(detection["threshold"]),
        "baseline_mean": _decimal(detection["baseline_mean"]),
    }


def _persist_detection(table, detection):
    item = _detection_item(detection)
    names = {"#user_id": "user_id", "#sk": "sk"}
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#user_id) AND attribute_not_exists(#sk)",
            ExpressionAttributeNames=names,
        )
        return "created"
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise

    key = {"user_id": detection["user_id"], "sk": detection["sk"]}
    count_names = {
        "#user_id": "user_id", "#count": "count", "#threshold": "threshold",
        "#baseline_mean": "baseline_mean", "#mode": "mode", "#detected_at": "detected_at",
        "#expires_at": "expires_at",
    }
    count_values = {
        ":count": item["count"], ":threshold": item["threshold"],
        ":baseline_mean": item["baseline_mean"], ":mode": item["mode"],
        ":detected_at": item["detected_at"], ":expires_at": item["expires_at"],
    }
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET #count=:count, #threshold=:threshold, #baseline_mean=:baseline_mean, #mode=:mode, #detected_at=:detected_at, #expires_at=:expires_at",
            ConditionExpression="attribute_exists(#user_id) AND #count < :count",
            ExpressionAttributeNames=count_names,
            ExpressionAttributeValues=count_values,
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return "unchanged"
        raise

    existing_severities = [severity for severity, rank in SEVERITY_RANK.items() if rank < SEVERITY_RANK[detection["severity"]]]
    if existing_severities:
        severity_names = {"#user_id": "user_id", "#severity": "severity"}
        severity_values = {":new_severity": detection["severity"]}
        allowed = []
        for index, severity in enumerate(existing_severities):
            token = f":old_severity_{index}"
            severity_values[token] = severity
            allowed.append(f"#severity = {token}")
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET #severity=:new_severity",
                ConditionExpression="attribute_exists(#user_id) AND (" + " OR ".join(allowed) + ")",
                ExpressionAttributeNames=severity_names,
                ExpressionAttributeValues=severity_values,
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    return "updated"


def _scan_recent_events(now):
    table = dynamodb.Table(ACCESS_EVENT_TABLE)
    cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    kwargs = {
        "FilterExpression": "#timestamp >= :cutoff",
        "ProjectionExpression": "#user_id, #event_type, #timestamp",
        "ExpressionAttributeNames": {
            "#user_id": "user_id",
            "#event_type": "event_type",
            "#timestamp": "timestamp",
        },
        "ExpressionAttributeValues": {":cutoff": cutoff},
    }
    events = []
    scanned = 0
    last_key = None
    while scanned < MAX_SCAN_ITEMS:
        kwargs["Limit"] = min(SCAN_PAGE_SIZE, MAX_SCAN_ITEMS - scanned)
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        page = table.scan(**kwargs)
        events.extend(page.get("Items", []))
        scanned += page.get("ScannedCount", len(page.get("Items", [])))
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            return events, scanned, False
    logger.warning("anomaly-scorer-fn scan reached %d-item cap; scoring collected rows", MAX_SCAN_ITEMS)
    return events, scanned, True


def handler(event, context):
    now = datetime.now(timezone.utc)
    events, scanned, truncated = _scan_recent_events(now)
    detections = score_events(events, now, _config_from_env())
    table = dynamodb.Table(ANOMALY_DETECTIONS_TABLE)
    created = 0
    updated = 0
    for detection in detections:
        result = _persist_detection(table, detection)
        created += result == "created"
        updated += result == "updated"

    # The marker is last: its presence means the preceding scan/scoring/writes completed.
    table.put_item(Item={
        "user_id": "_system",
        "sk": "last_run",
        "ran_at": now.isoformat().replace("+00:00", "Z"),
    })
    users = len({event.get("user_id") for event in events if event.get("user_id") and event.get("user_id") != "_system"})
    logger.info(
        "anomaly-scorer-fn completed users=%d detections=%d created=%d updated=%d scanned=%d truncated=%s",
        users, len(detections), created, updated, scanned, truncated,
    )
    return {
        "status": "completed", "users": users, "detections": len(detections),
        "created": created, "updated": updated, "scanned": scanned, "truncated": truncated,
    }


def _extract_user_id(detail):
    request_params = detail.get("requestParameters") or {}
    object_key = request_params.get("key") or ""
    if "/" not in object_key:
        return None
    user_id = object_key.split("/", 1)[0]
    return user_id or None


def _contain_user(user_id):
    """STAGE 10 ACTIVATION PATH — not called by Stage 7's handler."""
    if not user_id or not SECURITY_STATE_TABLE:
        logger.warning("Cannot contain — missing user_id or SECURITY_STATE_TABLE")
        return
    dynamodb.Table(SECURITY_STATE_TABLE).put_item(Item={"user_id": user_id})
    logger.info("Wrote containment row for user=%s", user_id)


def _publish_alert(user_id, detail):
    """STAGE 10 ACTIVATION PATH — not called by Stage 7's handler."""
    if not SNS_TOPIC_ARN:
        logger.warning("Cannot publish alert — SNS_TOPIC_ARN not set")
        return
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject="ASCOS — High severity anomaly detected",
        Message=json.dumps({"user_id": user_id, "detail": detail}, default=str),
    )
    logger.info("Published High-severity alert for user=%s", user_id)