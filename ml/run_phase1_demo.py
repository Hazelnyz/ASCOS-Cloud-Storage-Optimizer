"""
Phase 1 (dependency-independent half) end-to-end demo.

Runs: synthetic data -> sliding-window snapshots -> labels ->
chronological split with embargo -> feature matrix for train/test.

Does NOT touch LightGBM or SHAP -- those stages are blocked pending
package availability (see ml/README.md).

Run with: python3 -m ml.run_phase1_demo
"""
from __future__ import annotations

import warnings

import pandas as pd

from ml.config import EMBARGO_DAYS, HORIZON_DAYS, SNAPSHOT_CADENCE_DAYS
from ml.data.synthetic_generator import generate_synthetic_dataset
from ml.features.feature_engineering import FEATURE_COLUMNS, compute_feature_matrix
from ml.labels.label_generation import generate_labels, generate_snapshots
from ml.splitting.chronological_split import chronological_split


def main():
    warnings.filterwarnings("ignore", category=UserWarning)

    print("=" * 70)
    print("ASCOS Phase 1 demo -- dependency-independent components only")
    print("=" * 70)

    events, meta = generate_synthetic_dataset(verbose=True)

    print()
    print(f"Event type breakdown:\n{events['event_type'].value_counts()}")
    print()
    print(f"File archetype breakdown (debug column, not a model feature):"
          f"\n{meta['archetype'].value_counts()}")

    snapshots = generate_snapshots(
        events, meta, horizon_days=HORIZON_DAYS, cadence_days=SNAPSHOT_CADENCE_DAYS
    )
    print(f"\nGenerated {len(snapshots)} (user_id, file_id, snapshot_time) rows "
          f"(cadence={SNAPSHOT_CADENCE_DAYS}d, horizon={HORIZON_DAYS}d)")

    labeled = generate_labels(events, snapshots, horizon_days=HORIZON_DAYS)
    label_counts = labeled["label"].value_counts()
    print(f"\nLabel distribution:\n{label_counts}")
    print(f"Positive rate: {labeled['label'].mean():.3f}")

    # Chronological split with embargo.
    split_date = events["timestamp"].min() + pd.Timedelta(
        days=int((events["timestamp"].max() - events["timestamp"].min()).days * 0.75)
    )
    split_result = chronological_split(
        labeled, split_date=split_date, horizon_days=HORIZON_DAYS, embargo_days=EMBARGO_DAYS
    )
    print(f"\nChronological split at {split_date.date()} (embargo={EMBARGO_DAYS}d):")
    print(f"  train:           {len(split_result.train)} rows "
          f"(up to {split_result.train_cutoff.date()})")
    print(f"  dropped/embargo: {len(split_result.dropped_embargo)} rows")
    print(f"  test:            {len(split_result.test)} rows "
          f"(after {split_result.split_date.date()})")
    print(f"  train positive rate: {split_result.train['label'].mean():.3f}")
    print(f"  test positive rate:  {split_result.test['label'].mean():.3f}")

    # Feature computation -- full train + test sets.
    print("\nComputing leakage-safe feature matrix for train + test "
          f"({len(split_result.train) + len(split_result.test)} rows total)... "
          "this takes ~30s at default dataset size.")
    train_features = compute_feature_matrix(events, meta, split_result.train)
    test_features = compute_feature_matrix(events, meta, split_result.test)

    print(f"\nTrain feature matrix: {train_features.shape}")
    print(f"Test feature matrix:  {test_features.shape}")
    print(f"\nFeature columns fed to the model ({len(FEATURE_COLUMNS)}):")
    for c in FEATURE_COLUMNS:
        print(f"  - {c}")

    print(f"\nnever_accessed rate -- train: {train_features['never_accessed'].mean():.3f}, "
          f"test: {test_features['never_accessed'].mean():.3f}")
    print(f"protected_flag rate (hard-gate column, excluded from model features) -- "
          f"train: {train_features['protected_flag'].mean():.3f}")

    print("\n" + "=" * 70)
    print("Phase 1 dependency-independent pipeline ran successfully end-to-end.")
    print("LightGBM training / SHAP / policy engine remain BLOCKED pending")
    print("package availability -- not run, not claimed complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
