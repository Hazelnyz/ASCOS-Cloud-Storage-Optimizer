"""
Phase 3 -- LightGBM evaluation, per Part 2 (ML_SCHEMA) §11 of the ASCOS
master project reference.

*** THIS MODULE NEVER TRAINS OR FITS A MODEL. ***

It loads an already-saved LightGBM booster (produced by
ml.modeling.train_lightgbm.train_model()) and its metadata JSON, uses
the metadata's own recorded (seed, horizon_days, cadence_days,
embargo_days, train_frac) to deterministically RECONSTRUCT the exact
same test split that was held out at training time -- via
ml.modeling.train_lightgbm.build_training_data(), the same reusable
function training used -- and scores that reconstructed test set with
the loaded model. No `lgb.LGBMClassifier(...).fit(...)` call, and no
`lgb.train(...)` call, appears anywhere in this file.

Metrics implemented from scratch with numpy/pandas (ROC-AUC via the
Mann-Whitney rank-sum identity, PR-AUC as the standard step-function
Average Precision, confusion matrix by direct counting, Brier score as
mean squared probability error) rather than importing scikit-learn's
metrics module -- this environment installed lightgbm/shap, not
scikit-learn, and reusing what's actually available avoids yet another
dependency negotiation for a handful of well-defined formulas.

*** SYNTHETIC / DEMO DATA ***
Every number this module reports describes model behavior on the
reproducible synthetic dataset (ml/data/synthetic_generator.py), NOT
real ASCOS user access data. This is stated in every printed report and
saved into the evaluation JSON artifact.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml.config import EMBARGO_DAYS, HORIZON_DAYS, RANDOM_SEED, SNAPSHOT_CADENCE_DAYS
from ml.modeling.train_lightgbm import MODEL_ARTIFACT_DIR, build_training_data

DEFAULT_THRESHOLD = 0.5


# --------------------------------------------------------------------
# Metrics (hand-rolled -- no scikit-learn dependency; see module docstring)
# --------------------------------------------------------------------

def _confusion_counts(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def _precision_recall_f1(cm: dict) -> tuple[float, float, float]:
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def _roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Mann-Whitney U / rank-sum identity for ROC-AUC:
    AUC = (sum of ranks of positive-class scores - n_pos*(n_pos+1)/2) / (n_pos * n_neg)
    Ties are handled via average ranking (pandas' default rank method),
    matching how sklearn's roc_auc_score handles ties."""
    n_pos = int(np.sum(y_true == 1))
    n_neg = int(np.sum(y_true == 0))
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = pd.Series(scores).rank(method="average").to_numpy()
    sum_ranks_pos = ranks[y_true == 1].sum()
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def _pr_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Average Precision: AP = sum_n (R_n - R_{n-1}) * P_n over
    thresholds taken at each distinct predicted score, sorted
    descending -- the standard step-function PR-AUC definition (same
    quantity sklearn.metrics.average_precision_score computes)."""
    order = np.argsort(-scores, kind="mergesort")
    y_sorted = y_true[order]
    n_pos = int(np.sum(y_true == 1))
    if n_pos == 0:
        return float("nan")
    tp_cumsum = np.cumsum(y_sorted == 1)
    fp_cumsum = np.cumsum(y_sorted == 0)
    precision = tp_cumsum / (tp_cumsum + fp_cumsum)
    recall = tp_cumsum / n_pos
    recall_prev = np.concatenate(([0.0], recall[:-1]))
    ap = float(np.sum((recall - recall_prev) * precision))
    return ap


def _brier_score(y_true: np.ndarray, probs: np.ndarray) -> float:
    return float(np.mean((probs - y_true) ** 2))


def _calibration_bins(y_true: np.ndarray, probs: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Lightweight reliability-diagram data: bucket predictions into
    n_bins equal-width probability bins, report mean predicted
    probability vs. empirical positive rate per bin. Per §4's
    calibration caveat: 'p_access = 0.65 is not automatically 65%
    likely ... unless the model is calibrated' -- this is the check
    that caveat calls for, expressed as numbers rather than a plotted
    reliability diagram."""
    bins = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        else:
            mask = (probs >= lo) & (probs < hi)
        n = int(np.sum(mask))
        if n == 0:
            bins.append(
                {"bin_range": [float(lo), float(hi)], "n": 0, "mean_predicted": None, "empirical_positive_rate": None}
            )
            continue
        bins.append(
            {
                "bin_range": [float(lo), float(hi)],
                "n": n,
                "mean_predicted": float(np.mean(probs[mask])),
                "empirical_positive_rate": float(np.mean(y_true[mask])),
            }
        )
    return bins


# --------------------------------------------------------------------
# Model artifact discovery / loading
# --------------------------------------------------------------------

