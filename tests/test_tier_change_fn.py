"""Tests for tier-change-fn's S3 copy, ETag guard, metadata, and verification."""
import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws


ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "backend" / "tier-change-fn" / "handler.py"
BUCKET = "test-tier-change-verification"
TABLE_NAME = "test-protected-files-tier-change"
USER_ID = "user-a"
FILE_ID = "sample-file"


def _load_handler():
    spec = importlib.util.spec_from_file_location("tier_change_handler_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resources(monkeypatch):
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
        yield _load_handler(), s3


def _event(target_tier="WARM"):
    return {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": USER_ID}}}},
        "pathParameters": {"fileId": FILE_ID},
        "body": json.dumps({"targetTier": target_tier}),
    }


def _seed_file(s3):
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{USER_ID}/{FILE_ID}",
        Body=b"example contents",
        Metadata={"filename": "example-report.txt"},
    )
    return s3.head_object(Bucket=BUCKET, Key=f"{USER_ID}/{FILE_ID}")


def test_copy_succeeds_and_verifies_target_storage_class(resources):
    handler, s3 = resources
    source_head = _seed_file(s3)
    copy_calls = []
    original_copy = handler.s3.copy_object

    def record_copy(**kwargs):
        copy_calls.append(kwargs)
        return original_copy(**kwargs)

    handler.s3.copy_object = record_copy
    response = handler.handler(_event("WARM"), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "changed"
    assert copy_calls[0]["CopySourceIfMatch"] == source_head["ETag"]
    assert s3.head_object(Bucket=BUCKET, Key=f"{USER_ID}/{FILE_ID}")["StorageClass"] == "STANDARD_IA"


def test_verification_mismatch_returns_error(resources, monkeypatch, caplog):
    handler, s3 = resources
    _seed_file(s3)
    real_client = handler.s3

    class WrongVerificationClass:
        def __init__(self):
            self.head_calls = 0

        def head_object(self, **kwargs):
            self.head_calls += 1
            result = real_client.head_object(**kwargs)
            if self.head_calls == 2:
                result["StorageClass"] = "STANDARD"
            return result

        def __getattr__(self, name):
            return getattr(real_client, name)

    monkeypatch.setattr(handler, "s3", WrongVerificationClass())
    response = handler.handler(_event("WARM"), None)

    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error"] == "Storage class verification failed"
    assert "storage class verification mismatch" in caplog.text


def test_etag_mismatch_returns_precondition_failed(resources, monkeypatch):
    handler, s3 = resources
    source_head = _seed_file(s3)
    captured = {}

    def reject_changed_source(**kwargs):
        captured.update(kwargs)
        raise ClientError(
            {"Error": {"Code": "PreconditionFailed", "Message": "ETag changed"}},
            "CopyObject",
        )

    monkeypatch.setattr(handler.s3, "copy_object", reject_changed_source)
    response = handler.handler(_event("COLD"), None)

    assert captured["CopySourceIfMatch"] == source_head["ETag"]
    assert response["statusCode"] == 412
    assert s3.head_object(Bucket=BUCKET, Key=f"{USER_ID}/{FILE_ID}").get("StorageClass", "STANDARD") == "STANDARD"


def test_copy_preserves_filename_metadata(resources):
    handler, s3 = resources
    _seed_file(s3)

    response = handler.handler(_event("COLD"), None)

    assert response["statusCode"] == 200
    head = s3.head_object(Bucket=BUCKET, Key=f"{USER_ID}/{FILE_ID}")
    assert head["Metadata"]["filename"] == "example-report.txt"
