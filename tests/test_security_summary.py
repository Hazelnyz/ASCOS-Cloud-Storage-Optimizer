import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest


HANDLER_PATH = Path(__file__).resolve().parents[1] / "backend" / "security-summary-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("security_summary_handler", HANDLER_PATH)
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)

RESERVED_WORDS = {"timestamp", "type", "name", "status", "size", "data", "user"}


class FakeTable:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def query(self, **kwargs):
        projection = kwargs.get("ProjectionExpression", "")
        for attribute in projection.split(","):
            bare_name = attribute.strip().split(".")[0].strip()
            if bare_name.lower() in RESERVED_WORDS and not bare_name.startswith("#"):
                raise ValueError(f"Unaliased DynamoDB reserved word in projection: {bare_name}")
        self.calls.append(kwargs)
        return self.responses.pop(0) if self.responses else {"Items": []}


def jwt_event(claims=None):
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims or {"sub": "user-a", "auth_time": "1790000000"}}}}}


def test_summary_counts_pins_and_returns_latest_supported_events_without_fake_detections():
    protected = FakeTable([{"Count": 2, "LastEvaluatedKey": {"file_id": "next"}}, {"Count": 1}])
    events = FakeTable([{"Items": []}])
    detections = DetectionSummaryTable("2026-10-24T12:15:00Z", [{
        "user_id": "user-a", "sk": "2026-10-24T12:00:00Z#download_volume",
        "rule": "download_volume", "severity": "Medium", "status": "Logged",
        "count": 20, "threshold": 10, "mode": "learning",
        "window_start": "2026-10-24T12:00:00Z", "detected_at": "2026-10-24T12:15:00Z",
    }, {"user_id": "_system", "sk": "last_run", "rule": "invalid_marker"}])
    detections = DetectionSummaryTable(None, [])
    security._reset_tables()
    security._tables.update({
        "PROTECTED_FILES_TABLE": protected,
        "ACCESS_EVENT_TABLE": events,
        "ANOMALY_DETECTIONS_TABLE": detections,
    })

    response = security.handler(jwt_event(), None)

    assert response["statusCode"] == 200
    import json
    body = json.loads(response["body"])
    assert body["authentication"]["provider"] == "Cognito"
    assert body["authentication"]["lastSignIn"] is not None
    assert body["protectedFiles"] == {"count": 3}
    assert body["anomaly"] == {"status": "active", "rule": "baseline", "lastRun": "2026-10-24T12:15:00Z", "openCount": 1}
    assert len(body["detections"]) == 1
    assert body["detections"][0]["rule"] == "download_volume"
    assert protected.calls[0]["Select"] == "COUNT"


def test_unauthenticated_request_is_rejected_without_queries():
    security._reset_tables()
    with patch.dict(os.environ, {}, clear=True):
        response = security.handler({}, None)
    assert response["statusCode"] == 401


class DetectionSummaryTable:
    def __init__(self, last_run, detections):
        self.last_run = last_run
        self.detections = detections
        self.calls = []

    def get_item(self, **kwargs):
        self.calls.append(("get_item", kwargs))
        return {"Item": {"ran_at": self.last_run}} if self.last_run else {}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        assert "#user_id" in kwargs["KeyConditionExpression"]
        assert "#sk" in kwargs["KeyConditionExpression"]
        return {"Items": self.detections}


