"""
Phase 2 -- LightGBM training pipeline, per Part 2 (ML_SCHEMA) §3/§4 of
the ASCOS master project reference.

*** REUSES, WITHOUT MODIFICATION ***
  - ml.data.synthetic_generator.generate_synthetic_dataset        (§1)
  - ml.labels.label_generation.generate_snapshots / generate_labels (§3)
  - ml.splitting.chronological_split.chronological_split          (§3)
  - ml.features.feature_engineering.compute_feature_matrix /
    FEATURE_COLUMNS / CATEGORICAL_COLUMNS                          (§2)

None of that logic is duplicated here. This module adds only what those
don't already provide: assembling the LightGBM training matrix, the
scale_pos_weight class-imbalance calculation, model fit, and a
versioned local artifact save.

`lightgbm` is imported LAZILY (inside train_model(), not at module
top-level) so that `build_training_data()` -- which is pure
reuse-and-glue of the already-tested Phase 1 modules -- can be
imported and run even in an environment that does not have lightgbm
installed. This is what let the Phase-1-reuse half of this file be
verified directly in the Phase-1 sandbox before you run the full
training step in F:\\ml\\.venv.

Requirements enforced here (see docstrings below for where):
  - reproducible seed
  - scale_pos_weight for class imbalance, NOT SMOTE
  - no random shuffling (chronological_split does this; unchanged)
  - no future information in features (feature_engineering.py does
    this; unchanged)
  - file_id / user_id / protected_flag never fed to the model
    (FEATURE_COLUMNS from feature_engineering.py already excludes
    them; asserted again here as a belt-and-suspenders check)
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ml.config import (
    EMBARGO_DAYS,
    FEATURE_SCHEMA_VERSION,
    HORIZON_DAYS,
    RANDOM_SEED,
    SNAPSHOT_CADENCE_DAYS,
)
from ml.data.synthetic_generator import generate_synthetic_dataset
from ml.features.feature_engineering import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    compute_feature_matrix,
)
from ml.labels.label_generation import generate_labels, generate_snapshots
from ml.splitting.chronological_split import chronological_split

MODEL_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "models"  # ml/models/
MODEL_NAME_PREFIX = "ascos-lgbm-demo"

# Belt-and-suspenders: these must never appear in the training matrix,
# regardless of what FEATURE_COLUMNS happens to contain.
FORBIDDEN_MODEL_INPUTS = {"file_id", "user_id", "protected_flag", "filename"}


@dataclass
class TrainingResult:
    model: Any  # lightgbm.LGBMClassifier -- typed loosely so this
    # dataclass (and therefore build_training_data()'s callers) never
    # require `import lightgbm` merely to read the type annotation.
    model_version: str
    model_path: Path
    metadata_path: Path
    train_rows: int
    test_rows: int
    dropped_embargo_rows: int
    train_positive: int
    train_negative: int
    test_positive: int
    test_negative: int
    scale_pos_weight: float
    feature_columns: list
    categorical_columns: list
    split_date: pd.Timestamp
    train_cutoff: pd.Timestamp
    lgbm_params: dict
    train_features: pd.DataFrame
    train_labels: pd.Series
    test_features: pd.DataFrame
    test_labels: pd.Series


def _align_categorical_columns(
    train_df: pd.DataFrame, test_df: pd.DataFrame, categorical_columns: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Why this exists: LightGBM's pandas-categorical support keys off
    category CODES, which must match between fit and predict.
    `compute_feature_matrix()` (feature_engineering.py) converts each
    categorical column to `category` dtype independently, based only
    on the values present in whatever DataFrame it was given -- so
    calling it once for train and once for test (as this module does)
    can produce two DataFrames whose same-named categorical column has
    different category sets/orderings.

    This function re-expresses both DataFrames' categorical columns
    against one shared `CategoricalDtype` (the union of values seen in
    either split), so LightGBM sees consistent codes at fit and predict
    time. This is a training-pipeline concern, not a feature-definition
    concern, which is why it lives here rather than being folded into
    feature_engineering.py.

    `last_access_day_of_week` already carries a fixed, spec-ordered
    category list (Monday..Sunday) straight from feature_engineering.py
    -- that ordering is preserved rather than replaced with an
    arbitrary union order.
    """
    train_df = train_df.copy()
    test_df = test_df.copy()
    for col in categorical_columns:
        if col not in train_df.columns:
            continue
        combined = pd.Index(pd.concat([train_df[col], test_df[col]]).dropna().unique())
        existing_dtype = train_df[col].dtype
        if hasattr(existing_dtype, "categories") and len(existing_dtype.categories) > 0:
            existing_order = list(existing_dtype.categories)
            combined_set = set(combined)
            ordered = [c for c in existing_order if c in combined_set]
            extra = [c for c in combined if c not in existing_order]
            categories = ordered + extra
        else:
            categories = list(combined)
        dtype = pd.CategoricalDtype(categories=categories)
        train_df[col] = train_df[col].astype(dtype)
        test_df[col] = test_df[col].astype(dtype)
    return train_df, test_df