def find_latest_model_artifact(model_dir: Path = MODEL_ARTIFACT_DIR) -> tuple[Path, Path]:
    """Finds the most recently trained model + its metadata JSON under
    ml/models/, by trained_at_utc recorded inside each metadata file
    (falls back to filename sort if that's ever missing)."""
    model_dir = Path(model_dir)
    meta_files = sorted(model_dir.glob("*.meta.json"))
    if not meta_files:
        raise FileNotFoundError(
            f"No *.meta.json files found under {model_dir} -- train a model first "
            "with ml.modeling.train_lightgbm before running evaluation."
        )

    def _trained_at(p: Path):
        try:
            with open(p) as fh:
                return json.load(fh).get("trained_at_utc", "")
        except Exception:
            return ""

    meta_files.sort(key=_trained_at)
    latest_meta_path = meta_files[-1]
    with open(latest_meta_path) as fh:
        meta = json.load(fh)
    model_path = model_dir / f"{meta['model_version']}.txt"
    if not model_path.exists():
        raise FileNotFoundError(
            f"metadata references model file {model_path} which does not exist"
        )
    return model_path, latest_meta_path


def load_model_and_metadata(model_path: Path, metadata_path: Path):
    import lightgbm as lgb  # lazy import, consistent with train_lightgbm.py

    with open(metadata_path) as fh:
        metadata = json.load(fh)
    booster = lgb.Booster(model_file=str(model_path))
    return booster, metadata


# --------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------

@dataclass
class EvaluationResult:
    model_version: str
    evaluated_at_utc: str
    threshold: float
    test_rows: int
    positive_prevalence: float
    reconstructed_train_rows: int
    reconstructed_test_rows: int
    metadata_train_rows: int
    metadata_test_rows: int
    reconstruction_matches_metadata: bool
    metrics: dict
    confusion_matrix: dict
    calibration_bins: list
    feature_importance_gain: list
    feature_importance_split: list
    evaluation_path: Path


