"""
Label generation for ASCOS access prediction, per Part 2 §3 of the
master reference.

    label = 1  if any ACCESS_EVENT (read/download) for this
                (user_id, file_id) exists in (T, T + horizon]
    label = 0  otherwise

This module owns two responsibilities that the spec ties together:

1. `generate_snapshots`: the sliding-window snapshot generation
   ("for each user, generate one training row every ~3 days from their
   history"). Snapshots are only generated where a full, uncensored
   label window (T, T+horizon] fits inside the observed simulation
   period -- if T+horizon extends past the last observed timestamp, we
   cannot know the true label, so that snapshot is dropped rather than
   silently mislabeled as a false negative.

2. `generate_labels`: given snapshots, look FORWARD from each snapshot
   time to compute the ground-truth label. This is the one place in the
   whole pipeline that is *allowed* to look into the future relative to
   T -- everything in ml/features/feature_engineering.py is explicitly
   forbidden from doing this (see that module's docstring).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import ACCESS_EVENTS, HORIZON_DAYS, SNAPSHOT_CADENCE_DAYS


def generate_snapshots(
    events_df: pd.DataFrame,
    file_metadata_df: pd.DataFrame,
    horizon_days: int = HORIZON_DAYS,
    cadence_days: int = SNAPSHOT_CADENCE_DAYS,
    observation_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Generate sliding-window (user_id, file_id, snapshot_time) rows.

    For each file, snapshots start at its `upload_date` (a file cannot
    be snapshotted before it exists) and repeat every `cadence_days`,
    stopping once `snapshot_time + horizon_days` would exceed
    `observation_end` (default: the last event timestamp in
    `events_df`) -- i.e. every returned snapshot has a *fully observed*
    label window.

    Returns a DataFrame with columns: user_id, file_id, snapshot_time.
    """
    if observation_end is None:
        if len(events_df) == 0:
            raise ValueError("events_df is empty and no observation_end was given")
        observation_end = events_df["timestamp"].max()

    horizon = pd.Timedelta(days=horizon_days)
    cadence = pd.Timedelta(days=cadence_days)
    last_allowed_snapshot = observation_end - horizon

    rows = []
    for _, file_row in file_metadata_df.iterrows():
        upload_date = pd.Timestamp(file_row["upload_date"])
        if upload_date > last_allowed_snapshot:
            # File uploaded too close to the end of the observation
            # window for even one fully-labeled snapshot to exist.
            continue
        t = upload_date
        while t <= last_allowed_snapshot:
            rows.append(
                {
                    "user_id": file_row["user_id"],
                    "file_id": file_row["file_id"],
                    "snapshot_time": t,
                }
            )
            t = t + cadence

    snapshots_df = pd.DataFrame(rows, columns=["user_id", "file_id", "snapshot_time"])
    snapshots_df = snapshots_df.sort_values(["snapshot_time", "user_id", "file_id"]).reset_index(
        drop=True
    )
    return snapshots_df


def generate_labels(
    events_df: pd.DataFrame,
    snapshots_df: pd.DataFrame,
    horizon_days: int = HORIZON_DAYS,
) -> pd.DataFrame:
    """
    Attach a ground-truth `label` column to `snapshots_df`.

    label = 1 if an ACCESS_EVENT (read/download) exists for
    (user_id, file_id) with timestamp in (snapshot_time, snapshot_time
    + horizon_days], else 0.

    This is the ONLY function in the labeling/feature pipeline that is
    allowed to look strictly after snapshot_time. It must never be
    imported by, or its logic duplicated into, feature_engineering.py.
    """
    access_events = events_df[events_df["event_type"].isin(ACCESS_EVENTS)]
    # Group access timestamps per (user_id, file_id) once, up front.
    grouped = {
        key: np.sort(group["timestamp"].to_numpy())
        for key, group in access_events.groupby(["user_id", "file_id"])
    }

    horizon = pd.Timedelta(days=horizon_days)
    labels = np.zeros(len(snapshots_df), dtype=int)

    for i, row in enumerate(snapshots_df.itertuples(index=False)):
        key = (row.user_id, row.file_id)
        ts_array = grouped.get(key)
        if ts_array is None or len(ts_array) == 0:
            continue
        window_start = np.datetime64(pd.Timestamp(row.snapshot_time))
        window_end = np.datetime64(pd.Timestamp(row.snapshot_time) + horizon)
        # (T, T + horizon]  -->  strictly greater than start, <= end
        left = np.searchsorted(ts_array, window_start, side="right")
        right = np.searchsorted(ts_array, window_end, side="right")
        labels[i] = 1 if (right - left) > 0 else 0

    result = snapshots_df.copy()
    result["label"] = labels
    return result
