"""
Isolation Forest training (§7).

"Training: per-user (or small cluster if too sparse) on that user's
own historical rolling-window features -- unsupervised, no
'malicious/not' label exists. Retrained on the same schedule as the
DynamoDB behavioral baseline."

DEPENDENCY SPLIT, same pattern as ml/modeling/train_lightgbm.py:
building the training feature matrix (this module's
build_training_snapshots / build_feature_matrix) needs only
pandas/numpy and ml.anomaly.feature_engineering, and is fully testable
without scikit-learn installed. Only fit_isolation_forest() and
train_and_save() import sklearn, and only at call time (lazy import),
so a sandbox without sklearn can still verify everything up to the
actual .fit() call, exactly as was done for LightGBM training earlier
in this project.

SNAPSHOT CADENCE -- an implementation choice, not a spec value:
§3's "generate one training row every ~3 days" is specific to
access-prediction training and does not apply here (anomaly detection
uses short reactive windows, not multi-day ones -- see
ml/anomaly/feature_engineering.py's docstring). The spec does not give
an equivalent cadence for anomaly-detection training. This module
generates one snapshot AT EACH event's own timestamp for that user --
the natural granularity for a system meant to react per-event, not on
a multi-day cycle. Documented here explicitly so it isn't mistaken for
a spec-given number.

PER-USER VS FALLBACK: per ANOMALY_MIN_SAMPLES_PER_USER in ml/config.py
and its own docstring there, a user with fewer historical snapshots
than that threshold does not get a dedicated model -- their events are
scored against one shared GLOBAL model trained on every user's pooled
snapshots instead. This is the simplest defensible reading of the
spec's "(or small cluster if too sparse)" given the spec does not
define what constitutes a cluster or how to form one; a real
clustering step (e.g. by role, by directory_category patterns) is a
reasonable future refinement, not implemented here.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from ml.anomaly.feature_engineering import (
    ANOMALY_NUMERIC_FEATURE_COLUMNS,
    compute_anomaly_features_batch,
)
from ml.config import (
    ANOMALY_CONTAMINATION,
    ANOMALY_MIN_SAMPLES_PER_USER,
    ANOMALY_SEVERITY_LOW_MAX_PERCENTILE,
    ANOMALY_SEVERITY_MEDIUM_MAX_PERCENTILE,
    RANDOM_SEED,
    SYNTHETIC_DATA_DISCLAIMER,
)

GLOBAL_MODEL_KEY = "__global_fallback__"


def build_training_snapshots(events_df: pd.DataFrame) -> list[tuple[str, pd.Timestamp]]:
    """One (user_id, timestamp) pair per real event in events_df --
    see module docstring for why this cadence, not a fixed interval.
    """
    if events_df.empty:
        return []
    pairs = list(zip(events_df["user_id"], pd.to_datetime(events_df["timestamp"])))
    # De-duplicate exact (user_id, timestamp) collisions -- two events
    # for the same user at the identical timestamp would otherwise
    # produce two identical feature rows, silently double-weighting
    # that moment in training.
    return sorted(set(pairs), key=lambda p: p[1])


def build_feature_matrix(
    events_df: pd.DataFrame, auth_events_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Full feature matrix (all users, all snapshots), plus the raw
    identifying columns (user_id, snapshot_time) needed to split it
    per-user afterward. Does not train anything.
    """
    snapshots = build_training_snapshots(events_df)
    return compute_anomaly_features_batch(events_df, snapshots, auth_events_df)


def _numeric_columns_for_training(feature_df: pd.DataFrame) -> list[str]:
    """failed_logins_last_1h is entirely None/NaN whenever
    auth_events_df wasn't supplied (the honest default -- see
    ml/anomaly/feature_engineering.py). Feeding an all-NaN column into
    IsolationForest is meaningless and, depending on sklearn version,
    can raise outright. Drop it from the trained feature set when it's
    fully unmeasured, and record that decision in the saved metadata
    (train_and_save) so scoring uses the exact same column set later --
    never a silent mismatch between what was trained on and what's
    scored.
    """
    cols = list(ANOMALY_NUMERIC_FEATURE_COLUMNS)
    if "failed_logins_last_1h" in feature_df.columns and feature_df["failed_logins_last_1h"].isna().all():
        cols = [c for c in cols if c != "failed_logins_last_1h"]
    return cols


def _one_hot_day_of_week(feature_df: pd.DataFrame) -> pd.DataFrame:
    return pd.get_dummies(feature_df["day_of_week"], prefix="dow")


