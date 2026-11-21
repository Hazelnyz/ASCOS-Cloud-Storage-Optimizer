"""
Tests for inference components: policy, protected_gate, bandit, ModelBundle.top_reasons.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, Mock

import pandas as pd

from ml.inference import policy, protected_gate, bandit, predictor


class TestPolicyBands(unittest.TestCase):
    """Test policy.py band edges with rounding to avoid float precision issues."""

    def test_policy_bands_boundary_values(self):
        """Test p_access at exact boundaries and edge cases."""
        test_cases = [
            (0.0, ["COLD"]),
            (0.19, ["COLD"]),
            (0.2, ["WARM", "COLD"]),
            (0.3, ["WARM", "COLD"]),  # [0.2, 0.4) -> WARM+COLD
            (0.4, ["WARM"]),
            (0.6, ["HOT", "WARM"]),
            (0.7, ["HOT", "WARM"]),
            (0.8, ["HOT"]),
            (1.0, ["HOT"]),
        ]

        for p_access, expected in test_cases:
            with self.subTest(p_access=p_access):
                result = policy.generate_candidate_tiers(p_access)
                self.assertEqual(result, expected, f"p_access={p_access} expected {expected}, got {result}")

    def test_policy_invalid_p_access(self):
        """Test that invalid p_access values raise ValueError."""
        with self.assertRaises(ValueError):
            policy.generate_candidate_tiers(-0.1)
        with self.assertRaises(ValueError):
            policy.generate_candidate_tiers(1.5)


class TestApplyCostSafetyConstraint(unittest.TestCase):
    """Test cost/safety constraint downgrade logic."""

    def test_cold_with_high_penalty_downgrades_to_warm(self):
        """Cold tier with high retrieval penalty should downgrade to Warm."""
        result = policy.apply_cost_safety_constraint("COLD", retrieval_cost_penalty_high=True)
        self.assertEqual(result, "WARM")

    def test_cold_without_penalty_remains_cold(self):
        """Cold tier without penalty remains Cold."""
        result = policy.apply_cost_safety_constraint("COLD", retrieval_cost_penalty_high=False)
        self.assertEqual(result, "COLD")

    def test_hot_with_penalty_remains_hot(self):
        """Hot tier is unaffected by penalty."""
        result = policy.apply_cost_safety_constraint("HOT", retrieval_cost_penalty_high=True)
        self.assertEqual(result, "HOT")

    def test_warm_with_penalty_remains_warm(self):
        """Warm tier is unaffected by penalty."""
        result = policy.apply_cost_safety_constraint("WARM", retrieval_cost_penalty_high=True)
        self.assertEqual(result, "WARM")


class TestProtectedGate(unittest.TestCase):
    """Test protected file hard gate logic."""

    def test_protected_cold_returns_restore_action(self):
        """Protected file in Cold tier should return restore-to-hot action."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"user_id": "user123", "file_id": "file1"}}

        with patch.object(protected_gate, "_table", return_value=mock_table):
            result = protected_gate.check_hard_gate(
                user_id="user123",
                file_id="file1",
                current_storage_tier="COLD",
            )

        self.assertTrue(result.is_protected)
        self.assertEqual(result.action, "bypass_bandit_restore_to_hot")

    def test_protected_hot_bypasses_bandit(self):
        """Protected file in Hot tier bypasses bandit but doesn't restore."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"user_id": "user123", "file_id": "file1"}}

        with patch.object(protected_gate, "_table", return_value=mock_table):
            result = protected_gate.check_hard_gate(
                user_id="user123",
                file_id="file1",
                current_storage_tier="HOT",
            )

        self.assertTrue(result.is_protected)
        self.assertEqual(result.action, "bypass_bandit_no_change")

    def test_unprotected_proceeds_to_policy(self):
        """Unprotected file should proceed to policy and bandit."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # No item = not protected

        with patch.object(protected_gate, "_table", return_value=mock_table):
            result = protected_gate.check_hard_gate(
                user_id="user123",
                file_id="file1",
                current_storage_tier="WARM",
            )

        self.assertFalse(result.is_protected)
        self.assertEqual(result.action, "proceed")


