import unittest

import numpy as np

from ml.evaluation.evaluate_lightgbm import (
    _brier_score,
    _calibration_bins,
    _confusion_counts,
    _pr_auc,
    _precision_recall_f1,
    _roc_auc,
)


class TestROCAUC(unittest.TestCase):
    def test_perfect_separation_gives_auc_one(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        scores = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        self.assertAlmostEqual(_roc_auc(y, scores), 1.0)

    def test_perfectly_reversed_gives_auc_zero(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        scores = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1])
        self.assertAlmostEqual(_roc_auc(y, scores), 0.0)

    def test_all_tied_scores_gives_auc_half(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        scores = np.array([0.5] * 6)
        self.assertAlmostEqual(_roc_auc(y, scores), 0.5)

    def test_no_positives_returns_nan(self):
        y = np.array([0, 0, 0])
        scores = np.array([0.1, 0.2, 0.3])
        self.assertTrue(np.isnan(_roc_auc(y, scores)))


class TestPRAUC(unittest.TestCase):
    def test_perfect_separation_gives_pr_auc_one(self):
        y = np.array([0, 0, 0, 1, 1, 1])
        scores = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        self.assertAlmostEqual(_pr_auc(y, scores), 1.0)

    def test_no_positives_returns_nan(self):
        y = np.array([0, 0, 0])
        scores = np.array([0.1, 0.2, 0.3])
        self.assertTrue(np.isnan(_pr_auc(y, scores)))


class TestConfusionAndPRF(unittest.TestCase):
    def test_known_confusion_matrix(self):
        y_true = np.array([1, 1, 0, 0, 1])
        y_pred = np.array([1, 0, 0, 0, 1])
        cm = _confusion_counts(y_true, y_pred)
        self.assertEqual(cm, {"tp": 2, "tn": 2, "fp": 0, "fn": 1})

    def test_precision_recall_f1_from_known_confusion_matrix(self):
        cm = {"tp": 2, "tn": 2, "fp": 0, "fn": 1}
        precision, recall, f1 = _precision_recall_f1(cm)
        self.assertAlmostEqual(precision, 1.0)
        self.assertAlmostEqual(recall, 2 / 3)
        self.assertAlmostEqual(f1, 2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))

    def test_zero_division_cases_return_zero_not_nan_or_error(self):
        cm = {"tp": 0, "tn": 5, "fp": 0, "fn": 0}
        precision, recall, f1 = _precision_recall_f1(cm)
        self.assertEqual((precision, recall, f1), (0.0, 0.0, 0.0))


class TestBrierScore(unittest.TestCase):
    def test_known_brier_score(self):
        probs = np.array([0.9, 0.1, 0.8, 0.2])
        y = np.array([1, 0, 1, 0])
        # errors: 0.01, 0.01, 0.04, 0.04 -> mean = 0.025
        self.assertAlmostEqual(_brier_score(y, probs), 0.025)

    def test_perfect_predictions_give_zero_brier(self):
        probs = np.array([1.0, 0.0, 1.0, 0.0])
        y = np.array([1, 0, 1, 0])
        self.assertAlmostEqual(_brier_score(y, probs), 0.0)


class TestCalibrationBins(unittest.TestCase):
    def test_bin_count_matches_n_bins(self):
        y = np.array([0, 1, 0, 1, 1, 0])
        probs = np.array([0.05, 0.95, 0.15, 0.55, 0.85, 0.25])
        bins = _calibration_bins(y, probs, n_bins=10)
        self.assertEqual(len(bins), 10)

    def test_every_prediction_falls_into_exactly_one_bin(self):
        y = np.array([0, 1, 0, 1, 1, 0])
        probs = np.array([0.05, 0.95, 0.15, 0.55, 0.85, 0.25])
        bins = _calibration_bins(y, probs, n_bins=10)
        self.assertEqual(sum(b["n"] for b in bins), len(probs))

    def test_boundary_value_one_is_included(self):
        y = np.array([1])
        probs = np.array([1.0])
        bins = _calibration_bins(y, probs, n_bins=10)
        self.assertEqual(sum(b["n"] for b in bins), 1)


if __name__ == "__main__":
    unittest.main()
