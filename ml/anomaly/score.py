"""
Live anomaly scoring + severity classification (§7).

This module is what a real anomaly-scorer-fn would call per event, once
Stage 10 Lambda wiring exists (it does not yet -- see ml/README.md).
Deliberately kept separate from train_isolation_forest.py: training
produces artifacts, this module only ever reads them. Same
prediction/training separation already applied elsewhere in this
project (e.g. ml/inference/predictor.py never retrains LightGBM).

Severity output feeds anomaly-scorer-fn's existing (currently unused)
_contain_user() / _publish_alert() activation points -- see
backend/anomaly-scorer-fn/handler.py's own docstring, which documents
those as Stage 10 activation paths placed there on purpose. This
module does not call them itself (it has no AWS dependency at all,
by design) -- that wiring is Stage 10.3, not this file.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

from ml.anomaly.feature_engineering import compute_anomaly_features
from ml.anomaly.train_isolation_forest import GLOBAL_MODEL_KEY

SEVERITY_LOW = "Low"
SEVERITY_MEDIUM = "Medium"
SEVERITY_HIGH = "High"


class AnomalyModelBundle:
    """A loaded model + the exact metadata needed to score consistently
    with how it was trained (column set, dow one-hot columns, severity
    cutoffs) -- never re-derives these from scratch at score time,
    which would risk drifting from what was actually trained on.
    """

    def __init__(self, model, meta: dict):
        self.model = model
        self.meta = meta

    @classmethod
    def load(cls, artifacts_dir: str | Path, key: str) -> "AnomalyModelBundle":
        artifacts_dir = Path(artifacts_dir)
        safe_key = key.strip("_") if key == GLOBAL_MODEL_KEY else key
        model_path = artifacts_dir / f"anomaly_{safe_key}.pkl"
        meta_path = artifacts_dir / f"anomaly_{safe_key}.meta.json"

        if not model_path.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"No trained anomaly model for key={key!r} in {artifacts_dir} "
                f"(expected {model_path.name} + {meta_path.name})."
            )

        with open(model_path, "rb") as f:
            model = pickle.load(f)
        with open(meta_path) as f:
            meta = json.load(f)

        return cls(model, meta)


def load_model_for_user(artifacts_dir: str | Path, user_id: str) -> AnomalyModelBundle:
    """Per-user model if one was trained (dense history); otherwise the
    shared global-fallback model -- mirrors exactly the dense/sparse
    split train_isolation_forest.train_and_save() made at training
    time. Raises if neither exists (e.g. global fallback was never
    trained because every user happened to be dense) -- callers should
    treat that as "no score available", not silently skip scoring.
    """
    try:
        return AnomalyModelBundle.load(artifacts_dir, user_id)
    except FileNotFoundError:
        return AnomalyModelBundle.load(artifacts_dir, GLOBAL_MODEL_KEY)


def _feature_dict_to_vector(feature_row: dict, bundle: AnomalyModelBundle) -> np.ndarray:
    numeric_cols = bundle.meta["numeric_columns"]
    dow_columns = bundle.meta["dow_columns"]

    numeric_values = [float(feature_row.get(c) or 0.0) for c in numeric_cols]
    dow_one_hot = [1.0 if feature_row.get("day_of_week") == d else 0.0 for d in dow_columns]

    return np.array([numeric_values + dow_one_hot], dtype=float)


def classify_severity(score: float, bundle: AnomalyModelBundle) -> str:
    """sklearn's decision_function: LOWER score = MORE anomalous. The
    two cutoffs were computed at training time from that model's own
    score distribution (see train_isolation_forest._save_model_artifact) --
    scoring never recomputes percentiles live, which would make
    severity drift as new events arrive instead of staying anchored to
    the model that's actually deployed.
    """
    if score <= bundle.meta["severity_medium_max_score"]:
        return SEVERITY_HIGH
    if score <= bundle.meta["severity_low_max_score"]:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def score_event(
    events_df,
    user_id: str,
    snapshot_time,
    artifacts_dir: str | Path,
    auth_events_df=None,
) -> dict:
    """End-to-end: compute this user's current features, load the right
    model (per-user or global fallback), score, classify severity.
    Returns a dict shaped closely to what an anomaly-scorer-fn response
    would eventually carry, without any AWS/Lambda dependency here.
    """
    feature_row = compute_anomaly_features(events_df, user_id, snapshot_time, auth_events_df)
    bundle = load_model_for_user(artifacts_dir, user_id)

    X = _feature_dict_to_vector(feature_row, bundle)
    raw_score = float(bundle.model.decision_function(X)[0])
    severity = classify_severity(raw_score, bundle)

    return {
        "user_id": user_id,
        "snapshot_time": str(snapshot_time),
        "anomaly_score": raw_score,
        "severity": severity,
        "scored_with_global_fallback": bundle.meta["is_global_fallback"],
        "failed_logins_feature_available": "failed_logins_last_1h" in bundle.meta["numeric_columns"],
    }