class TestBandit(unittest.TestCase):
    """Test Thompson Sampling bandit with mocked DynamoDB."""

    def setUp(self):
        """Set up mocks for DynamoDB."""
        self.mock_table = MagicMock()
        self.mock_table.get_item.return_value = {}  # No existing state

    def test_bandit_single_candidate_returns_it(self):
        """Single candidate should be returned deterministically."""
        candidates = ["HOT"]
        
        with patch.object(bandit, "_table", return_value=self.mock_table):
            choice = bandit.choose_tier(
                user_id="user123",
                candidates=candidates,
                p_access=0.9,
                file_type="pdf",
                file_age_days=30,
                current_tier="HOT",
            )

        self.assertEqual(choice.chosen_tier, "HOT")
        self.assertEqual(choice.context, "trivial_single_candidate")

    def test_bandit_samples_only_from_candidates(self):
        """Bandit should only sample from provided candidate tiers."""
        candidates = ["HOT", "WARM"]
        
        with patch.object(bandit, "_table", return_value=self.mock_table):
            choice = bandit.choose_tier(
                user_id="user123",
                candidates=candidates,
                p_access=0.7,
                file_type="pdf",
                file_age_days=30,
                current_tier="WARM",
            )

        self.assertIn(choice.chosen_tier, candidates)

    def test_bandit_reward_confirmed_increments_alpha(self):
        """Reward=confirmed (+1) should increment alpha count."""
        self.mock_table.update_item.return_value = None

        with patch.object(bandit, "_table", return_value=self.mock_table):
            bandit.update_reward(
                user_id="user123",
                context="test_context",
                chosen_tier="HOT",
                reward=1,
            )

        # Verify update_item was called
        self.mock_table.update_item.assert_called_once()

    def test_bandit_reward_overridden_increments_beta(self):
        """Reward=overridden (-1) should increment beta count."""
        self.mock_table.update_item.return_value = None

        with patch.object(bandit, "_table", return_value=self.mock_table):
            bandit.update_reward(
                user_id="user123",
                context="test_context",
                chosen_tier="COLD",
                reward=-1,
            )

        # Verify update_item was called
        self.mock_table.update_item.assert_called_once()

    def test_bandit_reward_no_response_skips_update(self):
        """Reward=no_response (0) should skip DynamoDB update."""
        self.mock_table.update_item.return_value = None

        with patch.object(bandit, "_table", return_value=self.mock_table):
            bandit.update_reward(
                user_id="user123",
                context="test_context",
                chosen_tier="WARM",
                reward=0,
            )

        # Verify update_item was NOT called
        self.mock_table.update_item.assert_not_called()

    def test_context_key_format(self):
        """Context key should include all required components."""
        key = bandit.context_key(p_access=0.65, file_type="pdf", file_age_days=45, current_tier="WARM")
        self.assertIn("mid", key)  # p_access bucket
        self.assertIn("pdf", key)
        self.assertIn("established", key)  # file_age bucket
        self.assertIn("WARM", key)