def build_training_data(
    seed: int = RANDOM_SEED,
    horizon_days: int = HORIZON_DAYS,
    cadence_days: int = SNAPSHOT_CADENCE_DAYS,
    embargo_days: int = EMBARGO_DAYS,
    train_frac: float = 0.75,
    verbose: bool = True,
):
    """
    Runs the full, already-tested Phase 1 chain end to end:
    synthetic data -> sliding-window snapshots -> 7-day-horizon labels
    -> chronological split with embargo -> leakage-safe feature
    matrices for train and test -- then aligns categorical dtypes for
    LightGBM (see `_align_categorical_columns`).

    Has NO dependency on lightgbm/shap -- everything it calls is pure
    Phase 1 (pandas/numpy) code. This is deliberate so this function
    can be exercised on its own wherever lightgbm isn't installed.

    Returns
    -------
    (train_features, train_labels, test_features, test_labels,
     split_result, events, meta)
    """
    events, meta = generate_synthetic_dataset(seed=seed, verbose=verbose)

    snapshots = generate_snapshots(
        events, meta, horizon_days=horizon_days, cadence_days=cadence_days
    )
    labeled = generate_labels(events, snapshots, horizon_days=horizon_days)

    split_date = events["timestamp"].min() + pd.Timedelta(
        days=int((events["timestamp"].max() - events["timestamp"].min()).days * train_frac)
    )
    split_result = chronological_split(
        labeled, split_date=split_date, horizon_days=horizon_days, embargo_days=embargo_days
    )

    if verbose:
        print(
            f"[train_lightgbm] split_date={split_date.date()} "
            f"embargo_days={embargo_days} horizon_days={horizon_days}"
        )
        print(
            f"[train_lightgbm] train={len(split_result.train)} "
            f"dropped_embargo={len(split_result.dropped_embargo)} "
            f"test={len(split_result.test)}"
        )

    if len(split_result.train) == 0 or len(split_result.test) == 0:
        raise ValueError(
            "chronological split produced an empty train or test set -- "
            "adjust train_frac / sim_days / horizon before training."
        )

    train_features = compute_feature_matrix(events, meta, split_result.train)
    test_features = compute_feature_matrix(events, meta, split_result.test)

    train_features, test_features = _align_categorical_columns(
        train_features, test_features, CATEGORICAL_COLUMNS
    )

    train_labels = split_result.train["label"].reset_index(drop=True)
    test_labels = split_result.test["label"].reset_index(drop=True)

    assert len(train_features) == len(train_labels), "train feature/label row mismatch"
    assert len(test_features) == len(test_labels), "test feature/label row mismatch"

    return train_features, train_labels, test_features, test_labels, split_result, events, meta


