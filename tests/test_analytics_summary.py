import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


HANDLER_PATH = Path(__file__).resolve().parents[1] / "backend" / "analytics-summary-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("analytics_summary_handler", HANDLER_PATH)
analytics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analytics)


def test_summary_aggregates_real_files_events_and_latest_predictions():
    today = date(2026, 10, 23)
    old_upload = datetime.combine(today - timedelta(days=3), datetime.min.time(), timezone.utc)
    recent_upload = datetime.combine(today - timedelta(days=1), datetime.min.time(), timezone.utc)
    files = [
        {"file_id": "f1", "size": 1024 ** 3, "tier": "HOT", "filename": "report.pdf", "created_at": old_upload},
        {"file_id": "f2", "size": 512, "tier": "COLD", "filename": "notes.txt", "created_at": recent_upload},
    ]
    access_rows = [
        {"timestamp": f"{today.isoformat()}T08:00:00Z", "event_type": "download"},
        {"timestamp": f"{today.isoformat()}T09:00:00Z", "event_type": "write"},
        {"timestamp": f"{today.isoformat()}T10:00:00Z", "event_type": "share"},
        {"timestamp": f"{today.isoformat()}T11:00:00Z", "event_type": "delete"},
    ]
    predictions = [
        {"file_id": "f1", "prediction_timestamp": "2026-10-20T00:00:00Z", "bandit_choice": "WARM"},
        {"file_id": "f1", "prediction_timestamp": "2026-10-22T00:00:00Z", "bandit_choice": "COLD"},
    ]

    with patch.dict("os.environ", {
        "STORAGE_RATE_HOT_PER_GB_MONTH": "0.023",
        "STORAGE_RATE_WARM_PER_GB_MONTH": "0.012",
        "STORAGE_RATE_COLD_PER_GB_MONTH": "0.004",
    }):
        result = analytics._summary(files, access_rows, predictions, today)

    assert result["tiers"] == [
        {"tier": "COLD", "files": 1, "bytes": 512},
        {"tier": "HOT", "files": 1, "bytes": 1024 ** 3},
    ]
    assert result["types"] == [{"type": "pdf", "files": 1}, {"type": "txt", "files": 1}]
    assert len(result["storageOverTime"]) == 30
    assert result["storageOverTime"][-4]["bytes"] == 1024 ** 3
    assert result["storageOverTime"][-2]["bytes"] == 1024 ** 3 + 512
    assert result["access"][-1] == {
        "day": today.isoformat(), "reads": 0, "writes": 1, "downloads": 1, "shares": 1,
    }
    assert result["optimization"]["monthlySavings"] == 0.019


def test_optimization_is_unavailable_without_configured_real_rates():
    today = date(2026, 10, 23)
    with patch.dict("os.environ", {}, clear=True):
        result = analytics._summary(
            [{"file_id": "f1", "size": 1024, "tier": "HOT", "filename": "a.txt", "created_at": None}],
            [],
            [{"file_id": "f1", "prediction_timestamp": "2026-10-22T00:00:00Z", "bandit_choice": "COLD"}],
            today,
        )
    assert result["optimization"] is None


def test_empty_or_irrelevant_access_and_missing_predictions_are_not_invented():
    result = analytics._summary([], [{"timestamp": "2026-10-23T12:00:00Z", "event_type": "delete"}], [], date(2026, 10, 23))

    assert result["tiers"] == []
    assert result["types"] == []
    assert result["access"] == []
    assert result["optimization"] is None


def test_share_events_counted_per_day():
    today = date(2026, 10, 23)
    yesterday = today - timedelta(days=1)
    access_rows = [
        {"timestamp": f"{yesterday.isoformat()}T08:00:00Z", "event_type": "share"},
        {"timestamp": f"{yesterday.isoformat()}T09:00:00Z", "event_type": "share"},
        {"timestamp": f"{today.isoformat()}T10:00:00Z", "event_type": "share"},
    ]

    result = analytics._summary([], access_rows, [], today)

    assert len(result["access"]) == 14
    # Yesterday should have 2 shares
    yesterday_entry = next((day for day in result["access"] if day["day"] == yesterday.isoformat()), None)
    assert yesterday_entry is not None
    assert yesterday_entry["shares"] == 2
    assert yesterday_entry["reads"] == 0
    assert yesterday_entry["writes"] == 0
    assert yesterday_entry["downloads"] == 0
    # Today should have 1 share
    today_entry = next((day for day in result["access"] if day["day"] == today.isoformat()), None)
    assert today_entry is not None
    assert today_entry["shares"] == 1
    assert today_entry["reads"] == 0
    assert today_entry["writes"] == 0
    assert today_entry["downloads"] == 0


def test_handler_requires_authenticated_user():
    response = analytics.handler({}, None)
    assert response["statusCode"] == 401


def test_all_analytics_query_key_attributes_are_explicitly_aliased():
    class QueryTable:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            return {"Items": []}

    events = QueryTable()
    predictions = QueryTable()
    analytics._reset_resources()
    analytics._resources.update({"ACCESS_EVENT_TABLE": events, "PREDICTIONS_TABLE": predictions})

    with patch.dict("os.environ", {"ACCESS_EVENT_TABLE": "access-events"}):
        analytics._access_rows("user-a", date(2026, 10, 10), date(2026, 10, 23))
        analytics._prediction_rows("user-a")

    access_query = events.calls[0]
    assert "#user_id" in access_query["KeyConditionExpression"]
    assert "#timestamp_event_id" in access_query["KeyConditionExpression"]
    assert access_query["ExpressionAttributeNames"] == {
        "#user_id": "user_id",
        "#timestamp_event_id": "timestamp_event_id",
    }
    prediction_query = predictions.calls[0]
    assert "#user_id" in prediction_query["KeyConditionExpression"]
    assert prediction_query["ExpressionAttributeNames"] == {"#user_id": "user_id"}