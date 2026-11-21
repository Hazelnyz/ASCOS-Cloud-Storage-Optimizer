import unittest

import pandas as pd

from ml.splitting.chronological_split import chronological_split


def _snapshots(dates, user_id="u1", file_id="f1"):
    return pd.DataFrame(
        [{"user_id": user_id, "file_id": file_id, "snapshot_time": pd.Timestamp(d)} for d in dates]
    )


class TestChronologicalSplit(unittest.TestCase):
    def test_embargo_shorter_than_horizon_raises(self):
        snaps = _snapshots(["2026-01-01", "2026-02-01"])
        with self.assertRaises(ValueError):
            chronological_split(
                snaps,
                split_date=pd.Timestamp("2026-01-15"),
                horizon_days=7,
                embargo_days=3,
            )

    def test_embargo_equal_to_horizon_is_allowed(self):
        snaps = _snapshots(["2026-01-01", "2026-02-01"])
        # Should not raise.
        chronological_split(
            snaps, split_date=pd.Timestamp("2026-01-15"), horizon_days=7, embargo_days=7
        )

    def test_train_test_and_embargo_partition_all_rows(self):
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates)
        result = chronological_split(
            snaps, split_date=pd.Timestamp("2026-02-01"), horizon_days=7, embargo_days=7
        )
        total = len(result.train) + len(result.test) + len(result.dropped_embargo)
        self.assertEqual(total, len(snaps))

    def test_no_train_snapshot_label_window_crosses_split_date(self):
        """The actual leakage invariant the embargo exists to protect:
        for every train snapshot T, T + horizon_days <= split_date."""
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates)
        horizon_days = 7
        embargo_days = 10  # deliberately wider than horizon
        split_date = pd.Timestamp("2026-02-01")
        result = chronological_split(
            snaps, split_date=split_date, horizon_days=horizon_days, embargo_days=embargo_days
        )
        label_window_ends = result.train["snapshot_time"] + pd.Timedelta(days=horizon_days)
        self.assertTrue((label_window_ends <= split_date).all())

    def test_all_test_snapshots_strictly_after_split_date(self):
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates)
        split_date = pd.Timestamp("2026-02-01")
        result = chronological_split(
            snaps, split_date=split_date, horizon_days=7, embargo_days=7
        )
        self.assertTrue((result.test["snapshot_time"] > split_date).all())

    def test_all_train_snapshots_at_or_before_train_cutoff(self):
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates)
        split_date = pd.Timestamp("2026-02-01")
        embargo_days = 7
        result = chronological_split(
            snaps, split_date=split_date, horizon_days=7, embargo_days=embargo_days
        )
        train_cutoff = split_date - pd.Timedelta(days=embargo_days)
        self.assertTrue((result.train["snapshot_time"] <= train_cutoff).all())

    def test_wider_embargo_shrinks_or_maintains_train_set(self):
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates)
        split_date = pd.Timestamp("2026-02-01")
        narrow = chronological_split(
            snaps, split_date=split_date, horizon_days=7, embargo_days=7
        )
        wide = chronological_split(
            snaps, split_date=split_date, horizon_days=7, embargo_days=20
        )
        self.assertLessEqual(len(wide.train), len(narrow.train))

    def test_no_random_shuffling_train_is_strictly_earlier_than_test(self):
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="D")
        snaps = _snapshots(dates).sample(frac=1, random_state=0).reset_index(drop=True)
        split_date = pd.Timestamp("2026-02-01")
        result = chronological_split(
            snaps, split_date=split_date, horizon_days=7, embargo_days=7
        )
        if len(result.train) and len(result.test):
            self.assertLess(result.train["snapshot_time"].max(), result.test["snapshot_time"].min())


if __name__ == "__main__":
    unittest.main()