def train_model(
    seed: int = RANDOM_SEED,
    n_estimators: int = 300,
    learning_rate: float = 0.05,
    num_leaves: int = 31,
    cadence_days: int = SNAPSHOT_CADENCE_DAYS,
    train_frac: float = 0.75,
    verbose: bool = True,
) -> TrainingResult:
    """
    Trains a LightGBM binary classifier on the Phase 1 data chain and
    saves a versioned local artifact under ml/models/.

    Requires `lightgbm` to be installed -- imported lazily here, not at
    module top-level (see module docstring).

    `cadence_days`/`train_frac` are exposed (rather than left as
    build_training_data()'s implicit defaults) so the ACTUAL values used
    for this run are recorded in the saved metadata JSON. This is what
    lets ml/evaluation/evaluate_lightgbm.py reconstruct the identical
    test split from metadata alone, without retraining or guessing that
    today's config defaults match whatever was used when the model was
    trained.
    """
    import lightgbm as lgb  # lazy import -- see module docstring

    (
        train_features,
        train_labels,
        test_features,
        test_labels,
        split_result,
        events,
        meta,
    ) = build_training_data(
        seed=seed, cadence_days=cadence_days, train_frac=train_frac, verbose=verbose
    )

    # Belt-and-suspenders check: FEATURE_COLUMNS (feature_engineering.py)
    # already excludes these, but assert it explicitly here since this
    # is the actual model-input boundary.
    leaked = FORBIDDEN_MODEL_INPUTS.intersection(FEATURE_COLUMNS)
    if leaked:
        raise RuntimeError(
            f"FEATURE_COLUMNS contains forbidden model inputs: {leaked}. "
            "Refusing to train."
        )

    X_train = train_features[FEATURE_COLUMNS]
    X_test = test_features[FEATURE_COLUMNS]

    # Inference-time requirement (not a training-behavior change): the
    # native LightGBM model file (booster_.save_model()) stores category
    # CODES only, never the string<->code mapping itself. Any process
    # that loads this model later to predict on new rows (ml/inference/
    # predictor.py) must re-apply the EXACT SAME CategoricalDtype per
    # column that was used here, via _align_categorical_columns, or the
    # codes -- and therefore the predictions -- will be wrong. Persisting
    # these lists is the single addition that makes that possible.
    categorical_category_maps = {
        col: list(X_train[col].dtype.categories)
        for col in CATEGORICAL_COLUMNS
        if col in X_train.columns and hasattr(X_train[col].dtype, "categories")
    }

    n_pos = int(train_labels.sum())
    n_neg = int(len(train_labels) - n_pos)
    if n_pos == 0:
        raise ValueError("training set has zero positive labels -- cannot compute scale_pos_weight")
    # Spec §3: "default approach is time-based split -> class weighting
    # (LightGBM's scale_pos_weight), not SMOTE by default."
    scale_pos_weight = n_neg / n_pos

    lgbm_params = dict(
        objective="binary",
        random_state=seed,
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        scale_pos_weight=scale_pos_weight,
        verbosity=-1,
    )

    model = lgb.LGBMClassifier(**lgbm_params)
    categorical_in_features = [c for c in CATEGORICAL_COLUMNS if c in FEATURE_COLUMNS]
    model.fit(
        X_train,
        train_labels,
        categorical_feature=categorical_in_features,
    )

    model_version = (
        f"{MODEL_NAME_PREFIX}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-seed{seed}"
    )
    MODEL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_ARTIFACT_DIR / f"{model_version}.txt"
    model.booster_.save_model(str(model_path))

    metadata = {
        "model_version": model_version,
        "seed": seed,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "lightgbm_version": lgb.__version__,
        "feature_columns": FEATURE_COLUMNS,
        "categorical_columns": categorical_in_features,
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "dropped_embargo_rows": len(split_result.dropped_embargo),
        "train_positive": n_pos,
        "train_negative": n_neg,
        "test_positive": int(test_labels.sum()),
        "test_negative": int(len(test_labels) - int(test_labels.sum())),
        "scale_pos_weight": scale_pos_weight,
        "lgbm_params": lgbm_params,
        "split_date": str(split_result.split_date.date()),
        "train_cutoff": str(split_result.train_cutoff.date()),
        "horizon_days": HORIZON_DAYS,
        "embargo_days": split_result.embargo_days,
        "cadence_days": cadence_days,
        "train_frac": train_frac,
        "data_source": "synthetic_demo_data",
        "categorical_category_maps": categorical_category_maps,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }
    metadata_path = MODEL_ARTIFACT_DIR / f"{model_version}.meta.json"
    with open(metadata_path, "w") as fh:
        json.dump(metadata, fh, indent=2, default=str)

    if verbose:
        print(f"[train_lightgbm] model saved to     {model_path}")
        print(f"[train_lightgbm] metadata saved to  {metadata_path}")
        print(
            f"[train_lightgbm] scale_pos_weight={scale_pos_weight:.4f} "
            f"(n_pos={n_pos}, n_neg={n_neg})"
        )

    return TrainingResult(
        model=model,
        model_version=model_version,
        model_path=model_path,
        metadata_path=metadata_path,
        train_rows=len(X_train),
        test_rows=len(X_test),
        dropped_embargo_rows=len(split_result.dropped_embargo),
        train_positive=n_pos,
        train_negative=n_neg,
        test_positive=int(test_labels.sum()),
        test_negative=int(len(test_labels) - int(test_labels.sum())),
        scale_pos_weight=scale_pos_weight,
        feature_columns=FEATURE_COLUMNS,
        categorical_columns=categorical_in_features,
        split_date=split_result.split_date,
        train_cutoff=split_result.train_cutoff,
        lgbm_params=lgbm_params,
        train_features=train_features,
        train_labels=train_labels,
        test_features=test_features,
        test_labels=test_labels,
    )


def main():
    print("=" * 70)
    print("ASCOS Phase 2 -- LightGBM training (SYNTHETIC / DEMO DATA)")
    print("=" * 70)
    result = train_model(verbose=True)
    print()
    print("Training complete.")
    print(f"  model_version:      {result.model_version}")
    print(f"  model_path:         {result.model_path}")
    print(f"  metadata_path:      {result.metadata_path}")
    print(
        f"  train_rows:         {result.train_rows} "
        f"(pos={result.train_positive}, neg={result.train_negative})"
    )
    print(
        f"  test_rows:          {result.test_rows} "
        f"(pos={result.test_positive}, neg={result.test_negative})"
    )
    print(f"  dropped_embargo:    {result.dropped_embargo_rows}")
    print(f"  scale_pos_weight:   {result.scale_pos_weight:.4f}")
    print(f"  lgbm_params:        {result.lgbm_params}")
    print(f"  feature_columns ({len(result.feature_columns)}): {result.feature_columns}")
    print(f"  categorical_columns: {result.categorical_columns}")
    print("=" * 70)
    print("Training completion status: SUCCESS")
    print("=" * 70)
    return result


if __name__ == "__main__":
    main()