def fit_isolation_forest(X: np.ndarray):
    """Lazy sklearn import -- see module docstring's dependency-split
    note. Callable on its own (e.g. from a notebook) without pulling in
    the rest of this module's file-I/O.
    """
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(
        contamination=ANOMALY_CONTAMINATION,
        random_state=RANDOM_SEED,
    )
    model.fit(X)
    return model


def _design_matrix(feature_df: pd.DataFrame, numeric_cols: list[str]) -> np.ndarray:
    numeric = feature_df[numeric_cols].fillna(0.0).to_numpy(dtype=float)
    dow = _one_hot_day_of_week(feature_df).to_numpy(dtype=float)
    return np.concatenate([numeric, dow], axis=1)


def train_and_save(
    events_df: pd.DataFrame,
    output_dir: str | Path,
    auth_events_df: pd.DataFrame | None = None,
    min_samples_per_user: int = ANOMALY_MIN_SAMPLES_PER_USER,
) -> dict:
    """Train one model per user with enough history, plus one shared
    global-fallback model for sparse users, and save every artifact
    needed for later scoring: the model itself, the exact numeric
    column set used, the one-hot day-of-week column order, and the
    severity percentile thresholds computed from THAT model's own
    training-score distribution (see ml/anomaly/score.py).

    Returns a summary dict (does not itself raise on a synthetic-data
    warning -- callers training on synthetic data should check
    events_df.attrs for SYNTHETIC_DATA_DISCLAIMER themselves, same
    pattern as ml/modeling/train_lightgbm.py).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_df = build_feature_matrix(events_df, auth_events_df)
    if feature_df.empty:
        raise ValueError("No events to train on -- events_df produced zero snapshots.")

    numeric_cols = _numeric_columns_for_training(feature_df)
    dow_columns = sorted(feature_df["day_of_week"].unique())

    per_user_counts = feature_df["user_id"].value_counts()
    sparse_users = per_user_counts[per_user_counts < min_samples_per_user].index.tolist()
    dense_users = per_user_counts[per_user_counts >= min_samples_per_user].index.tolist()

    trained = {}

    for user_id in dense_users:
        user_df = feature_df[feature_df["user_id"] == user_id]
        X = _design_matrix(user_df, numeric_cols)
        model = fit_isolation_forest(X)
        trained[user_id] = _save_model_artifact(
            output_dir, user_id, model, X, numeric_cols, dow_columns, is_global=False
        )

    if sparse_users:
        pooled_df = feature_df[feature_df["user_id"].isin(sparse_users)]
        X = _design_matrix(pooled_df, numeric_cols)
        global_model = fit_isolation_forest(X)
        trained[GLOBAL_MODEL_KEY] = _save_model_artifact(
            output_dir, GLOBAL_MODEL_KEY, global_model, X, numeric_cols, dow_columns, is_global=True
        )

    return {
        "dense_users_with_own_model": dense_users,
        "sparse_users_on_global_fallback": sparse_users,
        "numeric_columns_used": numeric_cols,
        "failed_logins_feature_included": "failed_logins_last_1h" in numeric_cols,
        "output_dir": str(output_dir),
    }


def _save_model_artifact(
    output_dir: Path,
    key: str,
    model,
    X_train: np.ndarray,
    numeric_cols: list[str],
    dow_columns: list[str],
    is_global: bool,
) -> str:
    scores = model.decision_function(X_train)  # sklearn: lower = more anomalous
    low_cutoff = float(np.percentile(scores, 100 - ANOMALY_SEVERITY_LOW_MAX_PERCENTILE))
    medium_cutoff = float(np.percentile(scores, 100 - ANOMALY_SEVERITY_MEDIUM_MAX_PERCENTILE))

    safe_key = key.strip("_") if key == GLOBAL_MODEL_KEY else key
    model_path = output_dir / f"anomaly_{safe_key}.pkl"
    meta_path = output_dir / f"anomaly_{safe_key}.meta.json"

    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    meta = {
        "key": key,
        "is_global_fallback": is_global,
        "numeric_columns": numeric_cols,
        "dow_columns": dow_columns,
        "n_training_samples": int(X_train.shape[0]),
        "severity_low_max_score": low_cutoff,
        "severity_medium_max_score": medium_cutoff,
        "severity_thresholds_are_open_decision": True,  # see ml/config.py note, Master Reference §40
        "random_seed": RANDOM_SEED,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return str(model_path)
