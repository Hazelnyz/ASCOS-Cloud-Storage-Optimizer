"""
Real-data adapter -- converts already-fetched DynamoDB `access_event`
items and S3 object/metadata info into the exact events_df /
file_metadata_df shapes ml.features.feature_engineering already
expects. Nothing in ml/features, ml/labels, ml/splitting, or
ml/modeling is modified or duplicated by this module.

DELIBERATE SEPARATION: this module takes plain Python dicts/lists as
input (whatever a boto3 call already returned) -- it does NOT call
boto3 itself. That keeps it fully testable without boto3/moto being
installed anywhere (see ml/tests/test_real_data_adapter.py, which runs
for real in this environment), and keeps "how to fetch it from AWS" a
separate, thin concern that lives in the Lambda handler code
(backend/prediction-fn, backend/access-analytics-fn, etc.).

*** Stage 10 decisions this module encodes (per explicit instruction) ***

1. `directory_category`: ASCOS has no real folder/directory concept --
   storage is a flat `{user_id}/{file_id}` prefix (Master Reference
   §7). Real inference uses a constant, neutral fallback category
   (`NEUTRAL_DIRECTORY_CATEGORY = "root/default"`) rather than
   inventing structure that doesn't exist. This is clearly NOT real
   user information -- every real file gets the exact same value,
   carrying zero predictive signal, by design. The Phase 3 feature
   CONTRACT (feature_engineering.FEATURE_COLUMNS) is unchanged; only
   the value fed into that existing column differs for real data.

2. `upload_date` reconstruction: real ASCOS has no dedicated
   file-metadata table, and S3 `LastModified` is not stable across
   edits. This module reconstructs `upload_date` as the EARLIEST
   `write` access_event for that (user_id, file_id) when one exists.
   If no `write` event exists yet (e.g. a file that predates Stage 7's
   access-event pipeline going live), it falls back to the earliest
   event of ANY type for that file, and flags the row as approximate
   via `upload_date_is_approximate` -- an extra diagnostic column that
   Phase 3's feature functions simply ignore (they only read the
   specific keys they need), so this never breaks the existing
   feature contract.

3. `protected_flag`: read from a caller-supplied lookup (the
   `protected_files` table), defaulting to False when the file has no
   row there -- consistent with the table's row-exists-means-protected
   semantics already established for ASCOS.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

NEUTRAL_DIRECTORY_CATEGORY = "root/default"

# Real S3 storage-class -> logical tier mapping. Kept identical to the
# frontend's S3_CLASS_TO_TIER table (frontend/src/types/index.ts) so
# the two sides of the system never disagree about what "HOT" means.
S3_CLASS_TO_TIER = {
    "STANDARD": "HOT",
    "STANDARD_IA": "WARM",
    "GLACIER_IR": "COLD",
}

# File-size bucket thresholds. The synthetic generator's "small/medium/
# large" categories were purely nominal (randomly assigned, never tied
# to an actual byte count), so real data needs its own explicit
# thresholds -- the spec does not mandate specific numbers, so these
# are a documented, reasonable default, not a derived spec value.
SMALL_FILE_MAX_BYTES = 1_000_000  # 1 MB
MEDIUM_FILE_MAX_BYTES = 100_000_000  # 100 MB


def bucket_file_size(size_bytes: int) -> str:
    if size_bytes < SMALL_FILE_MAX_BYTES:
        return "small"
    if size_bytes < MEDIUM_FILE_MAX_BYTES:
        return "medium"
    return "large"


def file_type_from_filename(filename: str | None) -> str:
    """Extension without the dot, lowercased. 'unknown' if there's no
    filename (e.g. metadata hasn't been decoded/found) or no extension."""
    if not filename or "." not in filename:
        return "unknown"
    return filename.rsplit(".", 1)[-1].lower()


def tier_from_s3_storage_class(storage_class: str | None) -> str:
    """Mirrors frontend's tierFromStorageClass; defaults to HOT (S3's
    own convention: STANDARD objects often omit StorageClass entirely
    on ListObjectsV2 -- same convention file-list-fn already follows)."""
    if not storage_class:
        return "HOT"
    return S3_CLASS_TO_TIER.get(storage_class.upper(), "HOT")


def access_event_items_to_dataframe(items: list[dict]) -> pd.DataFrame:
    """
    Converts a list of raw `access_event` DynamoDB items (as plain
    dicts -- i.e. already through boto3's response, NOT boto3 Attribute
    objects) into the events_df shape feature_engineering.py expects:
    event_id, user_id, file_id, event_type, timestamp, source_ip,
    device_context.

    Only reads the plain (non-composite-key) attributes -- the
    composite `timestamp_event_id` / `user_id_file_id` sort/GSI keys
    are ignored entirely, since the writer (access-event-writer-fn)
    already stores each component as its own plain attribute too.
    """
    if not items:
        return pd.DataFrame(
            columns=["event_id", "user_id", "file_id", "event_type", "timestamp", "source_ip", "device_context"]
        )
    rows = []
    for item in items:
        rows.append(
            {
                "event_id": item["event_id"],
                "user_id": item["user_id"],
                "file_id": item["file_id"],
                "event_type": item["event_type"],
                "timestamp": pd.Timestamp(item["timestamp"]),
                "source_ip": item.get("source_ip"),
                "device_context": item.get("device_context"),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values(["user_id", "file_id", "timestamp"]).reset_index(drop=True)


@dataclass
class RealFileInput:
    """What the caller (prediction-fn) must supply per real file --
    deliberately plain data, no boto3 objects."""
    file_id: str
    user_id: str
    size_bytes: int
    storage_class: str | None  # raw S3 value, or None
    filename: str | None  # decoded filename, or None if not available
    is_protected: bool


def build_file_metadata_row(
    file_input: RealFileInput,
    events_for_file: pd.DataFrame,
    now: pd.Timestamp,
) -> dict:
    """
    Builds one file_metadata_df row for real inference, per the three
    Stage 10 decisions in this module's docstring.

    `events_for_file` should already be filtered to this file's own
    events (any subset of the real events_df is fine -- this function
    does its own additional filtering defensively).
    """
    if len(events_for_file) == 0 or "user_id" not in events_for_file.columns:
        own_events = events_for_file.iloc[0:0]
    else:
        own_events = events_for_file[
            (events_for_file["user_id"] == file_input.user_id)
            & (events_for_file["file_id"] == file_input.file_id)
        ]
    write_events = own_events[own_events["event_type"] == "write"] if len(own_events) else own_events

    upload_date_is_approximate = False
    if len(write_events) > 0:
        upload_date = write_events["timestamp"].min()
    elif len(own_events) > 0:
        upload_date = own_events["timestamp"].min()
        upload_date_is_approximate = True
    else:
        # No event history at all yet for this file -- nothing to
        # reconstruct from. Use `now` and flag it loudly; file_age_days
        # will read as ~0, which is honest (we have zero evidence of
        # how old the file actually is).
        upload_date = now
        upload_date_is_approximate = True

    return {
        "file_id": file_input.file_id,
        "user_id": file_input.user_id,
        "upload_date": upload_date,
        "upload_date_is_approximate": upload_date_is_approximate,  # diagnostic only, not a model feature
        "file_type": file_type_from_filename(file_input.filename),
        "file_size_bucket": bucket_file_size(file_input.size_bytes),
        "directory_category": NEUTRAL_DIRECTORY_CATEGORY,
        "current_storage_tier": tier_from_s3_storage_class(file_input.storage_class),
        "protected_flag": bool(file_input.is_protected),
    }


def build_file_metadata_dataframe(
    file_inputs: list[RealFileInput],
    events_df: pd.DataFrame,
    now: pd.Timestamp,
) -> pd.DataFrame:
    rows = [build_file_metadata_row(fi, events_df, now) for fi in file_inputs]
    return pd.DataFrame(rows)
