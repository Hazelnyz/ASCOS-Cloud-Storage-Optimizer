"""JWT-scoped per-user cost estimate for the Cost & Budget page."""

import json
import logging
import math
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_resources = {}
TIERS = ("HOT", "WARM", "COLD")
QUERY_PAGE_SIZE = 100
STORAGE_CLASS_TIER = {"STANDARD": "HOT", "STANDARD_IA": "WARM", "GLACIER_IR": "COLD"}


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
        user_id = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
        return user_id if isinstance(user_id, str) and user_id else None
    except (KeyError, TypeError):
        return None


def _list_user_objects(user_id):
    """List only the JWT subject's direct S3 prefix; paginator follows every page."""
    s3 = _get_resource("s3")
    prefix = f"{user_id}/"
    objects = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=os.environ["S3_BUCKET_NAME"], Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            file_id = key[len(prefix):]
            if not file_id:
                continue
            tier = STORAGE_CLASS_TIER.get(obj.get("StorageClass", "STANDARD"))
            if tier:
                objects[file_id] = {"size": int(obj.get("Size", 0)), "tier": tier}
    return objects


def _query_all_pages(table, user_id, month_prefix):
    rows = []
    query = {
        "KeyConditionExpression": Key("user_id").eq(user_id) & Key("timestamp_event_id").begins_with(month_prefix),
        "Limit": QUERY_PAGE_SIZE,
    }
    while True:
        response = table.query(**query)
        rows.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return rows
        query["ExclusiveStartKey"] = last_key


def _query_access_events(user_id, month_prefix):
    return _query_all_pages(_get_resource("ACCESS_EVENT_TABLE"), user_id, month_prefix)


def _query_active_users(month_prefix):
    """Read one monthly marker per active user from the ALL partition (never Scan)."""
    rows = _query_all_pages(_get_resource("ACCESS_EVENT_TABLE"), "ALL", month_prefix)
    return {row["active_user_id"] for row in rows if row.get("event_type") == "active_user" and row.get("active_user_id")}


def _get_user_budget(user_id):
    response = _get_resource("USER_BUDGETS_TABLE").get_item(Key={"user_id": user_id})
    item = response.get("Item")
    if not item:
        return None
    return {"budget": float(item["budget"]), "alert_threshold": float(item["alert_threshold"])}


def _rate(name):
    value = float(os.environ[name])
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid configured rate: {name}")
    return value


def calculate_estimate(objects, events, rates, shared_overhead, active_users, user_id):
    storage = {tier: {"bytes": 0, "gb": 0.0, "rate": rates["storage"][tier], "cost": 0.0} for tier in TIERS}
    for obj in objects.values():
        storage[obj["tier"]]["bytes"] += obj["size"]
    for tier in TIERS:
        storage[tier]["gb"] = storage[tier]["bytes"] / (1024 ** 3)
        storage[tier]["cost"] = storage[tier]["gb"] * storage[tier]["rate"]

    request_counts = {"download": 0, "write": 0, "delete": 0}
    request_cost = 0.0
    retrieval_gb = {"warm": 0.0, "cold": 0.0}
    unmapped_requests = 0
    missing_transfer_bytes = 0
    for event in events:
        event_type = event.get("event_type")
        if event_type not in request_counts:
            continue
        request_counts[event_type] += 1
        if event_type == "delete":  # S3 DELETE requests are free at the configured rate.
            continue
        obj = objects.get(event.get("file_id", ""))
        if not obj:
            unmapped_requests += 1
            continue
        tier = obj["tier"]
        prefix = {"HOT": "standard", "WARM": "warm", "COLD": "cold"}[tier]
        operation = "read" if event_type == "download" else "write"
        request_cost += rates["requests"][f"{prefix}_{operation}"] / 1000
        if event_type == "download" and tier in ("WARM", "COLD"):
            transferred = event.get("bytes_transferred_out")
            if isinstance(transferred, (int, Decimal)) and transferred >= 0:
                retrieval_gb[tier.lower()] += int(transferred) / (1024 ** 3)
            else:
                missing_transfer_bytes += 1

    retrieval_cost = retrieval_gb["warm"] * rates["retrieval"]["warm"] + retrieval_gb["cold"] * rates["retrieval"]["cold"]
    shared_amount = None
    if shared_overhead is not None and active_users:
        shared_amount = shared_overhead / len(active_users) if user_id in active_users else 0.0
    request_and_retrieval = request_cost + retrieval_cost
    known_total = sum(storage[tier]["cost"] for tier in TIERS) + request_and_retrieval
    if shared_amount is not None:
        known_total += shared_amount

    breakdown = [
        {"category": "Storage - Hot", "amount": storage["HOT"]["cost"]},
        {"category": "Storage - Warm", "amount": storage["WARM"]["cost"]},
        {"category": "Storage - Cold", "amount": storage["COLD"]["cost"]},
        {"category": "Requests and retrieval", "amount": request_and_retrieval},
        {"category": "Shared overhead", "amount": shared_amount},
    ]
    return {
        "estimated_spent": known_total,
        "breakdown": breakdown,
        "storage_by_tier": storage,
        "request_counts": request_counts,
        "cold_retrieval_gb": retrieval_gb["cold"],
        "warm_retrieval_gb": retrieval_gb["warm"],
        "unmapped_request_events": unmapped_requests,
        "missing_transfer_byte_events": missing_transfer_bytes,
        "active_user_count": len(active_users),
    }


