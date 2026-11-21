"""Aggregate real, user-scoped ASCOS file, prediction, and access data."""

import json
import logging
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ACCESS_TYPES = {"read", "write", "download", "share"}
_resources = {}


def _get_resource(name):
    if name not in _resources:
        if name == "s3":
            _resources[name] = boto3.client("s3")
        else:
            _resources[name] = boto3.resource("dynamodb").Table(os.environ[name])
    return _resources[name]


def _reset_resources():
    _resources.clear()


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=lambda value: float(value) if isinstance(value, Decimal) else value),
    }


def _user_id(event):
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _tier(storage_class):
    if storage_class in {"STANDARD_IA", "ONEZONE_IA"}:
        return "WARM"
    if storage_class in {"GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"}:
        return "COLD"
    if storage_class in {"STANDARD", None}:
        return "HOT"
    return None


def _file_type(filename):
    if not filename or "." not in filename.rsplit("/", 1)[-1]:
        return "Other"
    return filename.rsplit(".", 1)[-1].lower() or "Other"


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _query_all(table, **kwargs):
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def _list_user_files(user_id):
    s3 = _get_resource("s3")
    bucket = os.environ["S3_BUCKET_NAME"]
    prefix = f"{user_id}/"
    files = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            file_id = key[len(prefix):]
            if not file_id or "/" in file_id:
                continue
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
            except ClientError as error:
                logger.warning("analytics-summary-fn: HeadObject failed for %s: %s", key, error)
                head = {}
            metadata = head.get("Metadata", {})
            tier = _tier(head.get("StorageClass", obj.get("StorageClass", "STANDARD")))
            files.append({
                "file_id": file_id,
                "size": int(obj.get("Size", 0)),
                "tier": tier,
                "filename": metadata.get("filename"),
                "created_at": _parse_timestamp(metadata.get("uploaded-at")),
            })
    return files


def _access_rows(user_id, start_day, end_day):
    if not os.environ.get("ACCESS_EVENT_TABLE"):
        return []
    table = _get_resource("ACCESS_EVENT_TABLE")
    start_key = f"{start_day.isoformat()}T00:00:00"
    end_key = f"{(end_day + timedelta(days=1)).isoformat()}T00:00:00"
    try:
        return _query_all(
            table,
            KeyConditionExpression="#user_id = :user_id AND #timestamp_event_id BETWEEN :start_key AND :end_key",
            ExpressionAttributeNames={
                "#user_id": "user_id",
                "#timestamp_event_id": "timestamp_event_id",
            },
            ExpressionAttributeValues={
                ":user_id": user_id,
                ":start_key": start_key,
                ":end_key": end_key,
            },
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            logger.warning("analytics-summary-fn: access-event table is unavailable")
            return []
        raise


def _prediction_rows(user_id):
    return _query_all(
        _get_resource("PREDICTIONS_TABLE"),
        IndexName="user-index",
        KeyConditionExpression="#user_id = :user_id",
        ExpressionAttributeNames={"#user_id": "user_id"},
        ExpressionAttributeValues={":user_id": user_id},
        ScanIndexForward=False,
    )


def _latest_predictions(rows):
    latest = {}
    for row in rows:
        file_id = row.get("file_id")
        if not file_id:
            continue
        timestamp = row.get("prediction_timestamp") or row.get("prediction_timestamp_id", "")
        if file_id not in latest or timestamp > latest[file_id][0]:
            latest[file_id] = (timestamp, row)
    return {file_id: pair[1] for file_id, pair in latest.items()}


def _storage_rates():
    rates = {}
    for tier in ("HOT", "WARM", "COLD"):
        try:
            rate = float(os.environ[f"STORAGE_RATE_{tier}_PER_GB_MONTH"])
        except (KeyError, ValueError):
            return None
        if not math.isfinite(rate) or rate < 0:
            return None
        rates[tier] = rate
    return rates


def _summary(files, access_rows, prediction_rows, today):
    tiers = {}
    types = {}
    for file in files:
        tier = file["tier"]
        if tier:
            bucket = tiers.setdefault(tier, {"tier": tier, "files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += file["size"]
        file_type = _file_type(file["filename"])
        types[file_type] = types.get(file_type, 0) + 1

    storage_over_time = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        end_of_day = datetime.combine(day, time.max, tzinfo=timezone.utc)
        total = sum(file["size"] for file in files if file["created_at"] and file["created_at"] <= end_of_day)
        storage_over_time.append({"day": day.isoformat(), "bytes": total})

    access_by_day = {}
    latest_event_date = None
    for row in access_rows:
        ts = _parse_timestamp(row.get("timestamp"))
        if ts and row.get("event_type") in ACCESS_TYPES:
            d = ts.date()
            if latest_event_date is None or d > latest_event_date:
                latest_event_date = d

    anchor = today
    if latest_event_date and (today - latest_event_date).days > 13:
        anchor = latest_event_date

    for offset in range(13, -1, -1):
        day = anchor - timedelta(days=offset)
        access_by_day[day.isoformat()] = {"day": day.isoformat(), "reads": 0, "writes": 0, "downloads": 0, "shares": 0}
    has_relevant_access = False
    for row in access_rows:
        timestamp = _parse_timestamp(row.get("timestamp"))
        event_type = row.get("event_type")
        if not timestamp or event_type not in ACCESS_TYPES:
            continue
        day_bucket = access_by_day.get(timestamp.date().isoformat())
        if day_bucket:
            has_relevant_access = True
            field = {"read": "reads", "write": "writes", "download": "downloads", "share": "shares"}[event_type]
            day_bucket[field] += 1

    latest = _latest_predictions(prediction_rows)
    file_by_id = {file["file_id"]: file for file in files}
    rates = _storage_rates()
    monthly_savings = 0.0
    if rates:
        for file_id, prediction in latest.items():
            current = file_by_id.get(file_id)
            predicted_tier = prediction.get("bandit_choice")
            if not current or not current["tier"] or predicted_tier not in rates:
                continue
            current_rate = rates[current["tier"]]
            predicted_rate = rates[predicted_tier]
            monthly_savings += current["size"] / (1024 ** 3) * (current_rate - predicted_rate)

    return {
        "tiers": sorted(tiers.values(), key=lambda row: row["tier"]),
        "types": sorted(
            ({"type": file_type, "files": count} for file_type, count in types.items()),
            key=lambda row: (-row["files"], row["type"]),
        ),
        "storageOverTime": storage_over_time,
        "access": list(access_by_day.values()) if has_relevant_access else [],
        "optimization": {"monthlySavings": round(monthly_savings, 6)} if prediction_rows and rates else None,
    }


def handler(event, context):
    user_id = _user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    today = datetime.now(timezone.utc).date()
    try:
        files = _list_user_files(user_id)
        access_rows = _access_rows(user_id, today - timedelta(days=89), today)
        prediction_rows = _prediction_rows(user_id)
        return _response(200, _summary(files, access_rows, prediction_rows, today))
    except (ClientError, KeyError) as error:
        logger.exception("analytics-summary-fn failed for user_id=%s: %s", user_id, error)
        return _response(500, {"error": "Internal server error"})