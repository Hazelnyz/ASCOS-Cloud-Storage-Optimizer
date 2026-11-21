"""
Leakage-safe feature engineering for ASCOS access prediction, per Part 2
§2 of the master reference.

*** GOLDEN RULE (spec §1, repeated here because it is the single most
important constraint in this module): ***

    Every feature, for a snapshot at time T, must be computed using
    ONLY events at or before T. Nothing after T is allowed into a
    feature -- that window belongs exclusively to the label.

Enforcement strategy
---------------------
Rather than trusting callers to pre-filter `events_df` to "only events
<= T" before calling in here, every feature-computation function in this
module filters internally, from the full/raw events_df, using an
explicit `timestamp <= snapshot_time` boundary. This means:

  - Passing the FULL events_df (including future events) produces the
    exact same features as passing a pre-truncated events_df.
  - There is exactly one place in the codebase (`_events_up_to`) where
    the leakage boundary is drawn, which is what
    ml/tests/test_feature_leakage.py exercises directly.

ACCESS_EVENTS (read, download) vs. all events
----------------------------------------------
Per §1/§2: all recency/frequency/temporal features use ONLY
ACCESS_EVENTS = {read, download}. write/delete/share are real events,
kept for other consumers (anomaly detection), but excluded from every
recency/frequency/prediction calculation here -- except `share_count_30d`
which is explicitly defined on `share` events, and the file-state group
which isn't event-derived at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import (
    ACCESS_EVENTS,
    CO_ACCESS_WINDOW_MINUTES,
    SHARE_COUNT_WINDOW_DAYS,
)

# Columns fed to the model as features (§2 "one row per (user_id,
# file_id, snapshot_timestamp)"). file_id / user_id / snapshot_timestamp
# are join keys, not features themselves -- kept as separate columns in
# the output DataFrame but explicitly excluded from FEATURE_COLUMNS so
# downstream code (LightGBM training in Phase 1b) knows exactly what to
# feed the model versus what to use as a key.
FEATURE_COLUMNS = [
    # Temporal
    "file_age_days",
    "days_since_last_access",
    "never_accessed",
    "access_hour_sin",
    "access_hour_cos",
    "last_access_day_of_week",
    "access_hour_consistency",
    # Behavioral
    "access_count_7d",
    "access_count_30d",
    "access_count_90d",
    "access_count_all_time",
    "recent_access_ratio",
    "access_acceleration",
    "user_avg_daily_accesses",
    "co_access_signal",
    "share_count_30d",
    # File state
    "file_type",
    "file_size_bucket",
    "directory_category",
    "current_storage_tier",
    # NOTE: protected_flag is intentionally NOT in this list.
    # Per §2: "protected_flag | boolean -- NOT fed to the model as a
    # predictive feature; read separately by the policy engine as a
    # hard gate." It is still attached to the output DataFrame (as
    # `protected_flag`) so the policy engine can read it, but callers
    # must exclude it (and it IS excluded here) when building the
    # LightGBM training matrix.
]

CATEGORICAL_COLUMNS = [
    "last_access_day_of_week",
    "file_type",
    "file_size_bucket",
    "directory_category",
    "current_storage_tier",
]

DAY_OF_WEEK_CATEGORIES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _events_up_to(events_df: pd.DataFrame, snapshot_time: pd.Timestamp) -> pd.DataFrame:
    """The single leakage boundary in this module. Every feature
    function must route its event access through here (or through a
    structure derived from it) rather than reading `events_df` raw."""
    return events_df[events_df["timestamp"] <= snapshot_time]


def _circular_variance(hours: np.ndarray) -> float:
    """Circular variance of a set of hour-of-day values (0-23), based on
    their sin/cos encoding, per §2:
    'circular variance of access hour ... computed on the sin/cos pair,
    not raw hour'. Returns a value in [0, 1]; 0 = perfectly consistent
    (all same hour), 1 = maximally dispersed."""
    angles = 2 * np.pi * hours / 24.0
    mean_cos = np.mean(np.cos(angles))
    mean_sin = np.mean(np.sin(angles))
    mean_resultant_length = np.sqrt(mean_cos**2 + mean_sin**2)
    return float(1.0 - mean_resultant_length)


def compute_features_for_snapshot(
    events_df: pd.DataFrame,
    file_metadata_row: pd.Series,
    user_id: str,
    file_id: str,
    snapshot_time: pd.Timestamp,
) -> dict:
    """
    Compute one feature row for (user_id, file_id, snapshot_time).

    `events_df` may be the FULL raw event log (including events after
    snapshot_time) -- this function enforces the leakage boundary
    itself via `_events_up_to`. This is deliberate: it means leakage
    safety does not depend on the caller remembering to pre-filter.

    `file_metadata_row` supplies the non-event-derived File State
    features (file_type, file_size_bucket, directory_category,
    current_storage_tier, upload_date, protected_flag).
    """
    past = _events_up_to(events_df, snapshot_time)
    file_past = past[(past["user_id"] == user_id) & (past["file_id"] == file_id)]

    # ACCESS_EVENTS-only subset for this file, sorted by time.
    file_access = file_past[file_past["event_type"].isin(ACCESS_EVENTS)].sort_values("timestamp")
    access_timestamps = file_access["timestamp"].to_numpy()

    never_accessed = len(access_timestamps) == 0

    # ---------------- Temporal ----------------
    upload_date = pd.Timestamp(file_metadata_row["upload_date"])
    file_age_days = (snapshot_time - upload_date).total_seconds() / 86400.0

    if never_accessed:
        days_since_last_access = np.nan
        access_hour_sin = np.nan
        access_hour_cos = np.nan
        last_access_day_of_week = None
        access_hour_consistency = np.nan
    else:
        last_access_ts = pd.Timestamp(access_timestamps[-1])
        days_since_last_access = (snapshot_time - last_access_ts).total_seconds() / 86400.0
        last_hour = last_access_ts.hour
        access_hour_sin = float(np.sin(2 * np.pi * last_hour / 24.0))
        access_hour_cos = float(np.cos(2 * np.pi * last_hour / 24.0))
        last_access_day_of_week = DAY_OF_WEEK_CATEGORIES[last_access_ts.dayofweek]

        if len(access_timestamps) >= 2:
            recent_hours = pd.DatetimeIndex(access_timestamps).hour.to_numpy()
            access_hour_consistency = _circular_variance(recent_hours)
        else:
            access_hour_consistency = np.nan

    # ---------------- Behavioral ----------------
    def _count_in_window(days: float) -> int:
        cutoff = snapshot_time - pd.Timedelta(days=days)
        return int(np.sum(access_timestamps > np.datetime64(cutoff)))

    access_count_7d = _count_in_window(7)
    access_count_30d = _count_in_window(30)
    access_count_90d = _count_in_window(90)
    access_count_all_time = int(len(access_timestamps))

    recent_access_ratio = access_count_7d / max(access_count_30d, 1)

    # access_acceleration: compare the last 7d to the *previous* 7d
    # (i.e. days [T-14, T-7)), NOT the same 7d window used above.
    prev_cutoff_start = snapshot_time - pd.Timedelta(days=14)
    prev_cutoff_end = snapshot_time - pd.Timedelta(days=7)
    access_count_prev_7d = int(
        np.sum(
            (access_timestamps > np.datetime64(prev_cutoff_start))
            & (access_timestamps <= np.datetime64(prev_cutoff_end))
        )
    )
    access_acceleration = (access_count_7d - access_count_prev_7d) / max(access_count_prev_7d, 1)

    # user_avg_daily_accesses: user-level baseline, at-or-before T only.
    user_past_access = past[(past["user_id"] == user_id) & (past["event_type"].isin(ACCESS_EVENTS))]
    if len(user_past_access) == 0:
        user_avg_daily_accesses = 0.0
    else:
        user_first_ts = user_past_access["timestamp"].min()
        elapsed_days = max((snapshot_time - user_first_ts).total_seconds() / 86400.0, 1.0)
        user_avg_daily_accesses = len(user_past_access) / elapsed_days

    # co_access_signal: for each of this file's access events (<=T),
    # count other-file access events (<=T, same user) within
    # CO_ACCESS_WINDOW_MINUTES.
    co_access_signal = 0
    if not never_accessed:
        user_access_all = past[(past["user_id"] == user_id) & (past["event_type"].isin(ACCESS_EVENTS))]
        other_file_access = user_access_all[user_access_all["file_id"] != file_id]
        if len(other_file_access) > 0:
            other_ts_sorted = np.sort(other_file_access["timestamp"].to_numpy())
            window = pd.Timedelta(minutes=CO_ACCESS_WINDOW_MINUTES)
            for t in access_timestamps:
                lo = np.datetime64(pd.Timestamp(t) - window)
                hi = np.datetime64(pd.Timestamp(t) + window)
                # Both sides of the co-access window must themselves be
                # <= snapshot_time to avoid leaking a future co-access
                # (per §2: "a co-access that happened after T is future
                # information and must not leak in").
                hi = min(hi, np.datetime64(snapshot_time))
                left = np.searchsorted(other_ts_sorted, lo, side="left")
                right = np.searchsorted(other_ts_sorted, hi, side="right")
                co_access_signal += int(right - left)

    # share_count_30d: `share` events (NOT an ACCESS_EVENT) in the
    # trailing SHARE_COUNT_WINDOW_DAYS window, at-or-before T.
    share_cutoff = snapshot_time - pd.Timedelta(days=SHARE_COUNT_WINDOW_DAYS)
    share_count_30d = int(
        ((file_past["event_type"] == "share") & (file_past["timestamp"] > share_cutoff)).sum()
    )

    # ---------------- File state ----------------
    file_type = file_metadata_row["file_type"]
    file_size_bucket = file_metadata_row["file_size_bucket"]
    directory_category = file_metadata_row["directory_category"]
    current_storage_tier = file_metadata_row["current_storage_tier"]
    protected_flag = bool(file_metadata_row["protected_flag"])

    return {
        "user_id": user_id,
        "file_id": file_id,
        "snapshot_time": snapshot_time,
        # Temporal
        "file_age_days": file_age_days,
        "days_since_last_access": days_since_last_access,
        "never_accessed": bool(never_accessed),
        "access_hour_sin": access_hour_sin,
        "access_hour_cos": access_hour_cos,
        "last_access_day_of_week": last_access_day_of_week,
        "access_hour_consistency": access_hour_consistency,
        # Behavioral
        "access_count_7d": access_count_7d,
        "access_count_30d": access_count_30d,
        "access_count_90d": access_count_90d,
        "access_count_all_time": access_count_all_time,
        "recent_access_ratio": recent_access_ratio,
        "access_acceleration": access_acceleration,
        "user_avg_daily_accesses": user_avg_daily_accesses,
        "co_access_signal": co_access_signal,
        "share_count_30d": share_count_30d,
        # File state
        "file_type": file_type,
        "file_size_bucket": file_size_bucket,
        "directory_category": directory_category,
        "current_storage_tier": current_storage_tier,
        # Hard-gate flag, NOT a model feature (see FEATURE_COLUMNS docstring).
        "protected_flag": protected_flag,
    }


def compute_feature_matrix(
    events_df: pd.DataFrame,
    file_metadata_df: pd.DataFrame,
    snapshots_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Batch version of compute_features_for_snapshot.

    `snapshots_df` must have columns: user_id, file_id, snapshot_time.

    Returns a DataFrame with one row per input snapshot, in the same
    order, containing all columns produced by compute_features_for_snapshot.
    """
    meta_indexed = file_metadata_df.set_index("file_id")

    rows = []
    for _, snap in snapshots_df.iterrows():
        file_row = meta_indexed.loc[snap["file_id"]]
        rows.append(
            compute_features_for_snapshot(
                events_df=events_df,
                file_metadata_row=file_row,
                user_id=snap["user_id"],
                file_id=snap["file_id"],
                snapshot_time=pd.Timestamp(snap["snapshot_time"]),
            )
        )
    result = pd.DataFrame(rows)

    # Categorical dtype for LightGBM's native categorical handling
    # (Phase 1b). Set here so the contract is established even though
    # LightGBM training itself is out of scope for this phase.
    for col in CATEGORICAL_COLUMNS:
        if col in result.columns:
            if col == "last_access_day_of_week":
                result[col] = pd.Categorical(result[col], categories=DAY_OF_WEEK_CATEGORIES)
            else:
                result[col] = result[col].astype("category")

    result.attrs["data_source"] = events_df.attrs.get("data_source", "unknown")
    return result
