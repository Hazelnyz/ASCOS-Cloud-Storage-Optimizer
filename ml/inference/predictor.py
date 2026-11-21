"""
ml/inference/predictor.py

THE single reusable inference orchestrator. Chains:

    protected gate -> real feature loading -> Phase 3 LightGBM
    inference -> SHAP top reasons -> candidate-tier policy ->
    Thompson Sampling

into one prediction call (`predict_one`). Both the batch driver (this
integration pass) and, later, prediction-fn's real Lambda handler
(once LightGBM/SHAP-in-Lambda packaging -- container image or layer --
is solved) import and call THIS function. No logic is duplicated
between them, and nothing here re-implements what Phase 3 already does.

Reuses, without modification:
  - ml.features.feature_engineering.compute_features_for_snapshot,
    FEATURE_COLUMNS, CATEGORICAL_COLUMNS
  - the trained model artifact + metadata produced by
    ml.modeling.train_lightgbm (training logic itself untouched --
    only two small ADDITIVE fields were captured into its metadata
    output: categorical_category_maps, feature_schema_version)
  - ml.inference.feature_loader / protected_gate / policy / bandit

--- Spec-note flagged per project rule 12 (genuine tension, not
silently resolved) ---
ML_SCHEMA Sec5's diagram reads as if protected files skip LightGBM
entirely ("BYPASS bandit entirely" sits directly under the
"protected_flag == true" branch, with no separate p_access arrow).
But dynamodb.tf's own protected_files design note is more specific and
takes precedence here: "access_event logging and PREDICTION GENERATION
continue completely unaffected for pinned files -- they are a separate
pipeline from tiering execution." This module follows that note: p_access
/ SHAP are ALWAYS computed (so the Predictions UI stays populated and
useful even for protected files), but candidate_tiers / bandit_choice
are skipped whenever the hard gate fires -- matching "BYPASS bandit
entirely" literally, without also silently skipping prediction
generation, which nothing in the spec actually asked for.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ml.config import FEATURE_SCHEMA_VERSION
from ml.features.feature_engineering import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    compute_features_for_snapshot,
)
from ml.inference import bandit, model_store, policy, protected_gate

logger = logging.getLogger(__name__)

MODEL_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "models"


class ModelBundle:
    """
    Loads a trained model + its metadata ONCE, reused across many
    predict_one() calls (cheap to keep warm across a batch run or a
    Lambda container's lifetime later).
    """

    def __init__(self, model_version: str, artifact_dir: Path = MODEL_ARTIFACT_DIR):
        import lightgbm as lgb  # lazy import -- matches train_lightgbm.py's own pattern

        # Resolution itself (local dir vs S3->/tmp cache) is delegated
        # to model_store -- this constructor's own interface/behavior
        # is otherwise UNCHANGED: same two args, same resulting
        # model_path/meta_path locals below, same FileNotFoundError-
        # equivalent failure (now ModelArtifactError, still raised,
        # never swallowed) if either file can't be resolved.
        try:
            paths = model_store.resolve_artifact_paths(
                key=model_version,
                filename_by_role={
                    "model": f"{model_version}.txt",
                    "meta": f"{model_version}.meta.json",
                },
                local_dir=artifact_dir,
                cache_subdir="lgbm",
            )
        except model_store.ModelArtifactError as e:
            raise FileNotFoundError(str(e)) from e  # same exception type callers already expect

        model_path, meta_path = paths["model"], paths["meta"]

        with open(meta_path) as fh:
            self.metadata = json.load(fh)

        self.model_version = model_version
        self.booster = lgb.Booster(model_file=str(model_path))
        self.feature_columns = self.metadata.get("feature_columns", FEATURE_COLUMNS)
        self.categorical_columns = self.metadata.get("categorical_columns", CATEGORICAL_COLUMNS)
        self.category_maps = self.metadata.get("categorical_category_maps", {})
        if not self.category_maps:
            raise ValueError(
                f"model_version={model_version} has no categorical_category_maps in its "
                "metadata -- it was trained before this field was added (see the small, "
                "additive train_lightgbm.py patch delivered alongside this file). Retrain "
                "to produce a compatible artifact; category codes otherwise cannot be "
                "reconstructed correctly at inference time and predictions would be wrong."
            )

        self._explainer = None  # lazy -- SHAP TreeExplainer built on first use

    def _prepare_row(self, feature_dict: dict) -> pd.DataFrame:
        """
        Builds a single-row DataFrame in the exact column order the
        model was trained on, applying the SAVED categorical category
        lists (not whatever this one row happens to contain) -- this
        is what keeps LightGBM's category codes consistent between
        training and inference. See train_lightgbm.py's
        `_align_categorical_columns` docstring for why this matters.
        """
        row = {col: feature_dict.get(col) for col in self.feature_columns}
        df = pd.DataFrame([row])
        for col in self.categorical_columns:
            if col not in df.columns:
                continue
            categories = self.category_maps.get(col)
            if categories:
                df[col] = pd.Categorical(df[col], categories=categories)
            else:
                df[col] = df[col].astype("category")
        return df

    def predict_p_access(self, feature_dict: dict) -> float:
        df = self._prepare_row(feature_dict)
        pred = self.booster.predict(df)
        return float(pred[0])

    def top_reasons(self, feature_dict: dict, n: int = 3) -> list[dict]:
        """
        SHAP.TreeExplainer per-prediction feature contributions (Sec4).
        NOTE: shap's return shape for a raw lgb.Booster (binary
        objective) has varied across shap versions -- the defensive
        unwrapping below handles both "single 2D array" and "list of
        per-class arrays" forms. Verify against your installed shap
        version on first real run; adjust indexing if the contribution
        magnitudes look wrong.
        """
        import shap  # lazy import

        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.booster)

        df = self._prepare_row(feature_dict)
        raw = self._explainer.shap_values(df)

        if isinstance(raw, list):
            # list-of-arrays form (e.g. [class0_contribs, class1_contribs])
            contributions = raw[-1][0]
        else:
            contributions = raw[0] if raw.ndim > 1 else raw

        pairs = list(zip(self.feature_columns, contributions))
        pairs.sort(key=lambda p: abs(p[1]), reverse=True)
        return [{"feature": name, "contribution": f"{val:+.4f}"} for name, val in pairs[:n]]


_bundle_cache: dict[str, ModelBundle] = {}


def _get_bundle(model_version: str) -> ModelBundle:
    if model_version not in _bundle_cache:
        _bundle_cache[model_version] = ModelBundle(model_version)
    return _bundle_cache[model_version]


def predict_one(
    user_id: str,
    file_id: str,
    events_df: pd.DataFrame,
    file_metadata_row: pd.Series,
    model_version: str,
    snapshot_time: pd.Timestamp | None = None,
    retrieval_cost_penalty_high: bool = False,
    run_id: str | None = None,
) -> dict:
    """
    The single reusable inference call for one (user_id, file_id).
    Returns one prediction object in the exact Sec4 schema:
    prediction_id, user_id, file_id, model_version,
        feature_schema_version, prediction_timestamp, p_access,
        candidate_tiers, bandit_choice, top_reasons

    `events_df` / `file_metadata_row` are supplied by the CALLER (the
    batch driver today; prediction-fn later) rather than fetched here
    -- keeps this module free of direct S3/DynamoDB-listing coupling
    beyond what protected_gate/bandit already need, and keeps it
    testable without mocking a full AWS environment for every call.
    """
    if snapshot_time is None:
        snapshot_time = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)

    current_tier = file_metadata_row["current_storage_tier"]

    # --- Sec5 Step 1: protected-file hard gate, checked first ---
    gate = protected_gate.check_hard_gate(user_id, file_id, current_tier)
    logger.info(
        "predict_one user_id=%s file_id=%s gate_action=%s", user_id, file_id, gate.action
    )

    # --- Real feature loading + LightGBM p_access (Sec2/Sec4) ---
    # Always computed, including for gated files -- see module
    # docstring for why (dynamodb.tf's protected_files note).
    feature_dict = compute_features_for_snapshot(
        events_df, file_metadata_row, user_id, file_id, snapshot_time
    )
    bundle = _get_bundle(model_version)
    p_access = bundle.predict_p_access(feature_dict)

    # --- SHAP top reasons (Sec4) ---
    top_reasons = bundle.top_reasons(feature_dict)

    # --- Candidate-tier policy + Thompson Sampling (Sec5 Steps 2-4) ---
    # Skipped entirely if the hard gate fired -- "BYPASS bandit
    # entirely" per Sec5 Step 1.
    if gate.is_protected:
        candidate_tiers: list[str] = []
        bandit_choice = None
        bandit_context = None
    else:
        candidate_tiers = policy.generate_candidate_tiers(p_access)
        choice = bandit.choose_tier(
            user_id=user_id,
            candidates=candidate_tiers,
            p_access=p_access,
            file_type=feature_dict["file_type"],
            file_age_days=feature_dict["file_age_days"],
            current_tier=current_tier,
        )
        bandit_choice = policy.apply_cost_safety_constraint(
            choice.chosen_tier, retrieval_cost_penalty_high
        )
        bandit_context = choice.context

    return {
        "prediction_id": prediction_id_for_run(user_id, file_id, model_version, run_id)
        if run_id is not None else str(uuid.uuid4()),
        "user_id": user_id,
        "file_id": file_id,
        "model_version": model_version,
        "feature_schema_version": bundle.metadata.get(
            "feature_schema_version", FEATURE_SCHEMA_VERSION
        ),
        "prediction_timestamp": datetime.now(timezone.utc).isoformat(),
        "p_access": p_access,
        "candidate_tiers": candidate_tiers,
        "bandit_choice": bandit_choice,
        "bandit_context": bandit_context,
        "top_reasons": top_reasons,
    }


def prediction_id_for_run(user_id: str, file_id: str, model_version: str, run_id: str) -> str:
    """Return a stable prediction key for redelivery of the same worker task."""
    identity = json.dumps([user_id, file_id, model_version, run_id], separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ascos-prediction:{identity}"))
