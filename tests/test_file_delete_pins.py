"""Focused tests for file-delete-fn's best-effort protected pin cleanup."""
import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "backend" / "file-delete-fn" / "handler.py"
BUCKET = "test-file-delete-pins"
TABLE_NAME = "test-protected-files"


def _load_handler():
    spec = importlib.util.spec_from_file_location("file_delete_handler_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def aws_resources(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("S3_BUCKET_NAME", BUCKET)
    monkeypatch.setenv("PROTECTED_FILES_TABLE", TABLE_NAME)
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "file_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "file_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield _load_handler(), s3, table


def _event(user_id, file_id):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}},
        "pathParameters": {"fileId": file_id},
    }


def _seed_file(s3, user_id, file_id):
    s3.put_object(Bucket=BUCKET, Key=f"{user_id}/{file_id}", Body=b"data")


def _pin(table, user_id, file_id):
    table.put_item(Item={"user_id": user_id, "file_id": file_id})


def _has_pin(table, user_id, file_id):
    return "Item" in table.get_item(Key={"user_id": user_id, "file_id": file_id})


def test_deleting_protected_file_removes_its_pin_row(aws_resources):
    handler, s3, table = aws_resources
    _seed_file(s3, "user-a", "file-1")
    _pin(table, "user-a", "file-1")

    response = handler.handler(_event("user-a", "file-1"), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"fileId": "file-1", "deleted": True}
    assert not _has_pin(table, "user-a", "file-1")


def test_deleting_unprotected_file_still_succeeds(aws_resources):
    handler, s3, table = aws_resources
    _seed_file(s3, "user-a", "file-2")

    response = handler.handler(_event("user-a", "file-2"), None)

    assert response["statusCode"] == 200
    assert not _has_pin(table, "user-a", "file-2")


def test_pin_row_failure_does_not_fail_successful_file_delete(aws_resources, monkeypatch):
    handler, s3, table = aws_resources
    _seed_file(s3, "user-a", "file-3")
    _pin(table, "user-a", "file-3")

    def fail_pin_delete(_user_id, _file_id):
        raise RuntimeError("simulated DynamoDB failure")

    monkeypatch.setattr(handler, "_delete_protection", fail_pin_delete)
    response = handler.handler(_event("user-a", "file-3"), None)

    assert response["statusCode"] == 200
    assert _has_pin(table, "user-a", "file-3")
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="user-a/file-3")["KeyCount"] == 0


def test_user_cannot_remove_another_users_pin_row(aws_resources):
    handler, s3, table = aws_resources
    _seed_file(s3, "user-a", "shared-file-id")
    _pin(table, "user-a", "shared-file-id")
    _pin(table, "user-b", "shared-file-id")

    response = handler.handler(_event("user-a", "shared-file-id"), None)

    assert response["statusCode"] == 200
    assert not _has_pin(table, "user-a", "shared-file-id")
    assert _has_pin(table, "user-b", "shared-file-id")
