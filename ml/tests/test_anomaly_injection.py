"""
Test for anomaly injected burst evaluation (evaluation only, never for training).
"""

import unittest
from unittest.mock import MagicMock

import pandas as pd

from ml.anomaly import synthetic_injection, feature_engineering, score


class TestAnomalyInjectedBurst(unittest.TestCase):
    """Test that injected anomaly bursts score above normal behavior."""

    def test_inject_delete_burst_creates_anomalous_features(self):
        """Injected delete burst should spike deletes_last_1h and events_last_1h."""
        # Create normal events
        events_df = pd.DataFrame([
            {"user_id": "user123", "event_type": "download", "timestamp": pd.Timestamp("2026-01-15T10:00:00"), "file_id": "f1"},
            {"user_id": "user123", "event_type": "read", "timestamp": pd.Timestamp("2026-01-15T10:05:00"), "file_id": "f2"},
        ])

        # Create snapshot times
        snapshot_times = [
            pd.Timestamp("2026-01-15T10:30:00"),
            pd.Timestamp("2026-01-15T11:00:00"),
            pd.Timestamp("2026-01-15T11:30:00"),
        ]

        # Inject delete burst
        eval_df = synthetic_injection.inject_delete_burst(
            events_df=events_df,
            user_id="user123",
            snapshot_times=snapshot_times,
            burst_fraction=0.5,  # 50% of snapshots get burst
            burst_size=20,
            seed=42,
        )

        # Verify DataFrame has expected columns
        self.assertIn("deletes_last_1h", eval_df.columns)
        self.assertIn("events_last_1h", eval_df.columns)
        self.assertIn("is_injected_anomaly", eval_df.columns)

        # Verify some rows are marked as injected anomalies
        injected_rows = eval_df[eval_df["is_injected_anomaly"] == True]
        self.assertGreater(len(injected_rows), 0)

        # Verify injected rows have spiked delete counts
        for _, row in injected_rows.iterrows():
            self.assertEqual(row["deletes_last_1h"], 20)
            self.assertGreaterEqual(row["events_last_1h"], 20)

    def test_inject_failed_login_burst_raises_not_implemented(self):
        """Failed login burst should raise NotImplementedError (Cognito not wired)."""
        events_df = pd.DataFrame()
        snapshot_times = [pd.Timestamp("2026-01-15T10:00:00")]

        with self.assertRaises(NotImplementedError) as cm:
            synthetic_injection.inject_failed_login_burst(
                events_df=events_df,
                user_id="user123",
                snapshot_times=snapshot_times,
            )

        self.assertIn("Cognito", str(cm.exception))
        self.assertIn("not wired", str(cm.exception))

    def test_evaluate_detection_computes_metrics(self):
        """evaluate_detection should compute detection rate and false positive rate."""
        # Create mock evaluation DataFrame with injected anomalies
        eval_df = pd.DataFrame([
            {"is_injected_anomaly": True, "severity": "High", "score": -1.5},
            {"is_injected_anomaly": True, "severity": "Medium", "score": -0.8},
            {"is_injected_anomaly": True, "severity": "Low", "score": 0.2},  # Missed detection
            {"is_injected_anomaly": False, "severity": "Low", "score": 1.0},
            {"is_injected_anomaly": False, "severity": "Medium", "score": 0.5},  # False positive
            {"is_injected_anomaly": False, "severity": "Low", "score": 1.2},
        ])

        # Mock score function
        def mock_score_fn(feature_row, bundle):
            return feature_row["score"], feature_row["severity"]

        mock_bundle = MagicMock()

        result = synthetic_injection.evaluate_detection(
            model_bundle=mock_bundle,
            eval_df=eval_df,
            score_fn=mock_score_fn,
        )

        # Verify metrics are computed
        self.assertIn("detection_rate", result)
        self.assertIn("false_positive_rate", result)
        self.assertIn("n_injected_anomalies", result)
        self.assertIn("n_normal", result)

        # Detection rate: 2 out of 3 detected (High + Medium)
        expected_detection_rate = 2 / 3
        self.assertAlmostEqual(result["detection_rate"], expected_detection_rate)

        # False positive rate: 1 out of 3 normal flagged (Medium)
        expected_fpr = 1 / 3
        self.assertAlmostEqual(result["false_positive_rate"], expected_fpr)

    def test_injected_anomaly_never_used_for_training(self):
        """Verify injected anomaly DataFrame is tagged as evaluation-only."""
        # Provide minimal events_df with required columns for feature engineering
        events_df = pd.DataFrame([
            {"user_id": "user123", "event_type": "download", "timestamp": pd.Timestamp("2026-01-15T09:00:00"), "file_id": "f1"},
        ])
        snapshot_times = [pd.Timestamp("2026-01-15T10:00:00")]

        eval_df = synthetic_injection.inject_delete_burst(
            events_df=events_df,
            user_id="user123",
            snapshot_times=snapshot_times,
        )

        # Verify disclaimer attribute is set
        self.assertIn("disclaimer", eval_df.attrs)
        self.assertIn("INJECTED anomalies", eval_df.attrs["disclaimer"])
        self.assertIn("never pass this to train_isolation_forest", eval_df.attrs["disclaimer"])

        # Verify injection_type is recorded
        self.assertEqual(eval_df.attrs["injection_type"], "delete_burst")

    def test_evaluate_detection_raises_on_missing_anomaly_flag(self):
        """evaluate_detection should raise if is_injected_anomaly column is missing."""
        eval_df = pd.DataFrame([{"severity": "High", "score": -1.0}])

        mock_bundle = MagicMock()
        mock_score_fn = lambda row, bundle: (row["score"], row["severity"])

        with self.assertRaises(ValueError) as cm:
            synthetic_injection.evaluate_detection(
                model_bundle=mock_bundle,
                eval_df=eval_df,
                score_fn=mock_score_fn,
            )

        self.assertIn("inject_delete_burst", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
