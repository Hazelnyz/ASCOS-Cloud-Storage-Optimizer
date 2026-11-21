import unittest

import numpy as np
import pandas as pd

from ml.features.feature_engineering import (
    FEATURE_COLUMNS,
    compute_features_for_snapshot,
)


def _make_event(user_id, file_id, event_type, timestamp, source_ip="10.0.0.1", device="web"):
    return {
        "event_id": f"{file_id}-{event_type}-{timestamp}",
        "user_id": user_id,
        "file_id": file_id,
        "event_type": event_type,
        "timestamp": pd.Timestamp(timestamp),
        "source_ip": source_ip,
        "device_context": device,
    }


def _file_meta_row(file_id="f1", user_id="u1", upload_date="2026-01-01"):
    return pd.Series(
        {
            "file_id": file_id,
            "user_id": user_id,
            "upload_date": pd.Timestamp(upload_date),
            "file_type": "pdf",
            "file_size_bucket": "small",
            "directory_category": "project_a",
            "current_storage_tier": "HOT",
            "protected_flag": False,
        }
    )


class TestFeatureLeakage(unittest.TestCase):
    def test_future_access_event_does_not_change_features(self):
        """The core leakage test: adding an ACCESS_EVENT strictly after
        snapshot_time must not change a single feature value."""
        snapshot_time = pd.Timestamp("2026-02-01")
        base_events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-05"),
                _make_event("u1", "f1", "read", "2026-01-20"),
            ]
        )
        future_event = pd.DataFrame(
            [_make_event("u1", "f1", "download", "2026-02-15")]  # strictly after snapshot_time
        )
        events_with_future = pd.concat([base_events, future_event], ignore_index=True)

        meta_row = _file_meta_row()

        feats_without_future = compute_features_for_snapshot(
            base_events, meta_row, "u1", "f1", snapshot_time
        )
        feats_with_future = compute_features_for_snapshot(
            events_with_future, meta_row, "u1", "f1", snapshot_time
        )

        for col in FEATURE_COLUMNS:
            a, b = feats_without_future[col], feats_with_future[col]
            if isinstance(a, float) and np.isnan(a) and isinstance(b, float) and np.isnan(b):
                continue
            self.assertEqual(
                a, b, msg=f"leakage detected in feature '{col}': {a!r} != {b!r}"
            )

    def test_event_exactly_at_snapshot_time_is_included(self):
        """Spec: 'at or before T' -- an event AT T must count as past."""
        snapshot_time = pd.Timestamp("2026-01-10 12:00:00")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-10 12:00:00"),  # exactly at T
            ]
        )
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertFalse(feats["never_accessed"])
        self.assertEqual(feats["access_count_7d"], 1)

    def test_event_one_microsecond_after_snapshot_is_excluded(self):
        snapshot_time = pd.Timestamp("2026-01-10 12:00:00")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-10 12:00:00.000001"),
            ]
        )
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertTrue(feats["never_accessed"])

    def test_co_access_signal_does_not_leak_future_co_access(self):
        """§2 explicitly flags co_access_signal as the highest leakage
        risk: 'a co-access that happened after T is future information
        and must not leak in.'"""
        snapshot_time = pd.Timestamp("2026-01-10 09:00:00")
        events_no_future_co_access = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-10 09:00:00"),
                _make_event("u1", "f2", "write", "2026-01-01"),
                # co-access partner event is in the FUTURE relative to T:
            ]
        )
        events_with_future_co_access = pd.concat(
            [
                events_no_future_co_access,
                pd.DataFrame(
                    [_make_event("u1", "f2", "read", "2026-01-10 09:05:00")]  # after T
                ),
            ],
            ignore_index=True,
        )
        meta_row = _file_meta_row()

        feats_a = compute_features_for_snapshot(
            events_no_future_co_access, meta_row, "u1", "f1", snapshot_time
        )
        feats_b = compute_features_for_snapshot(
            events_with_future_co_access, meta_row, "u1", "f1", snapshot_time
        )
        self.assertEqual(feats_a["co_access_signal"], feats_b["co_access_signal"])
        self.assertEqual(feats_a["co_access_signal"], 0)

    def test_co_access_signal_detects_past_co_access(self):
        snapshot_time = pd.Timestamp("2026-01-10 09:10:00")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-10 09:00:00"),
                _make_event("u1", "f2", "write", "2026-01-01"),
                _make_event("u1", "f2", "read", "2026-01-10 09:05:00"),  # within 15 min, before T
            ]
        )
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertEqual(feats["co_access_signal"], 1)

    def test_never_accessed_features_are_null_not_sentinel(self):
        """§2: 'NULL/missing if no ACCESS_EVENT exists yet ... not a
        sentinel number.'"""
        snapshot_time = pd.Timestamp("2026-01-02")
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-01")])
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertTrue(feats["never_accessed"])
        self.assertTrue(np.isnan(feats["days_since_last_access"]))
        self.assertTrue(np.isnan(feats["access_hour_sin"]))
        self.assertTrue(np.isnan(feats["access_hour_cos"]))
        self.assertIsNone(feats["last_access_day_of_week"])
        self.assertTrue(np.isnan(feats["access_hour_consistency"]))

    def test_access_hour_consistency_requires_at_least_two_events(self):
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-02 09:00:00"),
            ]
        )
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertTrue(np.isnan(feats["access_hour_consistency"]))

    def test_protected_flag_excluded_from_feature_columns(self):
        """§2: protected_flag must NOT be fed to the model as a feature."""
        self.assertNotIn("protected_flag", FEATURE_COLUMNS)

    def test_file_id_and_user_id_not_model_features(self):
        """§2: raw file_id/filename must never be fed to the model."""
        self.assertNotIn("file_id", FEATURE_COLUMNS)
        self.assertNotIn("user_id", FEATURE_COLUMNS)

    def test_write_delete_share_excluded_from_recency_frequency_features(self):
        """write/delete/share must not count toward access_count_* etc."""
        snapshot_time = pd.Timestamp("2026-01-10")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "write", "2026-01-02"),
                _make_event("u1", "f1", "share", "2026-01-03"),
                _make_event("u1", "f1", "delete", "2026-01-04"),
            ]
        )
        # Note: delete makes later events implausible in real data, but
        # this is a synthetic unit test isolating feature logic, not a
        # generator-validity test.
        meta_row = _file_meta_row()
        feats = compute_features_for_snapshot(events, meta_row, "u1", "f1", snapshot_time)
        self.assertTrue(feats["never_accessed"])
        self.assertEqual(feats["access_count_all_time"], 0)


if __name__ == "__main__":
    unittest.main()
