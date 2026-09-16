"""
Functional smoke test for all 7 Stage 6 handlers, using moto to
mock S3/DynamoDB so we can actually invoke the handler() functions
and check their real behavior — not just that they import.
"""
import json
import os
import sys
import importlib
from decimal import Decimal

os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
os.environ["S3_BUCKET_NAME"] = "test-ascos-bucket"
os.environ["UPLOAD_URL_EXPIRY_SECONDS"] = "300"
os.environ["DOWNLOAD_URL_EXPIRY_SECONDS"] = "900"
os.environ["SHARE_URL_EXPIRY_SECONDS"] = "86400"
os.environ["ACCESS_EVENT_TABLE"] = "test-access-event"
os.environ["PREDICTIONS_TABLE"] = "test-predictions"

from moto import mock_aws
import boto3

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))

USER_ID = "user-abc-123"
OTHER_USER_ID = "user-xyz-999"


def jwt_event(user_id, path_params=None, body=None):
    e = {
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}},
    }
    if path_params:
        e["pathParameters"] = path_params
    if body is not None:
        e["body"] = json.dumps(body)
    return e


def load_handler(name):
    path = os.path.join(BASE, name)
    sys.path.insert(0, path)
    if "handler" in sys.modules:
        del sys.modules["handler"]
    mod = importlib.import_module("handler")
    sys.path.remove(path)
    return mod


results = []

