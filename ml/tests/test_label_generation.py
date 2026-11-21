import unittest

import pandas as pd

from ml.labels.label_generation import generate_labels, generate_snapshots


def _make_event(user_id, file_id, event_type, timestamp):
    return {
        "event_id": f"{file_id}-{event_type}-{timestamp}",
        "user_id": user_id,
        "file_id": file_id,
        "event_type": event_type,
        "timestamp": pd.Timestamp(timestamp),
        "source_ip": "10.0.0.1",
        "device_context": "web",
    }


class TestLabelHorizonCorrectness(unittest.TestCase):
    def test_access_within_horizon_labels_positive(self):
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-08"),  # 3 days after snapshot
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": pd.Timestamp("2026-01-05")}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 1)

    def test_access_exactly_at_horizon_boundary_labels_positive(self):
        """(T, T+horizon] is inclusive of the right edge."""
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", snapshot_time + pd.Timedelta(days=7)),
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": snapshot_time}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 1)

    def test_access_one_second_past_horizon_labels_negative(self):
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event(
                    "u1", "f1", "read", snapshot_time + pd.Timedelta(days=7, seconds=1)
                ),
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": snapshot_time}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 0)

    def test_access_at_exactly_snapshot_time_does_not_count_as_future(self):
        """(T, T+horizon] is exclusive of T itself -- an access AT T is
        "the present", not future evidence of re-access."""
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", snapshot_time),
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": snapshot_time}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 0)

    def test_access_before_snapshot_time_does_not_count(self):
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "read", "2026-01-02"),
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": snapshot_time}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 0)

    def test_no_access_events_at_all_labels_negative(self):
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-01")])
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": pd.Timestamp("2026-01-05")}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 0)

    def test_write_or_share_in_horizon_does_not_count_as_access(self):
        """Only read/download count -- write/delete/share must not
        produce a positive label."""
        snapshot_time = pd.Timestamp("2026-01-05")
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f1", "write", "2026-01-06"),
                _make_event("u1", "f1", "share", "2026-01-07"),
                _make_event("u1", "f1", "delete", "2026-01-08"),
            ]
        )
        snapshots = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "snapshot_time": snapshot_time}]
        )
        labeled = generate_labels(events, snapshots, horizon_days=7)
        self.assertEqual(labeled.loc[0, "label"], 0)


class TestSnapshotSlidingWindow(unittest.TestCase):
    def test_snapshots_start_at_upload_date(self):
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-01")])
        meta = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "upload_date": pd.Timestamp("2026-01-01")}]
        )
        snaps = generate_snapshots(
            events, meta, horizon_days=7, cadence_days=3,
            observation_end=pd.Timestamp("2026-02-01"),
        )
        self.assertEqual(snaps["snapshot_time"].min(), pd.Timestamp("2026-01-01"))

    def test_snapshots_spaced_by_cadence(self):
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-01")])
        meta = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "upload_date": pd.Timestamp("2026-01-01")}]
        )
        snaps = generate_snapshots(
            events, meta, horizon_days=7, cadence_days=3,
            observation_end=pd.Timestamp("2026-01-20"),
        )
        times = sorted(snaps["snapshot_time"].tolist())
        diffs = [(t2 - t1).days for t1, t2 in zip(times, times[1:])]
        self.assertTrue(all(d == 3 for d in diffs))

    def test_no_snapshot_has_a_label_window_beyond_observation_end(self):
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-01")])
        meta = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "upload_date": pd.Timestamp("2026-01-01")}]
        )
        observation_end = pd.Timestamp("2026-01-20")
        horizon_days = 7
        snaps = generate_snapshots(
            events, meta, horizon_days=horizon_days, cadence_days=3,
            observation_end=observation_end,
        )
        max_label_window_end = snaps["snapshot_time"].max() + pd.Timedelta(days=horizon_days)
        self.assertLessEqual(max_label_window_end, observation_end)

    def test_file_uploaded_too_close_to_observation_end_produces_no_snapshots(self):
        events = pd.DataFrame([_make_event("u1", "f1", "write", "2026-01-19")])
        meta = pd.DataFrame(
            [{"user_id": "u1", "file_id": "f1", "upload_date": pd.Timestamp("2026-01-19")}]
        )
        # Only 1 day of runway left, horizon is 7 -- no valid snapshot.
        snaps = generate_snapshots(
            events, meta, horizon_days=7, cadence_days=3,
            observation_end=pd.Timestamp("2026-01-20"),
        )
        self.assertEqual(len(snaps), 0)

    def test_multiple_files_produce_independent_snapshot_series(self):
        events = pd.DataFrame(
            [
                _make_event("u1", "f1", "write", "2026-01-01"),
                _make_event("u1", "f2", "write", "2026-01-10"),
            ]
        )
        meta = pd.DataFrame(
            [
                {"user_id": "u1", "file_id": "f1", "upload_date": pd.Timestamp("2026-01-01")},
                {"user_id": "u1", "file_id": "f2", "upload_date": pd.Timestamp("2026-01-10")},
            ]
        )
        snaps = generate_snapshots(
            events, meta, horizon_days=7, cadence_days=3,
            observation_end=pd.Timestamp("2026-02-01"),
        )
        self.assertTrue((snaps[snaps["file_id"] == "f1"]["snapshot_time"] >= pd.Timestamp("2026-01-01")).all())
        self.assertTrue((snaps[snaps["file_id"] == "f2"]["snapshot_time"] >= pd.Timestamp("2026-01-10")).all())


if __name__ == "__main__":
    unittest.main()
