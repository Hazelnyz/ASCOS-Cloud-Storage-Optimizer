import importlib.util
import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


MODULE_PATH = Path(__file__).parents[1] / "backend" / "cost-budget-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("cost_budget_handler", MODULE_PATH)
budget_handler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget_handler)


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("USER_BUDGETS_TABLE", "test-user-budgets")
    monkeypatch.setenv("BUDGET_MIN", "0")
    monkeypatch.setenv("BUDGET_MAX", "100")
    monkeypatch.setenv("BUDGET_STEP", "5")
    monkeypatch.setenv("ALERT_THRESHOLD_MIN", "1")
    monkeypatch.setenv("ALERT_THRESHOLD_MAX", "100")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-south-1")
        created = ddb.create_table(
            TableName=os.environ["USER_BUDGETS_TABLE"],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        budget_handler._reset_resources()
        yield created
        budget_handler._reset_resources()


def request(body, user_id="user-a"):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}, "http": {"method": "PUT"}},
        "body": json.dumps(body),
    }


def test_valid_budget_persists_for_jwt_user_only(table):
    result = budget_handler.handler(request({"budget": 25, "alert_threshold": 80, "user_id": "user-b"}), None)
    assert result["statusCode"] == 200
    assert table.get_item(Key={"user_id": "user-a"})["Item"]["budget"] == 25
    assert "Item" not in table.get_item(Key={"user_id": "user-b"})


@pytest.mark.parametrize("payload", [
    {"budget": -5, "alert_threshold": 80},
    {"budget": 105, "alert_threshold": 80},
    {"budget": 12, "alert_threshold": 80},
    {"budget": float("nan"), "alert_threshold": 80},
    {"budget": 10, "alert_threshold": 101},
    {"budget": "10", "alert_threshold": 80},
])
def test_invalid_budget_values_are_rejected(table, payload):
    result = budget_handler.handler(request(payload), None)
    assert result["statusCode"] == 400


def test_missing_auth_returns_401(table):
    result = budget_handler.handler({"body": json.dumps({"budget": 10, "alert_threshold": 80})}, None)
    assert result["statusCode"] == 401
