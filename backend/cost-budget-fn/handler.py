"""Budget persistence for the Cost & Budget page."""

import json
import logging
import math
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_resources = {}


def _get_resource(name):
    if name not in _resources:
        _resources[name] = boto3.resource("dynamodb").Table(os.environ[name])
    return _resources[name]


def _reset_resources():
    _resources.clear()


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _user_id(event):
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def handler(event, context):
    user_id = _user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        try:
            body = json.loads(event.get("body", "{}"))
        except (TypeError, json.JSONDecodeError):
            return _response(400, {"error": "Invalid JSON body"})
        if not isinstance(body, dict):
            return _response(400, {"error": "A JSON object is required"})
        budget = body.get("budget")
        alert_threshold = body.get("alert_threshold")

        budget_min = float(os.environ["BUDGET_MIN"])
        budget_max = float(os.environ["BUDGET_MAX"])
        budget_step = float(os.environ["BUDGET_STEP"])
        alert_threshold_min = float(os.environ["ALERT_THRESHOLD_MIN"])
        alert_threshold_max = float(os.environ["ALERT_THRESHOLD_MAX"])

        if budget is None or alert_threshold is None:
            return _response(400, {"error": "budget and alert_threshold are required"})

        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            return _response(400, {"error": "budget must be a number"})
        if isinstance(alert_threshold, bool) or not isinstance(alert_threshold, (int, float)):
            return _response(400, {"error": "alert_threshold must be a number"})

        budget = float(budget)
        alert_threshold = float(alert_threshold)

        if not math.isfinite(budget) or not (budget_min <= budget <= budget_max):
            return _response(400, {"error": f"budget must be between {budget_min} and {budget_max}"})

        if budget_step <= 0 or not math.isclose((budget - budget_min) % budget_step, 0, abs_tol=1e-8):
            return _response(400, {"error": f"budget must use increments of {budget_step}"})

        if not math.isfinite(alert_threshold) or not (alert_threshold_min <= alert_threshold <= alert_threshold_max):
            return _response(400, {"error": f"alert_threshold must be between {alert_threshold_min} and {alert_threshold_max}"})

        table = _get_resource("USER_BUDGETS_TABLE")
        table.put_item(
            Item={
                "user_id": user_id,
                "budget": Decimal(str(budget)),
                "alert_threshold": Decimal(str(alert_threshold)),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        return _response(200, {"budget": budget, "alert_threshold": alert_threshold})

    except (ClientError, KeyError, ValueError) as error:
        logger.exception("cost-budget-fn failed for user_id=%s: %s", user_id, error)
        return _response(500, {"error": "Internal server error"})
