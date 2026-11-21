"""
Anomaly-detection feature engineering (§7).

DISTINCT from ml/features/feature_engineering.py in two ways the spec
is explicit about, and which this module must not blur:

1. Uses ALL event types (read/write/delete/share/download), never just
   ACCESS_EVENTS. §7: "ALL event types, not just ACCESS_EVENTS."
2. Short rolling windows (5min/1h/24h), not the 7/30/90-day windows
   used for access prediction. §7: "anomaly detection needs to react
   fast, unlike the 7-day access-prediction horizon."

Because of (1) and (2), this module does NOT reuse
ml/features/feature_engineering.py's _events_up_to() boundary or its
window logic -- that function is scoped to ACCESS_EVENTS and to
multi-day windows, and importing it here would either be wrong (wrong
event-type filter) or require passing flags through it that don't
belong in the access-prediction module's contract. Each module stays
self-contained, matching the existing project pattern of independent,
single-purpose components (e.g. access-event-writer-fn and
anomaly-scorer-fn deliberately keep their own separate copies of the
same small ALLOWED_EVENT_NAMES constant rather than sharing one).

Same leakage discipline still applies even though this isn't a
training-label problem: every feature for a snapshot at time T uses
only events at or before T. There is no forward-looking label for
anomaly detection (it's unsupervised), but a live-scoring boundary
computed from *future* events would be nonsensical for a real-time
system regardless -- the boundary matters for a different reason here
(correctness of "as of now", not leakage into a label).

WHAT THIS MODULE DOES NOT DO: score anything. This produces feature
rows only; ml/anomaly/train_isolation_forest.py and ml/anomaly/score.py
own model fitting and severity classification, per the project's
policy/execution separation principle applied here too.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import (
    ALL_EVENT_TYPES,
    ANOMALY_WINDOW_1H_HOURS,
    ANOMALY_WINDOW_5MIN_MINUTES,
    ANOMALY_WINDOW_24H_HOURS,
)

# Columns this module produces, in a fixed order -- the single source
# of truth for what "the anomaly feature vector" means, mirrored by
# ml/anomaly/train_isolation_forest.py and ml/anomaly/score.py so
# training and live scoring can never silently drift out of column
# alignment with each other.
ANOMALY_FEATURE_COLUMNS = [
    "events_last_5min",
    "events_last_1h",
    "events_last_24h",
    "deletes_last_1h",
    "downloads_last_1h",
    "unique_files_last_1h",
    "unique_ips_last_24h",
    "failed_logins_last_1h",
    "hour_of_day_sin",
    "hour_of_day_cos",
    "day_of_week",
]

# Columns that are genuinely numeric inputs to IsolationForest.
# day_of_week is categorical (see note in compute_anomaly_features)
# and is one-hot encoded separately by the caller, not fed as a raw
# number here -- an ordinal 0..6 would wrongly imply Sunday is "far"
# from Monday, same reasoning ml/features/feature_engineering.py
# already applies to last_access_day_of_week.
ANOMALY_NUMERIC_FEATURE_COLUMNS = [c for c in ANOMALY_FEATURE_COLUMNS if c != "day_of_week"]

_DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _events_at_or_before(events_df: pd.DataFrame, snapshot_time: pd.Timestamp) -> pd.DataFrame:
    """The boundary every feature in this module routes through."""
    return events_df[events_df["timestamp"] <= snapshot_time]


def compute_anomaly_features(
    events_df: pd.DataFrame,
    user_id: str,
    snapshot_time: pd.Timestamp,
    auth_events_df: pd.DataFrame | None = None,
) -> dict:
    """Compute one anomaly-feature row for (user_id, snapshot_time).

    events_df: the access_event table's rows (all event types --
        this function does NOT filter to ACCESS_EVENTS, unlike the
        access-prediction module). Expected columns: user_id,
        event_type, timestamp, source_ip, device_context, file_id.

    auth_events_df: Cognito authentication events (sign-in
        success/failure, MFA challenge/result), if that source has
        actually been wired into this pipeline. Per §7 and the Stage 7
        handoff: this source is NOT currently connected anywhere in
        the deployed system (access_event only carries S3-derived and
        app-logged file events, never login attempts). Passing None
        (the default) is therefore the honest default, not a
        placeholder -- callers must not synthesize a fake auth_events_df
        just to make this parameter non-None. When None,
        failed_logins_last_1h is returned as None (NaN-equivalent),
        never 0 -- 0 would falsely claim "checked, found none" when the
        real answer is "not measurable yet". See
        ml/anomaly/train_isolation_forest.py for how training handles
        this column when it's entirely unmeasured across the dataset.
    """
    if events_df.empty:
        user_events = events_df
    else:
        past = _events_at_or_before(events_df, snapshot_time)
        user_events = past[past["user_id"] == user_id]

    window_5min_start = snapshot_time - pd.Timedelta(minutes=ANOMALY_WINDOW_5MIN_MINUTES)
    window_1h_start = snapshot_time - pd.Timedelta(hours=ANOMALY_WINDOW_1H_HOURS)
    window_24h_start = snapshot_time - pd.Timedelta(hours=ANOMALY_WINDOW_24H_HOURS)

    in_5min = user_events[user_events["timestamp"] > window_5min_start]
    in_1h = user_events[user_events["timestamp"] > window_1h_start]
    in_24h = user_events[user_events["timestamp"] > window_24h_start]

    events_last_5min = len(in_5min)
    events_last_1h = len(in_1h)
    events_last_24h = len(in_24h)

    deletes_last_1h = int((in_1h["event_type"] == "delete").sum())
    downloads_last_1h = int((in_1h["event_type"] == "download").sum())
    unique_files_last_1h = int(in_1h["file_id"].nunique()) if "file_id" in in_1h.columns else 0
    unique_ips_last_24h = (
        int(in_24h["source_ip"].dropna().nunique()) if "source_ip" in in_24h.columns else 0
    )

    if auth_events_df is None:
        failed_logins_last_1h = None
    else:
        user_auth = auth_events_df[auth_events_df["user_id"] == user_id]
        user_auth = user_auth[user_auth["timestamp"] <= snapshot_time]
        user_auth_1h = user_auth[user_auth["timestamp"] > window_1h_start]
        failed_logins_last_1h = int((user_auth_1h["result"] == "failure").sum())

    hour = snapshot_time.hour
    hour_of_day_sin = float(np.sin(2 * np.pi * hour / 24.0))
    hour_of_day_cos = float(np.cos(2 * np.pi * hour / 24.0))
    # Categorical, per the same reasoning as last_access_day_of_week in
    # ml/features/feature_engineering.py: Monday..Sunday are adjacent
    # in the week cycle, an ordinal encoding would misrepresent that.
    day_of_week = _DAYS_OF_WEEK[snapshot_time.dayofweek]

    device_context = None
    if not in_1h.empty and "device_context" in in_1h.columns:
        recent = in_1h.sort_values("timestamp").iloc[-1]
        device_context = recent.get("device_context")

    return {
        "user_id": user_id,
        "snapshot_time": snapshot_time,
        "events_last_5min": events_last_5min,
        "events_last_1h": events_last_1h,
        "events_last_24h": events_last_24h,
        "deletes_last_1h": deletes_last_1h,
        "downloads_last_1h": downloads_last_1h,
        "unique_files_last_1h": unique_files_last_1h,
        "unique_ips_last_24h": unique_ips_last_24h,
        "failed_logins_last_1h": failed_logins_last_1h,
        "hour_of_day_sin": hour_of_day_sin,
        "hour_of_day_cos": hour_of_day_cos,
        "day_of_week": day_of_week,
        "device_context": device_context,
    }


def compute_anomaly_features_batch(
    events_df: pd.DataFrame,
    snapshots: list[tuple[str, pd.Timestamp]],
    auth_events_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Vectorized-by-loop convenience wrapper for training: one row per
    (user_id, snapshot_time) pair in `snapshots`. Not a performance
    optimization -- explicit and easy to reason about, matching how
    ml/features/feature_engineering.py's own batch helper works for
    the access-prediction pipeline.
    """
    rows = [
        compute_anomaly_features(events_df, user_id, snapshot_time, auth_events_df)
        for user_id, snapshot_time in snapshots
    ]
    return pd.DataFrame(rows)


def assert_all_event_types_included(events_df: pd.DataFrame) -> None:
    """Defensive check callable from tests/callers: fail loudly if
    someone upstream pre-filtered events_df to ACCESS_EVENTS only
    before handing it to this module -- that would silently produce
    correct-looking but wrong (under-counted) anomaly features,
    exactly the ACCESS_EVENTS-vs-ALL_EVENT_TYPES distinction §7 is
    explicit about. Not a leakage check -- a scope check.
    """
    present = set(events_df["event_type"].unique()) if not events_df.empty else set()
    unexpected = present - ALL_EVENT_TYPES
    if unexpected:
        raise ValueError(f"events_df contains event_type values outside ALL_EVENT_TYPES: {unexpected}")