with mock_aws():
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(
        Bucket="test-ascos-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
    )

    dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
    access_event_table = dynamodb.create_table(
        TableName="test-access-event",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp_event_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "timestamp_event_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    predictions_table = dynamodb.create_table(
        TableName="test-predictions",
        KeySchema=[{"AttributeName": "prediction_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "prediction_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "prediction_timestamp_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "user-index",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "prediction_timestamp_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    predictions_table.put_item(Item={
        "prediction_id": "pred-1",
        "user_id": USER_ID,
        "prediction_timestamp_id": "2026-09-14T00:00:00Z#pred-1",
        "file_id": "file-1",
        "p_access": Decimal("0.8"),
        "candidate_tiers": ["HOT", "WARM"],
        "bandit_choice": "WARM",
        "prediction_timestamp": "2026-09-14T00:00:00Z",
    })

    # --- Test 1: file-list-fn on an empty prefix ---
    m = load_handler("file-list-fn")
    resp = m.handler(jwt_event(USER_ID), None)
    assert resp["statusCode"] == 200, f"file-list-fn empty: {resp}"
    assert json.loads(resp["body"])["files"] == []
    results.append("file-list-fn (empty): PASS")

    # --- Test 2: file-list-fn with no auth ---
    m2 = load_handler("file-list-fn")
    resp = m2.handler({}, None)
    assert resp["statusCode"] == 401, f"file-list-fn no-auth: {resp}"
    results.append("file-list-fn (no auth -> 401): PASS")

    # --- Test 3: file-upload-url-fn happy path ---
    m = load_handler("file-upload-url-fn")
    resp = m.handler(jwt_event(USER_ID, body={"filename": "report.pdf"}), None)
    assert resp["statusCode"] == 200, f"upload-url: {resp}"
    body = json.loads(resp["body"])
    assert "fileId" in body and "uploadUrl" in body
    file_id = body["fileId"]
    results.append(f"file-upload-url-fn (happy path): PASS, fileId={file_id}")

    # --- Test 4: file-upload-url-fn missing filename -> 400 ---
    m2 = load_handler("file-upload-url-fn")
    resp = m2.handler(jwt_event(USER_ID, body={}), None)
    assert resp["statusCode"] == 400, f"upload-url missing filename: {resp}"
    results.append("file-upload-url-fn (missing filename -> 400): PASS")

    # Actually upload an object using that presigned URL's key convention
    # (moto doesn't validate presigned URL signatures the way real S3
    # does, so we directly put the object to set up state for the
    # remaining tests).
    key = f"{USER_ID}/{file_id}"
    s3.put_object(Bucket="test-ascos-bucket", Key=key, Body=b"hello world", Metadata={"filename": "report.pdf"})

    # --- Test 5: file-download-url-fn happy path ---
    m = load_handler("file-download-url-fn")
    resp = m.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 200, f"download-url: {resp}"
    assert "downloadUrl" in json.loads(resp["body"])
    results.append("file-download-url-fn (happy path): PASS")

    # --- Test 6: file-download-url-fn wrong user (isolation check) ---
    m2 = load_handler("file-download-url-fn")
    resp = m2.handler(jwt_event(OTHER_USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 404, f"download-url cross-user: {resp}"
    results.append("file-download-url-fn (other user's fileId -> 404, NOT another user's file): PASS")

    # --- Test 7: file-metadata-fn happy path ---
    m = load_handler("file-metadata-fn")
    resp = m.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 200, f"metadata: {resp}"
    meta_body = json.loads(resp["body"])
    assert meta_body["filename"] == "report.pdf", f"filename not recovered: {meta_body}"
    results.append("file-metadata-fn (happy path, filename recovered from metadata): PASS")

    # --- Test 8: file-metadata-fn nonexistent file -> 404 ---
    m2 = load_handler("file-metadata-fn")
    resp = m2.handler(jwt_event(USER_ID, path_params={"fileId": "does-not-exist"}), None)
    assert resp["statusCode"] == 404, f"metadata missing: {resp}"
    results.append("file-metadata-fn (nonexistent fileId -> 404): PASS")

    # --- Test 9: file-share-fn happy path (checks access_event write) ---
    m = load_handler("file-share-fn")
    resp = m.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 200, f"share: {resp}"
    assert "shareUrl" in json.loads(resp["body"])
    scan = access_event_table.scan()
    share_events = [i for i in scan["Items"] if i["event_type"] == "share"]
    assert len(share_events) == 1, f"expected 1 share event, got {len(share_events)}"
    assert share_events[0]["file_id"] == file_id
    assert share_events[0]["user_id_file_id"] == f"{USER_ID}#{file_id}"
    results.append("file-share-fn (happy path, access_event row written correctly): PASS")

    # --- Test 10: frequently-used-fn happy path ---
    m = load_handler("frequently-used-fn")
    resp = m.handler(jwt_event(USER_ID), None)
    assert resp["statusCode"] == 200, f"frequently-used: {resp}"
    preds = json.loads(resp["body"])["predictions"]
    assert len(preds) == 1 and preds[0]["fileId"] == "file-1"
    results.append("frequently-used-fn (happy path, GSI query correct): PASS")

    # --- Test 11: frequently-used-fn different user gets nothing ---
    m2 = load_handler("frequently-used-fn")
    resp = m2.handler(jwt_event(OTHER_USER_ID), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["predictions"] == []
    results.append("frequently-used-fn (other user, correctly isolated, empty result): PASS")

    # --- Test 12: file-delete-fn happy path ---
    m = load_handler("file-delete-fn")
    resp = m.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 200, f"delete: {resp}"
    results.append("file-delete-fn (happy path): PASS")

    # --- Test 13: confirm the object is actually gone ---
    m2 = load_handler("file-metadata-fn")
    resp = m2.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 404, f"post-delete metadata check: {resp}"
    results.append("file-delete-fn (object actually removed from S3, confirmed via metadata 404): PASS")

    # --- Test 14: file-delete-fn on already-deleted file -> 404, not false success ---
    m3 = load_handler("file-delete-fn")
    resp = m3.handler(jwt_event(USER_ID, path_params={"fileId": file_id}), None)
    assert resp["statusCode"] == 404, f"double-delete: {resp}"
    results.append("file-delete-fn (deleting already-deleted file -> 404, not false success): PASS")

print("\n".join(results))
print(f"\n{len(results)}/14 tests passed.")
