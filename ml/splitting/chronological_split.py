"""
Chronological train/test split with embargo, per Part 2 §3 of the
master reference.

Relevant spec text:

    "rows cannot be randomly split between train/test ... Split
    strategy: chronological only ... Add an embargo/gap at the split
    boundary at least as long as the prediction horizon (7+ days): the
    actual leakage risk is that a training snapshot's label window
    reaches forward past the split boundary ... The embargo exists to
    prevent the training label window from overlapping the test
    feature period, not the other way around. Splitting is the *first*
    step in the pipeline, before any class weighting or oversampling."

Design
------
Given a `split_date` and `embargo_days` (>= horizon_days, enforced
below):

    train_cutoff = split_date - embargo_days
    train = snapshots with snapshot_time <= train_cutoff
    test  = snapshots with snapshot_time >  split_date
    (dropped/embargo zone = snapshot_time in (train_cutoff, split_date])

Why this satisfies the spec's invariant: for any train snapshot at time
T <= train_cutoff, its label window is (T, T + horizon_days]. Since
T <= split_date - embargo_days and embargo_days >= horizon_days:

    T + horizon_days <= split_date - embargo_days + horizon_days <= split_date

So no train snapshot's label window can reach past split_date, and
every test snapshot starts strictly after split_date -- the two label
windows cannot overlap. This is checked directly in
ml/tests/test_chronological_split.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ml.config import EMBARGO_DAYS, HORIZON_DAYS


@dataclass
class SplitResult:
    train: pd.DataFrame
    test: pd.DataFrame
    dropped_embargo: pd.DataFrame
    split_date: pd.Timestamp
    embargo_days: int
    train_cutoff: pd.Timestamp


def chronological_split(
    snapshots_df: pd.DataFrame,
    split_date: pd.Timestamp,
    horizon_days: int = HORIZON_DAYS,
    embargo_days: int = EMBARGO_DAYS,
    time_column: str = "snapshot_time",
) -> SplitResult:
    """
    Split `snapshots_df` chronologically around `split_date`, dropping
    an embargo zone of `embargo_days` immediately before `split_date`.

    Raises ValueError if embargo_days < horizon_days -- the spec is
    explicit that the embargo must be "at least as long as the
    prediction horizon"; silently allowing a shorter embargo would
    reintroduce exactly the leakage this function exists to prevent.

    IMPORTANT: this function must be called BEFORE any class-weighting
    or oversampling step (per spec: "Splitting is the *first* step in
    the pipeline"). It does not perform or know about class balancing
    itself -- that is a modeling-stage concern (Phase 1b, LightGBM
    `scale_pos_weight`), deliberately kept out of this module.
    """
    if embargo_days < horizon_days:
        raise ValueError(
            f"embargo_days ({embargo_days}) must be >= horizon_days ({horizon_days}) "
            "per spec §3: 'embargo/gap at the split boundary at least as long as "
            "the prediction horizon'."
        )

    split_date = pd.Timestamp(split_date)
    train_cutoff = split_date - pd.Timedelta(days=embargo_days)

    times = pd.to_datetime(snapshots_df[time_column])

    train_mask = times <= train_cutoff
    test_mask = times > split_date
    embargo_mask = (~train_mask) & (~test_mask)

    train = snapshots_df.loc[train_mask].reset_index(drop=True)
    test = snapshots_df.loc[test_mask].reset_index(drop=True)
    dropped = snapshots_df.loc[embargo_mask].reset_index(drop=True)

    return SplitResult(
        train=train,
        test=test,
        dropped_embargo=dropped,
        split_date=split_date,
        embargo_days=embargo_days,
        train_cutoff=train_cutoff,
    )
