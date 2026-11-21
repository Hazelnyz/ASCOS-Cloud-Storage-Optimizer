import unittest
import warnings

import pandas as pd

from ml.config import ALL_EVENT_TYPES
from ml.data.synthetic_generator import generate_synthetic_dataset


class TestSyntheticGeneratorReproducibility(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings("ignore", category=UserWarning)

    def test_same_seed_produces_identical_events(self):
        ev1, meta1 = generate_synthetic_dataset(seed=123, n_users=5, sim_days=60, verbose=False)
        ev2, meta2 = generate_synthetic_dataset(seed=123, n_users=5, sim_days=60, verbose=False)
        pd.testing.assert_frame_equal(ev1, ev2)
        pd.testing.assert_frame_equal(meta1, meta2)

    def test_different_seed_produces_different_events(self):
        ev1, _ = generate_synthetic_dataset(seed=1, n_users=5, sim_days=60, verbose=False)
        ev2, _ = generate_synthetic_dataset(seed=2, n_users=5, sim_days=60, verbose=False)
        # Different seeds should not coincidentally produce identical event logs.
        self.assertFalse(ev1.equals(ev2))

    def test_default_seed_is_reproducible_across_repeated_calls(self):
        ev1, meta1 = generate_synthetic_dataset(verbose=False)
        ev2, meta2 = generate_synthetic_dataset(verbose=False)
        pd.testing.assert_frame_equal(ev1, ev2)
        pd.testing.assert_frame_equal(meta1, meta2)


class TestSyntheticGeneratorValidity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=UserWarning)
        cls.events, cls.meta = generate_synthetic_dataset(
            seed=7, n_users=10, sim_days=90, verbose=False
        )

    def test_event_types_are_within_spec_enum(self):
        observed = set(self.events["event_type"].unique())
        self.assertTrue(observed.issubset(ALL_EVENT_TYPES))

    def test_required_columns_present(self):
        expected_event_cols = {
            "event_id",
            "user_id",
            "file_id",
            "event_type",
            "timestamp",
            "source_ip",
            "device_context",
        }
        self.assertTrue(expected_event_cols.issubset(set(self.events.columns)))

        expected_meta_cols = {
            "file_id",
            "user_id",
            "upload_date",
            "file_type",
            "file_size_bucket",
            "directory_category",
            "current_storage_tier",
            "protected_flag",
        }
        self.assertTrue(expected_meta_cols.issubset(set(self.meta.columns)))

    def test_event_ids_are_unique(self):
        self.assertEqual(self.events["event_id"].nunique(), len(self.events))

    def test_no_events_before_file_upload_date(self):
        merged = self.events.merge(
            self.meta[["file_id", "upload_date"]], on="file_id", how="left"
        )
        self.assertTrue((merged["timestamp"] >= merged["upload_date"]).all())

    def test_no_events_after_a_files_delete_event(self):
        deletes = self.events[self.events["event_type"] == "delete"]
        for _, del_row in deletes.iterrows():
            later = self.events[
                (self.events["file_id"] == del_row["file_id"])
                & (self.events["timestamp"] > del_row["timestamp"])
            ]
            self.assertEqual(
                len(later), 0, msg=f"found events after delete for file {del_row['file_id']}"
            )

    def test_synthetic_data_is_labeled(self):
        self.assertEqual(self.events.attrs.get("data_source"), "synthetic_demo_data")
        self.assertEqual(self.meta.attrs.get("data_source"), "synthetic_demo_data")
        self.assertIn("SYNTHETIC", self.events.attrs.get("disclaimer", ""))

    def test_generator_emits_synthetic_data_warning(self):
        with self.assertWarns(UserWarning):
            generate_synthetic_dataset(seed=99, n_users=3, sim_days=30, verbose=False)


if __name__ == "__main__":
    unittest.main()
