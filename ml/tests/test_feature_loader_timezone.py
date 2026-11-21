"""
Regression test for timezone handling in feature_loader.py.

Ensures that timestamps returned by feature_loader are tz-naive UTC,
compatible with feature_engineering.py's tz-naive snapshot_time.
"""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

# Mock boto3 before importing modules that use it
import sys
sys.modules['boto3'] = MagicMock()
sys.modules['boto3.dynamodb'] = MagicMock()
sys.modules['boto3.dynamodb.conditions'] = MagicMock()

from ml.inference import feature_loader
from ml.features import feature_engineering


class TestFeatureLoaderTimezone(unittest.TestCase):
    """Test that feature_loader normalizes timestamps to tz-naive UTC."""

    def test_load_real_events_for_user_normalizes_timestamps(self):
        """Mock DynamoDB query returns tz-aware UTC timestamps; should be normalized to tz-naive."""
        # Mock DynamoDB items with tz-aware timestamps (as CloudTrail provides)
        mock_items = [
            {
                "event_id": "evt1",
                "user_id": "user123",
                "file_id": "file1",
                "event_type": "download",
                "timestamp": "2026-01-15T10:30:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
            {
                "event_id": "evt2",
                "user_id": "user123",
                "file_id": "file2",
                "event_type": "read",
                "timestamp": "2026-01-15T11:45:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
        ]

        mock_table = MagicMock()
        # Return no LastEvaluatedKey to signal end of pagination
        mock_table.query.return_value = {"Items": mock_items}

        with patch.object(feature_loader, "_dynamodb_resource", return_value=MagicMock()):
            with patch.object(feature_loader, "_access_event_table", return_value=mock_table):
                df = feature_loader.load_real_events_for_user("user123")

        # Verify timestamps are tz-naive
        for ts in df["timestamp"]:
            self.assertIsNone(ts.tzinfo, f"Timestamp {ts} should be tz-naive")

        # Verify values are preserved
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["event_id"], "evt1")
        self.assertEqual(df.iloc[1]["event_id"], "evt2")

    def test_load_real_events_for_user_pagination_two_pages(self):
        """Test pagination works correctly with two pages of results."""
        # First page
        page1_items = [
            {
                "event_id": "evt1",
                "user_id": "user123",
                "file_id": "file1",
                "event_type": "download",
                "timestamp": "2026-01-15T10:30:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
        ]

        # Second page
        page2_items = [
            {
                "event_id": "evt2",
                "user_id": "user123",
                "file_id": "file2",
                "event_type": "read",
                "timestamp": "2026-01-15T11:45:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
        ]

        mock_table = MagicMock()
        # First call returns page 1 with LastEvaluatedKey
        # Second call returns page 2 without LastEvaluatedKey (end)
        mock_table.query.side_effect = [
            {"Items": page1_items, "LastEvaluatedKey": {"user_id": "user123", "timestamp_event_id": "2026-01-15T10:30:00Z#evt1"}},
            {"Items": page2_items},  # No LastEvaluatedKey = end
        ]

        with patch.object(feature_loader, "_dynamodb_resource", return_value=MagicMock()):
            with patch.object(feature_loader, "_access_event_table", return_value=mock_table):
                df = feature_loader.load_real_events_for_user("user123")

        # Verify both pages were combined
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["event_id"], "evt1")
        self.assertEqual(df.iloc[1]["event_id"], "evt2")

        # Verify query was called twice (pagination)
        self.assertEqual(mock_table.query.call_count, 2)

    def test_load_real_file_metadata_normalizes_upload_date(self):
        """Mock S3 HeadObject returns tz-aware LastModified; should be normalized to tz-naive."""
        # Mock events_df empty (no write events, so upload_date falls back to S3 LastModified)
        events_df = pd.DataFrame(columns=["user_id", "file_id", "event_type", "timestamp"])

        mock_s3 = MagicMock()
        mock_s3.head_object.return_value = {
            "Metadata": {"filename": "test.pdf"},
            "StorageClass": "STANDARD",
            "Size": 1024 * 1024,  # 1 MB
            "LastModified": datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        }

        mock_s3_paginator = MagicMock()
        mock_s3_paginator.paginate.return_value = [
            {"Contents": [{"Key": "user123/file1.pdf", "Size": 1024 * 1024, "LastModified": datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)}]}
        ]
        mock_s3.get_paginator.return_value = mock_s3_paginator

        mock_protected = MagicMock()
        mock_protected.query.return_value = {"Items": []}

        with patch.dict(os.environ, {"S3_BUCKET_NAME": "test-bucket"}):
            with patch.object(feature_loader, "_s3_client", return_value=mock_s3):
                with patch.object(feature_loader, "_protected_files_table", return_value=mock_protected):
                    df = feature_loader.load_real_file_metadata_for_user("user123", events_df)

        # Verify upload_date is tz-naive and equals expected UTC time
        upload_date = df.iloc[0]["upload_date"]
        expected_date = pd.Timestamp("2026-01-15T10:30:00")
        self.assertIsNotNone(upload_date)
        self.assertIsNone(upload_date.tzinfo, f"upload_date {upload_date} should be tz-naive")
        self.assertEqual(upload_date, expected_date)

    def test_predictor_snapshot_logic_with_feature_loader_timestamps(self):
        """Integration test: events from feature_loader work through predictor's snapshot logic."""
        # Mock DynamoDB to return items with tz-aware timestamps (ISO strings ending in Z)
        mock_items = [
            {
                "event_id": "evt1",
                "user_id": "user123",
                "file_id": "file1",
                "event_type": "download",
                "timestamp": "2026-01-15T10:30:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
            {
                "event_id": "evt2",
                "user_id": "user123",
                "file_id": "file1",
                "event_type": "read",
                "timestamp": "2026-01-15T11:45:00Z",
                "source_ip": "1.2.3.4",
                "device_context": "Chrome",
            },
        ]

        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": mock_items}

        with patch.object(feature_loader, "_access_event_table", return_value=mock_table):
            events_df = feature_loader.load_real_events_for_user("user123")

        # Build file metadata as pd.Series (as predictor.py does)
        file_metadata_row = pd.Series({
            "file_id": "file1",
            "user_id": "user123",
            "upload_date": pd.Timestamp("2026-01-01T00:00:00"),  # tz-naive
            "file_type": "pdf",
            "file_size_bucket": "small",
            "directory_category": "uncategorized",
            "current_storage_tier": "HOT",
            "protected_flag": False,
        })

        # Use tz-naive snapshot_time (as predictor.py does)
        snapshot_time = pd.Timestamp("2026-01-15T12:00:00")  # tz-naive

        # This should not raise a TypeError about tz-aware vs tz-naive comparison
        features = feature_engineering.compute_features_for_snapshot(
            events_df=events_df,
            file_metadata_row=file_metadata_row,
            user_id="user123",
            file_id="file1",
            snapshot_time=snapshot_time,
        )
        # Verify we got a result
        self.assertIsNotNone(features)
        self.assertIn("days_since_last_access", features)
        self.assertFalse(pd.isna(features["days_since_last_access"]))


if __name__ == "__main__":
    unittest.main()
