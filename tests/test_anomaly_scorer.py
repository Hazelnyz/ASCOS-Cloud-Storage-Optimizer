import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from botocore.exceptions import ClientError

HANDLER_PATH = Path(__file__).resolve().parents[1] / "backend" / "anomaly-scorer-fn" / "handler.py"
SPEC = importlib.util.spec_from_file_location("anomaly_scorer_handler", HANDLER_PATH)
scorer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorer)

NOW = datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc)


def event(kind, timestamp, user="user-a"):
    return {"user_id": user, "event_type": kind, "timestamp": timestamp.isoformat().replace("+00:00", "Z")}


def current_events(kind, count, user="user-a"):
    start = scorer._floor_hour(NOW)
    return [event(kind, start + timedelta(seconds=second), user) for second in range(count)]


def test_floor_is_inclusive_and_just_below_floor_does_not_detect():
    detections = scorer.score_events(current_events("download", 9) + current_events("download", 10, "user-b"), NOW)
    assert [(row["user_id"], row["count"], row["severity"]) for row in detections] == [("user-b", 10, "Low")]
    assert detections[0]["threshold"] == 10


def test_baseline_uses_zero_hour_buckets_and_mean_plus_three_population_std():
    first = scorer._floor_hour(NOW) - timedelta(hours=100)
    rows = [event("download", first + timedelta(minutes=10))]
    rows.extend(current_events("download", 31))

    detections = scorer.score_events(rows, NOW)

    assert len(detections) == 1
    detection = detections[0]
    assert detection["mode"] == "baseline"
    assert detection["baseline_mean"] == 0.01
    assert detection["threshold"] == max(10.0, 0.01 + 3 * (0.01 * 0.99) ** 0.5)
    assert detection["severity"] == "Medium"


def test_learning_mode_uses_floor_despite_high_early_activity():
    first = NOW - timedelta(hours=40)
    rows = [event("download", first + timedelta(minutes=10)) for _ in range(100)]
    rows.extend(current_events("download", 10))

    detections = scorer.score_events(rows, NOW)

    assert len(detections) == 1
    assert detections[0]["mode"] == "learning"
    assert detections[0]["threshold"] == 10


def test_severity_cutoffs_and_download_delete_rules_are_independent():
    rows = []
    rows.extend(current_events("download", 10, "low-user"))
    rows.extend(current_events("download", 20, "medium-user"))
    rows.extend(current_events("download", 40, "high-user"))
    rows.extend(current_events("download", 10, "separate-rules"))
    rows.extend(current_events("delete", 9, "separate-rules"))
    rows.extend(current_events("delete", 40, "delete-user"))

    detections = scorer.score_events(rows, NOW, {"std_mult": 0})
    by_user_rule = {(row["user_id"], row["rule"]): row for row in detections}

    assert by_user_rule[("low-user", "download_volume")]["severity"] == "Low"
    assert by_user_rule[("medium-user", "download_volume")]["severity"] == "Medium"
    assert by_user_rule[("high-user", "download_volume")]["severity"] == "High"
    assert ("separate-rules", "download_volume") in by_user_rule
    assert ("separate-rules", "delete_volume") not in by_user_rule
    assert by_user_rule[("delete-user", "delete_volume")]["severity"] == "High"


class DetectionTable:
    def __init__(self):
        self.items = {}

    @staticmethod
    def _conditional_failure(operation):
        return ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "condition failed"}},
            operation,
        )

    def put_item(self, Item, **kwargs):
        key = (Item["user_id"], Item["sk"])
        if key in self.items:
            raise self._conditional_failure("PutItem")
        self.items[key] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kwargs):
        item = self.items[(Key["user_id"], Key["sk"])]
        if "#count < :count" in kwargs["ConditionExpression"]:
            if item["count"] >= ExpressionAttributeValues[":count"]:
                raise self._conditional_failure("UpdateItem")
            for field in ("count", "threshold", "baseline_mean", "mode", "detected_at", "expires_at"):
                item[field] = ExpressionAttributeValues[f":{field}"]
            return
        allowed_old_severities = {
            value for key, value in ExpressionAttributeValues.items() if key.startswith(":old_severity_")
        }
        if item.get("severity") not in allowed_old_severities:
            raise self._conditional_failure("UpdateItem")
        item["severity"] = ExpressionAttributeValues[":new_severity"]


def test_same_window_dedupes_higher_count_upgrades_and_lower_count_never_downgrades():
    table = DetectionTable()
    config = {"std_mult": 0}
    low = scorer.score_events(current_events("download", 10), NOW, config)[0]
    higher = scorer.score_events(current_events("download", 40), NOW, config)[0]
    lower = scorer.score_events(current_events("download", 20), NOW, config)[0]

    assert scorer._persist_detection(table, low) == "created"
    assert scorer._persist_detection(table, low) == "unchanged"
    assert len(table.items) == 1
    assert scorer._persist_detection(table, higher) == "updated"
    assert scorer._persist_detection(table, lower) == "unchanged"

    stored = next(iter(table.items.values()))
    assert stored["count"] == 40
    assert stored["severity"] == "High"
    assert stored["status"] == "Logged"


def test_scan_filter_and_projection_alias_reserved_attribute_names():
    class ScanTable:
        def scan(self, **kwargs):
            names = kwargs["ExpressionAttributeNames"]
            for expression_key in ("FilterExpression", "ProjectionExpression"):
                expression = kwargs[expression_key]
                assert "#timestamp" in expression
                if expression_key == "ProjectionExpression":
                    assert "#user_id" in expression
                for reserved in ("timestamp", "user", "type", "status", "count", "name", "size", "data"):
                    assert not any(part.strip() == reserved for part in expression.split(","))
            assert names["#timestamp"] == "timestamp"
            assert names["#user_id"] == "user_id"
            return {"Items": [], "ScannedCount": 0}

    scorer.dynamodb.Table = lambda table_name: ScanTable()
    events, scanned, truncated = scorer._scan_recent_events(NOW)

    assert events == []
    assert scanned == 0
    assert truncated is False