def _load_rates():
    return {
        "storage": {"HOT": _rate("STORAGE_RATE_HOT"), "WARM": _rate("STORAGE_RATE_WARM"), "COLD": _rate("STORAGE_RATE_COLD")},
        "requests": {
            "standard_write": _rate("REQUEST_RATE_STANDARD_WRITE"), "standard_read": _rate("REQUEST_RATE_STANDARD_READ"),
            "warm_write": _rate("REQUEST_RATE_WARM_WRITE"), "warm_read": _rate("REQUEST_RATE_WARM_READ"),
            "cold_write": _rate("REQUEST_RATE_COLD_WRITE"), "cold_read": _rate("REQUEST_RATE_COLD_READ"),
            "delete": _rate("REQUEST_RATE_DELETE"),
        },
        "retrieval": {"warm": _rate("RETRIEVAL_RATE_WARM"), "cold": _rate("RETRIEVAL_RATE_COLD")},
    }


def handler(event, context):
    user_id = _user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})
    try:
        now = datetime.now(timezone.utc)
        month_prefix = now.strftime("%Y-%m")
        objects = _list_user_objects(user_id)
        events = _query_access_events(user_id, month_prefix)
        active_users = _query_active_users(month_prefix)
        user_budget = _get_user_budget(user_id)
        shared_raw = os.environ.get("SHARED_OVERHEAD_MONTHLY", "")
        shared_overhead = float(shared_raw) if shared_raw else None
        if shared_overhead is not None and (not math.isfinite(shared_overhead) or shared_overhead < 0):
            raise ValueError("Invalid configured shared overhead")
        rates = _load_rates()
        estimate = calculate_estimate(objects, events, rates, shared_overhead, active_users, user_id)
        notes = (
            "WARM and COLD request rates and WARM/COLD retrieval rates use us-east-1 values and are unverified for ap-south-1; "
            "these parts are approximate. Retrieval GB uses CloudTrail bytesTransferredOut when present. "
            f"{estimate['unmapped_request_events']} request events could not be mapped to a current storage class; "
            f"{estimate['missing_transfer_byte_events']} WARM/COLD downloads lacked transfer-byte data. "
            "Shared overhead is a configured monthly estimate split equally among users with access events this month."
        )
        body = {
            "budget": user_budget["budget"] if user_budget else None,
            "alert_threshold": user_budget["alert_threshold"] if user_budget else None,
            **estimate,
            "rates_used": {**rates, "notes": notes},
            "computed_at": now.isoformat(),
            "ml_savings_estimate": None,
            "budget_config": {
                "min": float(os.environ["BUDGET_MIN"]), "max": float(os.environ["BUDGET_MAX"]),
                "step": float(os.environ["BUDGET_STEP"]),
                "alert_threshold_min": float(os.environ["ALERT_THRESHOLD_MIN"]),
                "alert_threshold_max": float(os.environ["ALERT_THRESHOLD_MAX"]),
            },
        }
        return _response(200, body)
    except (ClientError, KeyError, ValueError) as error:
        logger.exception("cost-summary-fn failed for user_id=%s: %s", user_id, error)
        return _response(500, {"error": "Internal server error"})
