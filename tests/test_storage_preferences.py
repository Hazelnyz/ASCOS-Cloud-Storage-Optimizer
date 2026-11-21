import importlib.util
import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


MODULE_PATH = Path(__file__).parents[1] / "backend" / "storage-preferences-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("storage_preferences_handler", MODULE_PATH)
preferences_handler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preferences_handler)


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("STORAGE_PREFERENCES_TABLE", "test-storage-preferences")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-south-1")
        created = ddb.create_table(
            TableName=os.environ["STORAGE_PREFERENCES_TABLE"],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        preferences_handler._resources.clear()
        yield created
        preferences_handler._resources.clear()


def request(method="GET", body=None, user_id="user-a"):
    return {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": user_id}}},
            "http": {"method": method},
        },
        "body": body,
    }


def response(result):
    return json.loads(result["body"])


def test_get_defaults_to_false_and_put_persists_for_jwt_user(table):
    assert response(preferences_handler.handler(request(), None)) == {"auto_tier_enabled": False}
    result = preferences_handler.handler(request("PUT", json.dumps({"auto_tier_enabled": False})), None)
    assert result["statusCode"] == 200
    assert table.get_item(Key={"user_id": "user-a"})["Item"]["auto_tier_enabled"] is False
    result = preferences_handler.handler(request("PUT", json.dumps({"auto_tier_enabled": True})), None)
    assert result["statusCode"] == 200
    assert response(preferences_handler.handler(request(), None)) == {"auto_tier_enabled": True}
    assert "Item" not in table.get_item(Key={"user_id": "user-b"})


@pytest.mark.parametrize("body", [None, "", "{", "null", "{}", '{"auto_tier_enabled": 1}', '{"auto_tier_enabled": "false"}', '{"auto_tier_enabled": null}'])
def test_missing_malformed_or_non_boolean_body_returns_400(table, body):
    result = preferences_handler.handler(request("PUT", body), None)
    assert result["statusCode"] == 400


def test_missing_auth_returns_401(table):
    assert preferences_handler.handler({"requestContext": {"http": {"method": "GET"}}}, None)["statusCode"] == 401
