import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


MODULE_PATH = Path(__file__).parents[1] / "backend" / "cost-summary-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("cost_summary_handler", MODULE_PATH)
cost = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cost)


def event_for(user_id):
    return {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}}}


def rates_env(monkeypatch):
    values = {
        "S3_BUCKET_NAME": "cost-test-bucket", "ACCESS_EVENT_TABLE": "cost-test-events", "USER_BUDGETS_TABLE": "cost-test-budgets",
        "STORAGE_RATE_HOT": "0.025", "STORAGE_RATE_WARM": "0.0138", "STORAGE_RATE_COLD": "0.005",
        "REQUEST_RATE_STANDARD_WRITE": "0.005", "REQUEST_RATE_STANDARD_READ": "0.0004",
        "REQUEST_RATE_WARM_WRITE": "0.01", "REQUEST_RATE_WARM_READ": "0.001",
        "REQUEST_RATE_COLD_WRITE": "0.02", "REQUEST_RATE_COLD_READ": "0.01", "REQUEST_RATE_DELETE": "0",
        "RETRIEVAL_RATE_WARM": "0.01", "RETRIEVAL_RATE_COLD": "0.03", "SHARED_OVERHEAD_MONTHLY": "6",
        "BUDGET_MIN": "0", "BUDGET_MAX": "10000", "BUDGET_STEP": "5",
        "ALERT_THRESHOLD_MIN": "1", "ALERT_THRESHOLD_MAX": "100",
    }
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def aws(monkeypatch):
    rates_env(monkeypatch)
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(Bucket=os.environ["S3_BUCKET_NAME"], CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        ddb = boto3.resource("dynamodb", region_name="ap-south-1")
        events = ddb.create_table(
            TableName=os.environ["ACCESS_EVENT_TABLE"],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}, {"AttributeName": "timestamp_event_id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}, {"AttributeName": "timestamp_event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        budgets = ddb.create_table(
            TableName=os.environ["USER_BUDGETS_TABLE"],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        cost._reset_resources()
        yield s3, events, budgets
        cost._reset_resources()


def current_sort_key(file_id):
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m')}-{now.day:02d}T12:00:00Z#{file_id}"


def test_empty_user_has_zero_estimate_and_no_cross_user_overhead(aws):
    s3, events, _ = aws
    events.put_item(Item={"user_id": "ALL", "timestamp_event_id": current_sort_key("b") + "#ACTIVE#other", "event_type": "active_user", "active_user_id": "other"})
    result = json.loads(cost.handler(event_for("empty-user"), None)["body"])
    assert result["estimated_spent"] == 0
    assert result["budget"] is None
    assert result["breakdown"][-1]["amount"] == 0
    assert result["active_user_count"] == 1
    assert all(result["storage_by_tier"][tier]["bytes"] == 0 for tier in ("HOT", "WARM", "COLD"))


def test_user_with_all_tiers_and_recorded_requests_gets_scoped_estimate(aws):
    s3, events, budgets = aws
    prefix = "user-a/"
    s3.put_object(Bucket=os.environ["S3_BUCKET_NAME"], Key=prefix + "hot.txt", Body=b"a", StorageClass="STANDARD")
    s3.put_object(Bucket=os.environ["S3_BUCKET_NAME"], Key=prefix + "warm.txt", Body=b"b", StorageClass="STANDARD_IA")
    s3.put_object(Bucket=os.environ["S3_BUCKET_NAME"], Key=prefix + "cold.txt", Body=b"c", StorageClass="GLACIER_IR")
    s3.put_object(Bucket=os.environ["S3_BUCKET_NAME"], Key="user-b/secret.txt", Body=b"secret", StorageClass="GLACIER_IR")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    events.put_item(Item={"user_id": "user-a", "timestamp_event_id": f"{month}-01T01:00:00Z#download", "file_id": "cold.txt", "event_type": "download", "bytes_transferred_out": 1073741824})
    events.put_item(Item={"user_id": "user-a", "timestamp_event_id": f"{month}-02T01:00:00Z#write", "file_id": "hot.txt", "event_type": "write"})
    events.put_item(Item={"user_id": "user-a", "timestamp_event_id": f"{month}-03T01:00:00Z#delete", "file_id": "gone.txt", "event_type": "delete"})
    events.put_item(Item={"user_id": "user-b", "timestamp_event_id": f"{month}-01T01:00:00Z#b-download", "file_id": "secret.txt", "event_type": "download", "bytes_transferred_out": 10737418240})
    events.put_item(Item={"user_id": "ALL", "timestamp_event_id": f"{month}#ACTIVE#user-a", "event_type": "active_user", "active_user_id": "user-a"})
    events.put_item(Item={"user_id": "ALL", "timestamp_event_id": f"{month}#ACTIVE#user-b", "event_type": "active_user", "active_user_id": "user-b"})
    budgets.put_item(Item={"user_id": "user-a", "budget": 75, "alert_threshold": 80})

    response = cost.handler(event_for("user-a"), None)
    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["storage_by_tier"]["HOT"]["bytes"] == 1
    assert result["storage_by_tier"]["WARM"]["bytes"] == 1
    assert result["storage_by_tier"]["COLD"]["bytes"] == 1
    assert result["request_counts"] == {"download": 1, "write": 1, "delete": 1}
    assert result["cold_retrieval_gb"] == pytest.approx(1)
    assert result["budget"] == 75
    assert result["breakdown"][-1]["amount"] == 3
    assert result["ml_savings_estimate"] is None
    assert "unverified for ap-south-1" in result["rates_used"]["notes"]
    assert result["storage_by_tier"]["COLD"]["bytes"] == 1  # never includes user-b's object


def test_access_event_query_paginates_without_scan(aws, monkeypatch):
    _, events, _ = aws
    monkeypatch.setattr(cost, "QUERY_PAGE_SIZE", 10, raising=False)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    for index in range(25):
        events.put_item(Item={"user_id": "user-a", "timestamp_event_id": f"{month}-01T00:00:{index:02d}Z#{index}", "event_type": "delete"})
    rows = cost._query_access_events("user-a", month)
    assert len(rows) == 25


def test_missing_auth_returns_401(aws):
    response = cost.handler({}, None)
    assert response["statusCode"] == 401