def test_anomaly_summary_active_stale_and_never_returns_system_marker_as_detection():
    now = security.datetime(2026, 10, 24, 12, 30, tzinfo=security.timezone.utc)
    recent_detection = {
        "user_id": "user-a", "sk": "2026-10-24T12:00:00Z#download_volume",
        "rule": "download_volume", "severity": "Medium", "status": "Logged",
        "count": 20, "threshold": 10, "mode": "learning",
        "window_start": "2026-10-24T12:00:00Z", "detected_at": "2026-10-24T12:10:00Z",
    }
    system_row = {"user_id": "_system", "sk": "last_run", "rule": "bad"}
    table = DetectionSummaryTable("2026-10-24T12:15:00Z", [recent_detection, system_row])
    security._reset_tables()
    security._tables["ANOMALY_DETECTIONS_TABLE"] = table

    result = security._anomaly_summary("user-a", now)

    assert result["status"] == "active"
    assert result["rule"] == "baseline"
    assert result["openCount"] == 1
    assert len(result["detections"]) == 1
    assert result["detections"][0]["status"] == "Logged"
    assert result["detections"][0]["rule"] == "download_volume"

    stale_table = DetectionSummaryTable("2026-10-24T11:00:00Z", [])
    security._tables["ANOMALY_DETECTIONS_TABLE"] = stale_table
    stale = security._anomaly_summary("user-a", now)
    assert stale["status"] == "not_connected"
    assert stale["lastRun"] == "2026-10-24T11:00:00Z"


def test_activity_projection_aliases_every_reserved_attribute():
    table = FakeTable([{"Items": []}])
    security._reset_tables()
    security._tables["ACCESS_EVENT_TABLE"] = table

    security._activity_counts("user-a", security.datetime(2026, 10, 24, 12, tzinfo=security.timezone.utc))

    query = table.calls[0]
    assert all(name.strip().startswith("#") for name in query["ProjectionExpression"].split(","))
    assert query["ExpressionAttributeNames"]["#timestamp"] == "timestamp"
    assert query["ExpressionAttributeNames"]["#event_type"] == "event_type"
    with pytest.raises(ValueError, match="reserved word"):
        table.query(ProjectionExpression="file_id, timestamp")


def test_activity_counts_bucket_24h_and_7d_and_include_share():
    now = security.datetime(2026, 10, 24, 12, 0, tzinfo=security.timezone.utc)
    table = FakeTable([{
        "Items": [
            {"event_type": "download", "timestamp": "2026-10-24T11:00:00Z"},
            {"event_type": "write", "timestamp": "2026-10-23T13:00:00+00:00"},
            {"event_type": "delete", "timestamp": "2026-10-23T10:00:00Z"},
            {"event_type": "share", "timestamp": "2026-10-18T12:00:00Z"},
            {"event_type": "download", "timestamp": "2026-10-17T11:59:59Z"},
        ]
    }])
    security._reset_tables()
    security._tables["ACCESS_EVENT_TABLE"] = table

    activity = security._activity_counts("user-a", now)

    assert activity == {
        "last24h": {"download": 1, "write": 1, "delete": 0, "share": 0},
        "last7d": {"download": 1, "write": 1, "delete": 1, "share": 1},
        "truncated": False,
    }
    query = table.calls[0]
    assert query["ExpressionAttributeNames"]["#timestamp"] == "timestamp"
    assert query["ExpressionAttributeNames"]["#event_type"] == "event_type"
    assert all(name.startswith("#") for name in query["ProjectionExpression"].split(", "))


def test_activity_counts_report_truncated_when_row_cap_is_reached():
    now = security.datetime(2026, 10, 24, 12, 0, tzinfo=security.timezone.utc)
    rows = [
        {"event_type": "download", "timestamp": "2026-10-24T11:00:00Z"},
        {"event_type": "write", "timestamp": "2026-10-24T10:00:00Z"},
        {"event_type": "share", "timestamp": "2026-10-23T10:00:00Z"},
    ]
    table = FakeTable([
        {"Items": rows[:2], "LastEvaluatedKey": {"timestamp_event_id": "page-1"}},
        {"Items": rows[2:], "LastEvaluatedKey": {"timestamp_event_id": "page-2"}},
    ])
    security._reset_tables()
    security._tables["ACCESS_EVENT_TABLE"] = table

    with patch.object(security, "ACTIVITY_QUERY_LIMIT", 3), patch.object(security, "ACTIVITY_PAGE_SIZE", 2):
        activity = security._activity_counts("user-a", now)

    assert activity["truncated"] is True
    assert activity["last24h"]["download"] == 1
    assert activity["last7d"]["share"] == 1
    assert len(table.calls) == 2