class TestModelBundleTopReasons(unittest.TestCase):
    """Test ModelBundle.top_reasons with stub SHAP explainer."""

    def test_top_reasons_returns_top_n_features(self):
        """top_reasons should return top N features by absolute contribution."""
        # Create a fake shap module with TreeExplainer
        fake_shap_module = MagicMock()
        mock_explainer = MagicMock()
        # Return list-of-arrays form (binary classifier)
        # The code uses raw[-1][0], so the last array should have the expected values
        import numpy as np
        mock_explainer.shap_values.return_value = [np.array([[0.1, 0.2, -0.1, 0.3, -0.05]]), np.array([[0.5, -0.3, 0.2, -0.1, 0.05]])]
        fake_shap_module.TreeExplainer.return_value = mock_explainer
        
        mock_booster = MagicMock()
        mock_booster.predict.return_value = [0.7]
        
        with patch.dict(sys.modules, {"shap": fake_shap_module}):
            with patch("lightgbm.Booster", return_value=mock_booster):
                with patch("ml.inference.predictor.model_store.resolve_artifact_paths"):
                    with patch("builtins.open"):
                        with patch("json.load", return_value={
                            "feature_columns": ["feat1", "feat2", "feat3", "feat4", "feat5"],
                            "categorical_columns": [],
                            "categorical_category_maps": {}
                        }):
                            # Build with __new__ to bypass real constructor
                            bundle = predictor.ModelBundle.__new__(predictor.ModelBundle)
                            bundle._explainer = mock_explainer
                            bundle.feature_columns = ["feat1", "feat2", "feat3", "feat4", "feat5"]
                            bundle.categorical_columns = []
                            bundle.categorical_category_maps = {}
                            
                            feature_dict = {"feat1": 1, "feat2": 2, "feat3": 3, "feat4": 4, "feat5": 5}
                            result = bundle.top_reasons(feature_dict, n=3)
                            
                            # Should return top 3 by absolute value: 0.5, -0.3, 0.2
                            self.assertEqual(len(result), 3)
                            self.assertEqual(result[0]["feature"], "feat1")
                            self.assertEqual(result[0]["contribution"], "+0.5000")
                            self.assertEqual(result[1]["feature"], "feat2")
                            self.assertEqual(result[1]["contribution"], "-0.3000")

    def test_top_reasons_formats_contributions_as_strings(self):
        """Contributions should be formatted as signed strings with 4 decimal places."""
        # Create a fake shap module with TreeExplainer
        fake_shap_module = MagicMock()
        mock_explainer = MagicMock()
        # Return list-of-arrays form (binary classifier)
        # The code uses raw[-1][0], so the last array should have the expected values
        import numpy as np
        mock_explainer.shap_values.return_value = [np.array([[0.5, 0.3]]), np.array([[1.23456, -0.98765]])]
        fake_shap_module.TreeExplainer.return_value = mock_explainer
        
        mock_booster = MagicMock()
        mock_booster.predict.return_value = [0.5]
        
        with patch.dict(sys.modules, {"shap": fake_shap_module}):
            with patch("lightgbm.Booster", return_value=mock_booster):
                with patch("ml.inference.predictor.model_store.resolve_artifact_paths"):
                    with patch("builtins.open"):
                        with patch("json.load", return_value={
                            "feature_columns": ["feat1", "feat2"],
                            "categorical_columns": [],
                            "categorical_category_maps": {}
                        }):
                            # Build with __new__ to bypass real constructor
                            bundle = predictor.ModelBundle.__new__(predictor.ModelBundle)
                            bundle._explainer = mock_explainer
                            bundle.feature_columns = ["feat1", "feat2"]
                            bundle.categorical_columns = []
                            bundle.categorical_category_maps = {}
                            
                            feature_dict = {"feat1": 1, "feat2": 2}
                            result = bundle.top_reasons(feature_dict, n=2)
                            
                            # Check formatting
                            self.assertEqual(result[0]["contribution"], "+1.2346")
                            self.assertEqual(result[1]["contribution"], "-0.9877")