def evaluate_model(
    model_path: Path | None = None,
    metadata_path: Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    verbose: bool = True,
) -> EvaluationResult:
    if model_path is None or metadata_path is None:
        model_path, metadata_path = find_latest_model_artifact()

    booster, metadata = load_model_and_metadata(model_path, metadata_path)

    seed = metadata["seed"]
    horizon_days = metadata.get("horizon_days", HORIZON_DAYS)
    embargo_days = metadata.get("embargo_days", EMBARGO_DAYS)

    if "cadence_days" not in metadata:
        warnings.warn(
            "metadata is missing 'cadence_days' (older training artifact, predates "
            "the metadata-completeness fix) -- falling back to the current config "
            "default. If SNAPSHOT_CADENCE_DAYS has changed since this model was "
            "trained, the reconstructed split will NOT match the original.",
            stacklevel=2,
        )
    if "train_frac" not in metadata:
        warnings.warn(
            "metadata is missing 'train_frac' (older training artifact) -- falling "
            "back to 0.75. If a different train_frac was actually used, the "
            "reconstructed split will NOT match the original.",
            stacklevel=2,
        )
    cadence_days = metadata.get("cadence_days", SNAPSHOT_CADENCE_DAYS)
    train_frac = metadata.get("train_frac", 0.75)

    if verbose:
        print(f"[evaluate_lightgbm] loaded model_version={metadata['model_version']}")
        print(
            f"[evaluate_lightgbm] reconstructing split with seed={seed} "
            f"horizon_days={horizon_days} cadence_days={cadence_days} "
            f"embargo_days={embargo_days} train_frac={train_frac}"
        )

    (
        train_features,
        train_labels,
        test_features,
        test_labels,
        split_result,
        events,
        meta_df,
    ) = build_training_data(
        seed=seed,
        horizon_days=horizon_days,
        cadence_days=cadence_days,
        embargo_days=embargo_days,
        train_frac=train_frac,
        verbose=verbose,
    )

    # Sanity check: the reconstructed split should exactly match what
    # was recorded at training time. If it doesn't, evaluation is
    # scoring against a DIFFERENT test set than the model saw held out,
    # which would make every metric below meaningless -- so this is a
    # loud check, not a soft one.
    reconstruction_matches_metadata = (
        len(train_features) == metadata["train_rows"]
        and len(test_features) == metadata["test_rows"]
    )
    if not reconstruction_matches_metadata:
        warnings.warn(
            f"RECONSTRUCTION MISMATCH: rebuilt train/test rows "
            f"({len(train_features)}/{len(test_features)}) do not match metadata "
            f"({metadata['train_rows']}/{metadata['test_rows']}). Evaluation metrics "
            "below are being computed on a split that does NOT match the one used "
            "at training time -- treat them with suspicion.",
            stacklevel=2,
        )

    feature_columns = metadata.get("feature_columns")
    missing_cols = [c for c in feature_columns if c not in test_features.columns]
    if missing_cols:
        raise RuntimeError(
            f"reconstructed test features are missing columns the model expects: {missing_cols}"
        )

    X_test = test_features[feature_columns]
    y_test = test_labels.to_numpy()

    # NEVER FIT. Only predict, on an already-trained booster.
    p_access = booster.predict(X_test)
    p_access = np.asarray(p_access, dtype=float)
    y_pred = (p_access >= threshold).astype(int)

    cm = _confusion_counts(y_test, y_pred)
    precision, recall, f1 = _precision_recall_f1(cm)
    roc_auc = _roc_auc(y_test, p_access)
    pr_auc = _pr_auc(y_test, p_access)
    brier = _brier_score(y_test, p_access)
    calibration = _calibration_bins(y_test, p_access)

    importance_gain = booster.feature_importance(importance_type="gain")
    importance_split = booster.feature_importance(importance_type="split")
    fnames = booster.feature_name()
    gain_ranked = sorted(
        [{"feature": f, "importance_gain": float(g)} for f, g in zip(fnames, importance_gain)],
        key=lambda d: -d["importance_gain"],
    )
    split_ranked = sorted(
        [{"feature": f, "importance_split": int(s)} for f, s in zip(fnames, importance_split)],
        key=lambda d: -d["importance_split"],
    )

    metrics = {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "brier_score": brier,
    }

    evaluated_at = datetime.now(timezone.utc).isoformat()
    evaluation_path = Path(model_path).parent / f"{metadata['model_version']}.eval.json"
    report = {
        "data_source": "synthetic_demo_data",
        "disclaimer": "SYNTHETIC / DEMO DATA -- these metrics describe model behavior "
        "on the reproducible synthetic dataset, NOT real ASCOS user access data.",
        "model_version": metadata["model_version"],
        "evaluated_at_utc": evaluated_at,
        "threshold": threshold,
        "test_rows": len(test_features),
        "positive_prevalence": float(np.mean(y_test)),
        "reconstruction_matches_metadata": reconstruction_matches_metadata,
        "reconstructed_train_rows": len(train_features),
        "reconstructed_test_rows": len(test_features),
        "metadata_train_rows": metadata["train_rows"],
        "metadata_test_rows": metadata["test_rows"],
        "metrics": metrics,
        "confusion_matrix": cm,
        "calibration_bins": calibration,
        "feature_importance_gain": gain_ranked,
        "feature_importance_split": split_ranked,
    }
    with open(evaluation_path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)

    if verbose:
        print(f"[evaluate_lightgbm] reconstruction_matches_metadata={reconstruction_matches_metadata}")
        print(f"[evaluate_lightgbm] evaluation saved to {evaluation_path}")

    return EvaluationResult(
        model_version=metadata["model_version"],
        evaluated_at_utc=evaluated_at,
        threshold=threshold,
        test_rows=len(test_features),
        positive_prevalence=float(np.mean(y_test)),
        reconstructed_train_rows=len(train_features),
        reconstructed_test_rows=len(test_features),
        metadata_train_rows=metadata["train_rows"],
        metadata_test_rows=metadata["test_rows"],
        reconstruction_matches_metadata=reconstruction_matches_metadata,
        metrics=metrics,
        confusion_matrix=cm,
        calibration_bins=calibration,
        feature_importance_gain=gain_ranked,
        feature_importance_split=split_ranked,
        evaluation_path=evaluation_path,
    )


def main():
    print("=" * 70)
    print("ASCOS Phase 3 -- LightGBM evaluation (SYNTHETIC / DEMO DATA)")
    print("=" * 70)
    result = evaluate_model(verbose=True)
    print()
    print(f"model_version:      {result.model_version}")
    print(f"threshold:          {result.threshold}")
    print(f"test_rows:          {result.test_rows}")
    print(f"positive_prevalence:{result.positive_prevalence:.4f}")
    print(f"reconstruction_matches_metadata: {result.reconstruction_matches_metadata}")
    print()
    print("Metrics:")
    for k, v in result.metrics.items():
        print(f"  {k:12s}: {v:.4f}")
    print()
    print("Confusion matrix:")
    print(f"  {result.confusion_matrix}")
    print()
    print("Top 10 features by gain importance:")
    for row in result.feature_importance_gain[:10]:
        print(f"  {row['feature']:28s} {row['importance_gain']:.2f}")
    print()
    print(f"Full evaluation JSON saved to: {result.evaluation_path}")
    print("=" * 70)
    print("Evaluation completion status: SUCCESS")
    print("=" * 70)
    return result


if __name__ == "__main__":
    main()
