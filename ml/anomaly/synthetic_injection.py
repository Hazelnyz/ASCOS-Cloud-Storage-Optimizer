"""
Synthetic/injected anomaly evaluation set (§7, §11, §13).

§7: "Evaluation-only labeled set: since no real labeled anomaly data
exists, generate a small synthetic/injected anomaly set (simulated
delete burst, simulated failed-login burst -- only if Cognito auth
events are actually wired in per the note above) purely for measuring
detection rate and false-positive rate -- never used for training."

Two hard rules enforced by this module's design, not just its
docstring:

1. NEVER used for training. Nothing in this file is imported by
   train_isolation_forest.py, and every function here returns a
   labeled DataFrame explicitly tagged as an evaluation set via
   .attrs, mirroring how ml/data/synthetic_generator.py tags its own
   output.

2. The failed-login-burst injector refuses to run rather than
   fabricate fake Cognito auth data. §18 (ML_SCHEMA, restated in the
   Stage 7 handoff): "If Cognito event logging to this pipeline is
   deferred, login-pattern anomaly detection is deferred with it --
   don't claim login-pattern detection is covered unless this source
   is actually connected." As of this ASCOS deployment, it is not
   connected (confirmed against the real access-event-writer-fn/
   anomaly-scorer-fn handler source, which only ever sees S3 data
   events). inject_failed_login_burst() raises NotImplementedError
   with that exact reasoning rather than silently returning an empty
   or fabricated result -- a caller who doesn't handle that exception
   would find out immediately, not discover a silently-skipped
   evaluation later.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.anomaly.feature_engineering import ANOMALY_FEATURE_COLUMNS, compute_anomaly_features
from ml.config import RANDOM_SEED, SYNTHETIC_DATA_DISCLAIMER

EVAL_SET_DISCLAIMER = (
    SYNTHETIC_DATA_DISCLAIMER
    + " This specific set additionally contains INJECTED anomalies for "
    "evaluation only -- never pass this to train_isolation_forest.py."
)


def _normal_snapshot_rows(
    events_df: pd.DataFrame, user_id: str, snapshot_times: list[pd.Timestamp]
) -> list[dict]:
    return [
        {**compute_anomaly_features(events_df, user_id, t), "is_injected_anomaly": False}
        for t in snapshot_times
    ]


def inject_delete_burst(
    events_df: pd.DataFrame,
    user_id: str,
    snapshot_times: list[pd.Timestamp],
    burst_fraction: float = 0.1,
    burst_size: int = 20,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Normal feature rows for (user_id, each snapshot_time), plus a
    `burst_fraction` share of them mutated to simulate a delete burst:
    deletes_last_1h and events_last_1h artificially spiked, as if the
    user (or an attacker acting as them) deleted `burst_size` files in
    the last hour. This does NOT touch the real events_df -- the burst
    is applied to the already-computed feature row, not injected as
    fake rows into the raw event log, so it can never leak into
    anything else that reads events_df.
    """
    rng = np.random.default_rng(seed)
    rows = _normal_snapshot_rows(events_df, user_id, snapshot_times)

    n_burst = max(1, int(len(rows) * burst_fraction)) if rows else 0
    burst_indices = set(rng.choice(len(rows), size=min(n_burst, len(rows)), replace=False)) if rows else set()

    for i, row in enumerate(rows):
        if i in burst_indices:
            row["deletes_last_1h"] = burst_size
            row["events_last_1h"] = max(row["events_last_1h"], burst_size)
            row["unique_files_last_1h"] = max(row["unique_files_last_1h"], burst_size)
            row["is_injected_anomaly"] = True

    df = pd.DataFrame(rows)
    df.attrs["disclaimer"] = EVAL_SET_DISCLAIMER
    df.attrs["injection_type"] = "delete_burst"
    return df


def inject_failed_login_burst(*args, **kwargs):
    """Deliberately unimplemented -- see module docstring. Do not
    remove this stub or make it silently return an empty/fake result;
    its purpose is to fail loudly and explain why, so the gap stays
    visible in code, not just in a comment someone might not read.
    """
    raise NotImplementedError(
        "inject_failed_login_burst() is intentionally not implemented: Cognito "
        "authentication events are not wired into this ASCOS deployment's "
        "anomaly pipeline (confirmed against the real handler source -- "
        "access_event never carries login attempts). Per ML_SCHEMA §7/§18, "
        "login-pattern anomaly detection must not be claimed as covered until "
        "that source is actually connected. Wire Cognito auth-event logging "
        "into access_event (or a dedicated table) first, then implement this."
    )


def evaluate_detection(
    model_bundle,
    eval_df: pd.DataFrame,
    score_fn,
) -> dict:
    """§11: 'false-positive rate per severity tier, detection rate on
    the injected/synthetic set, severity classification accuracy.'

    score_fn: callable(feature_row: dict, bundle) -> (raw_score, severity)
        Passed in rather than imported directly from ml.anomaly.score
        so this function stays testable independent of a trained model
        (a fake score_fn can be substituted in tests).
    """
    if "is_injected_anomaly" not in eval_df.columns:
        raise ValueError("eval_df must come from inject_delete_burst() (or an equivalent injector).")

    results = []
    for _, row in eval_df.iterrows():
        raw_score, severity = score_fn(row.to_dict(), model_bundle)
        results.append({"is_injected_anomaly": row["is_injected_anomaly"], "severity": severity, "score": raw_score})

    results_df = pd.DataFrame(results)

    anomalous = results_df[results_df["is_injected_anomaly"]]
    normal = results_df[~results_df["is_injected_anomaly"]]

    detected = anomalous[anomalous["severity"].isin(["Medium", "High"])]
    detection_rate = len(detected) / len(anomalous) if len(anomalous) else None

    false_positives = normal[normal["severity"].isin(["Medium", "High"])]
    false_positive_rate = len(false_positives) / len(normal) if len(normal) else None

    severity_counts = results_df.groupby(["is_injected_anomaly", "severity"]).size().to_dict()

    return {
        "n_injected_anomalies": int(len(anomalous)),
        "n_normal": int(len(normal)),
        "detection_rate": detection_rate,
        "false_positive_rate": false_positive_rate,
        "severity_breakdown": {str(k): int(v) for k, v in severity_counts.items()},
    }