class TestPredictorBanditContext(unittest.TestCase):
    """Test that bandit_context is included in prediction dict."""

    def test_bandit_context_included_when_bandit_runs(self):
        """bandit_context should be included when bandit makes a choice."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # Not protected
        
        with patch.object(protected_gate, "_table", return_value=mock_table):
            with patch.object(bandit, "_table", return_value=mock_table):
                with patch.object(predictor, "_get_bundle") as mock_get_bundle:
                    mock_bundle = MagicMock()
                    mock_bundle.predict_p_access.return_value = 0.7
                    mock_bundle.top_reasons.return_value = []
                    mock_bundle.metadata = {"feature_schema_version": 1}
                    mock_get_bundle.return_value = mock_bundle
                    
                    with patch("ml.inference.predictor.compute_features_for_snapshot") as mock_features:
                        mock_features.return_value = {
                            "file_type": "pdf",
                            "file_age_days": 30,
                            "current_storage_tier": "WARM"
                        }
                        
                        with patch.object(policy, "generate_candidate_tiers", return_value=["HOT", "WARM"]):
                            with patch.object(bandit, "choose_tier", return_value=bandit.BanditChoice("HOT", "test_context")):
                                with patch.object(policy, "apply_cost_safety_constraint", return_value="HOT"):
                                    prediction = predictor.predict_one(
                                        user_id="user123",
                                        file_id="file1",
                                        events_df=pd.DataFrame(),
                                        file_metadata_row=pd.Series({"current_storage_tier": "WARM"}),
                                        model_version="v1"
                                    )
                    
                    self.assertIn("bandit_context", prediction)
                    self.assertEqual(prediction["bandit_context"], "test_context")

    def test_bandit_context_null_when_protected(self):
        """bandit_context should be null when file is protected."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"user_id": "user123", "file_id": "file1"}}  # Protected
        
        with patch.object(protected_gate, "_table", return_value=mock_table):
            with patch.object(predictor, "_get_bundle") as mock_get_bundle:
                mock_bundle = MagicMock()
                mock_bundle.predict_p_access.return_value = 0.7
                mock_bundle.top_reasons.return_value = []
                mock_bundle.metadata = {"feature_schema_version": 1}
                mock_get_bundle.return_value = mock_bundle
                
                with patch("ml.inference.predictor.compute_features_for_snapshot") as mock_features:
                    mock_features.return_value = {
                        "file_type": "pdf",
                        "file_age_days": 30,
                        "current_storage_tier": "WARM"
                    }
                    
                    prediction = predictor.predict_one(
                        user_id="user123",
                        file_id="file1",
                        events_df=pd.DataFrame(),
                        file_metadata_row=pd.Series({"current_storage_tier": "WARM"}),
                        model_version="v1"
                    )
                
                self.assertIn("bandit_context", prediction)
                self.assertIsNone(prediction["bandit_context"])

    def test_bandit_context_is_string_or_none_for_dynamodb_safety(self):
        """bandit_context must be a string or None (no floats) for DynamoDB write safety."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # Not protected
        
        with patch.object(protected_gate, "_table", return_value=mock_table):
            with patch.object(bandit, "_table", return_value=mock_table):
                with patch.object(predictor, "_get_bundle") as mock_get_bundle:
                    mock_bundle = MagicMock()
                    mock_bundle.predict_p_access.return_value = 0.7
                    mock_bundle.top_reasons.return_value = []
                    mock_bundle.metadata = {"feature_schema_version": 1}
                    mock_get_bundle.return_value = mock_bundle
                    
                    with patch("ml.inference.predictor.compute_features_for_snapshot") as mock_features:
                        mock_features.return_value = {
                            "file_type": "pdf",
                            "file_age_days": 30,
                            "current_storage_tier": "WARM"
                        }
                        
                        with patch.object(policy, "generate_candidate_tiers", return_value=["HOT", "WARM"]):
                            with patch.object(bandit, "choose_tier", return_value=bandit.BanditChoice("HOT", "test_context_string")):
                                with patch.object(policy, "apply_cost_safety_constraint", return_value="HOT"):
                                    prediction = predictor.predict_one(
                                        user_id="user123",
                                        file_id="file1",
                                        events_df=pd.DataFrame(),
                                        file_metadata_row=pd.Series({"current_storage_tier": "WARM"}),
                                        model_version="v1"
                                    )
                    
                    # bandit_context must be string or None (no floats for DynamoDB)
                    bandit_context = prediction["bandit_context"]
                    self.assertTrue(
                        bandit_context is None or isinstance(bandit_context, str),
                        f"bandit_context must be str or None, got {type(bandit_context).__name__}"
                    )


if __name__ == "__main__":
    unittest.main()
