"""
Stage 7.3 tests for access-event-writer-fn.

Standalone script (no pytest), moto-mocked, matching the existing
tests/test_handlers.py pattern. Run via: python3 test_access_event_writer.py

Covers:
  - valid GetObject / PutObject / DeleteObject -> correct event_type mapping
  - duplicate eventID -> conditional write silently ignored, no crash
  - non-allowlisted eventName -> ignored (defense in depth)
  - malformed/missing object key (no "/") -> raises
  - empty user_id (key starts with "/") -> raises
  - empty file_id (key ends with "/") -> raises
  - missing eventID -> raises
  - missing eventTime -> raises
"""
import os
import sys

os.environ["ACCESS_EVENT_TABLE"] = "test-ascos-access-event"

import boto3
from moto import mock_aws

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "backend", "access-event-writer-fn"),
)


def base_detail(event_name="GetObject", **overrides):
    detail = {
        "eventName": event_name,
        "eventID": "aaaa1111-0000-0000-0000-000000000001",
        "eventTime": "2026-09-19T10:15:00Z",
        "sourceIPAddress": "203.0.113.42",
        "userAgent": "Mozilla/5.0",
        "requestParameters": {
            "bucketName": "ascos-dev-storage-477554784986",
            "key": "test-user-001/test-file-001",
        },
    }
    detail.update(overrides)
    return detail


def wrap(detail):
    return {"detail-type": "AWS API Call via CloudTrail", "source": "aws.s3", "detail": detail}


def create_table(dynamodb):
    table = dynamodb.create_table(
        TableName=os.environ["ACCESS_EVENT_TABLE"],
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp_event_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "timestamp_event_id", "AttributeType": "S"},
            {"AttributeName": "user_id_file_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user-file-index",
                "KeySchema": [
                    {"AttributeName": "user_id_file_id", "KeyType": "HASH"},
                    {"AttributeName": "timestamp_event_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            }
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    return table


def run():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = create_table(dynamodb)
        table.wait_until_exists()

        import handler as h  # imported inside the mock context, after table exists

        # --- valid GetObject -> download ---
        result = h.handler(wrap(base_detail("GetObject")), None)
        assert result["status"] == "written", result
        item = table.get_item(
            Key={
                "user_id": "test-user-001",
                "timestamp_event_id": "2026-09-19T10:15:00Z#aaaa1111-0000-0000-0000-000000000001",
            }
        )["Item"]
        assert item["event_type"] == "download", item
        assert item["file_id"] == "test-file-001", item
        assert item["user_id_file_id"] == "test-user-001#test-file-001", item
        print("PASS: valid GetObject -> download")

        # --- valid PutObject -> write ---
        result = h.handler(
            wrap(base_detail("PutObject", eventID="bbbb2222-0000-0000-0000-000000000002")), None
        )
        assert result["status"] == "written", result
        item = table.get_item(
            Key={
                "user_id": "test-user-001",
                "timestamp_event_id": "2026-09-19T10:15:00Z#bbbb2222-0000-0000-0000-000000000002",
            }
        )["Item"]
        assert item["event_type"] == "write", item
        print("PASS: valid PutObject -> write")

        # --- valid DeleteObject -> delete ---
        result = h.handler(
            wrap(base_detail("DeleteObject", eventID="cccc3333-0000-0000-0000-000000000003")), None
        )
        assert result["status"] == "written", result
        item = table.get_item(
            Key={
                "user_id": "test-user-001",
                "timestamp_event_id": "2026-09-19T10:15:00Z#cccc3333-0000-0000-0000-000000000003",
            }
        )["Item"]
        assert item["event_type"] == "delete", item
        print("PASS: valid DeleteObject -> delete")

        # --- duplicate eventID (re-deliver the first GetObject) -> ignored, not crashed ---
        result = h.handler(wrap(base_detail("GetObject")), None)
        assert result["status"] == "duplicate_ignored", result
        print("PASS: duplicate eventID silently ignored")

        # --- ignored eventName (defense in depth, e.g. CopyObject slipping through) ---
        result = h.handler(
            wrap(base_detail("CopyObject", eventID="dddd4444-0000-0000-0000-000000000004")), None
        )
        assert result["status"] == "ignored", result
        print("PASS: non-allowlisted eventName ignored (defense in depth)")

        # --- malformed/missing object key (no "/" at all) ---
        try:
            h.handler(
                wrap(
                    base_detail(
                        "GetObject",
                        eventID="eeee5555-0000-0000-0000-000000000005",
                        requestParameters={"bucketName": "ascos-dev-storage-477554784986", "key": "no-slash-key"},
                    )
                ),
                None,
            )
            raise AssertionError("expected ValueError for malformed key")
        except ValueError:
            print("PASS: malformed object key raises")

        try:
            h.handler(
                wrap(
                    base_detail(
                        "GetObject",
                        eventID="ffff6666-0000-0000-0000-000000000006",
                        requestParameters={"bucketName": "ascos-dev-storage-477554784986"},
                    )
                ),
                None,
            )
            raise AssertionError("expected ValueError for missing key")
        except ValueError:
            print("PASS: missing object key raises")

        # --- empty user_id (key starts with "/") ---
        try:
            h.handler(
                wrap(
                    base_detail(
                        "GetObject",
                        eventID="11112222-0000-0000-0000-000000000011",
                        requestParameters={"bucketName": "ascos-dev-storage-477554784986", "key": "/file.txt"},
                    )
                ),
                None,
            )
            raise AssertionError("expected ValueError for empty user_id")
        except ValueError:
            print("PASS: empty user_id raises")

        # --- empty file_id (key ends with "/") ---
        try:
            h.handler(
                wrap(
                    base_detail(
                        "GetObject",
                        eventID="22223333-0000-0000-0000-000000000022",
                        requestParameters={"bucketName": "ascos-dev-storage-477554784986", "key": "user123/"},
                    )
                ),
                None,
            )
            raise AssertionError("expected ValueError for empty file_id")
        except ValueError:
            print("PASS: empty file_id raises")

        # --- missing eventID ---
        try:
            h.handler(wrap(base_detail("GetObject", eventID=None)), None)
            raise AssertionError("expected ValueError for missing eventID")
        except ValueError:
            print("PASS: missing eventID raises")

        # --- missing eventTime ---
        try:
            h.handler(
                wrap(base_detail("GetObject", eventID="1234abcd-0000-0000-0000-000000000099", eventTime=None)),
                None,
            )
            raise AssertionError("expected ValueError for missing eventTime")
        except ValueError:
            print("PASS: missing eventTime raises")

        print("\nAll access-event-writer-fn tests passed.")


if __name__ == "__main__":
    run()