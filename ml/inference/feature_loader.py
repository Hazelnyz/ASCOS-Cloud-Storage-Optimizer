"""
ml/inference/feature_loader.py

Bridges real AWS data (DynamoDB access_event + S3 object metadata) into
the exact DataFrame shapes ml.features.feature_engineering already
expects (events_df, file_metadata_df) -- per ML_SCHEMA Sec1/Sec2.
Nothing in feature_engineering.py or synthetic_generator.py is modified.

PRESERVES THE AGREED SYNTHETIC + REAL TRAINING STRATEGY (unchanged by
the batch-vs-Lambda inference decision):
  - Real access_event data is used whenever a user has enough of it.
  - ml.data.synthetic_generator (UNMODIFIED) backfills users below that
    threshold, or is used alone for brand-new users / no real users yet.
  - Every synthetic row stays traceable: file_metadata rows carry
    data_source == "synthetic" and a non-null `archetype`
    (synthetic_generator's own debug column). Real rows get
    data_source == "real" and archetype = None.
  - synthetic_generator's own SYNTHETIC_DATA_DISCLAIMER warning still
    fires, unmodified, whenever synthetic generation runs.

No AWS resource names are hardcoded (project rule #16) -- table/bucket
names come from environment variables, matching every deployed Lambda.
"""

from __future__ import annotations

import os

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Key

from ml.config import ACCESS_EVENTS, RANDOM_SEED
from ml.data.synthetic_generator import generate_synthetic_dataset

# --- Open decision, tunable default (documented, not silently guessed) ---
# Minimum real ACCESS_EVENT (read/download) rows a user must have before
# their real data is used without a synthetic backfill. Below this,
# synthetic history fills the gap so recency/frequency features aren't
# computed on too little real signal. Revisit once real usage volume is
# known -- not a frozen spec value, just a starting point.
MIN_REAL_ACCESS_EVENTS_PER_USER = 20

_dynamodb = None
_s3 = None


def _dynamodb_resource():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _access_event_table():
    return _dynamodb_resource().Table(os.environ["ACCESS_EVENT_TABLE"])


def _protected_files_table():
    return _dynamodb_resource().Table(os.environ["PROTECTED_FILES_TABLE"])


def load_real_events_for_user(user_id: str) -> pd.DataFrame:
    """
    Query access_event for one user -- partition-key Query, NEVER a
    Scan, preserving cross-user isolation the same way every real
    Stage 6 Lambda already does.

    Returns a DataFrame shaped exactly like synthetic_generator's
    events_df: event_id, user_id, file_id, event_type, timestamp,
    source_ip, device_context.
    """
    table = _access_event_table()
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("user_id").eq(user_id)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    cols = ["event_id", "user_id", "file_id", "event_type",
            "timestamp", "source_ip", "device_context"]
    if not items:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(items)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    # Normalize to tz-naive UTC for compatibility with feature_engineering.py
    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _file_type_from_filename(filename: str) -> str:
    if "." not in filename:
        return "unknown"
    return filename.rsplit(".", 1)[-1].lower()


def _size_bucket(size_bytes: int) -> str:
    # Buckets per Sec2 ("small/medium/large ... generalizes better than
    # raw bytes"). Exact cutoffs are an implementation detail the
    # schema leaves open -- documented here as the single source.
    mb = size_bytes / (1024 * 1024)
    if mb < 1:
        return "small"
    if mb < 50:
        return "medium"
    return "large"


# Same HOT/WARM/COLD <-> S3 storage-class mapping the frontend already
# uses (types/index.ts) -- kept identical so ML and UI never disagree.
_S3_CLASS_TO_TIER = {
    "STANDARD": "HOT",
    "STANDARD_IA": "WARM",
    "GLACIER_IR": "COLD",
    "GLACIER": "COLD",
    "DEEP_ARCHIVE": "COLD",
}


def _tier_from_storage_class(storage_class) -> str:
    # S3 omits StorageClass entirely for STANDARD objects.
    return _S3_CLASS_TO_TIER.get(storage_class or "STANDARD", "HOT")


def _earliest_write_event(events_df: pd.DataFrame, file_id: str):
    """
    upload_date reconstruction, per the compatibility report's plan:
    earliest `write` access_event for this file; falls back to the
    earliest event of ANY type if no write event exists yet (e.g. the
    file predates Stage 7 going live). Returns (None, True) if this
    file has no access_event history at all -- caller then falls back
    to S3 LastModified and flags the result approximate.
    """
    file_events = events_df[events_df["file_id"] == file_id]
    if file_events.empty:
        return None, True
    writes = file_events[file_events["event_type"] == "write"]
    if not writes.empty:
        return writes["timestamp"].min(), False
    return file_events["timestamp"].min(), True


def load_real_file_metadata_for_user(user_id: str, events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Reconstructs File State feature inputs (Sec2) for every S3 object
    under this user's prefix:
      file_type            <- filename extension (x-amz-meta-filename)
      file_size_bucket     <- S3 object size
      current_storage_tier <- S3 StorageClass via the shared mapping
      directory_category   <- constant placeholder (no folder concept
                               exists in ASCOS's flat {user_id}/{file_id}
                               key design, Master Reference Sec7 -- kept
                               as an agreed, inert placeholder rather
                               than dropped, so FEATURE_COLUMNS stays
                               stable)
      protected_flag       <- protected_files table (False if no row;
                               no pin/unpin backend writes it yet)
      upload_date           <- earliest real `write` event, else S3
                               LastModified (flagged approximate)
    """
    bucket = os.environ["S3_BUCKET_NAME"]
    s3 = _s3_client()
    protected = _protected_files_table()

    protected_ids: set[str] = set()
    resp = protected.query(KeyConditionExpression=Key("user_id").eq(user_id))
    protected_ids.update(item["file_id"] for item in resp.get("Items", []))

    rows = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{user_id}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            file_id = key.split("/", 1)[1] if "/" in key else key
            # ListObjectsV2 already returns size, LastModified, and
            # StorageClass. HeadObject remains necessary for the custom
            # x-amz-meta-filename value used to derive file_type.
            head = s3.head_object(Bucket=bucket, Key=key)
            filename = head.get("Metadata", {}).get("filename", file_id)

            upload_date, is_approx = _earliest_write_event(events_df, file_id)
            if upload_date is None:
                upload_date = pd.Timestamp(obj["LastModified"]).tz_localize(None)
                is_approx = True
            # Normalize to tz-naive UTC for compatibility with feature_engineering.py
            if upload_date is not None and upload_date.tzinfo is not None:
                upload_date = upload_date.tz_convert("UTC").tz_localize(None)

            rows.append({
                "file_id": file_id,
                "user_id": user_id,
                "upload_date": upload_date,
                "file_type": _file_type_from_filename(filename),
                "file_size_bucket": _size_bucket(obj["Size"]),
                "directory_category": "uncategorized",
                "current_storage_tier": _tier_from_storage_class(obj.get("StorageClass")),
                "protected_flag": file_id in protected_ids,
                "archetype": None,       # real data -- not a synthetic archetype
                "data_source": "real",
                "upload_date_is_approximate": is_approx,
            })

    cols = ["file_id", "user_id", "upload_date", "file_type", "file_size_bucket",
            "directory_category", "current_storage_tier", "protected_flag",
            "archetype", "data_source", "upload_date_is_approximate"]
    return pd.DataFrame(rows, columns=cols)


def load_training_data(user_ids: list[str] | None = None, seed: int = RANDOM_SEED):
    """
    Assembles (events_df, file_metadata_df, provenance) applying the
    agreed synthetic + real strategy:

      - Each real user's access_event history is pulled from DynamoDB.
      - A user is "real-sufficient" once their ACCESS_EVENTS
        (read/download) count reaches MIN_REAL_ACCESS_EVENTS_PER_USER.
      - Real-sufficient users train/predict on their real data.
      - Users below the threshold (including brand-new users) are
        backfilled with ml.data.synthetic_generator output, UNMODIFIED.
      - If `user_ids` is None/empty, the whole dataset falls back to
        synthetic-only -- the current bootstrap state until enough
        real data accumulates. This is not a permanent choice; it's
        exactly what the agreed strategy says should happen when real
        data is insufficient.
      - `provenance` records, per user, whether real/synthetic-backfill
        was used -- goes straight into the model's metadata artifact
        alongside model_version/seed/feature_columns.

    Returns
    -------
    events_df, file_metadata_df, provenance (dict[user_id, str])
    """
    events_frames = []
    metadata_frames = []
    provenance: dict[str, str] = {}

    if user_ids:
        for user_id in user_ids:
            real_events = load_real_events_for_user(user_id)
            n_access = int(real_events["event_type"].isin(ACCESS_EVENTS).sum())

            if not real_events.empty:
                real_meta = load_real_file_metadata_for_user(user_id, real_events)
                events_frames.append(real_events)
                metadata_frames.append(real_meta)

            provenance[user_id] = (
                "real"
                if n_access >= MIN_REAL_ACCESS_EVENTS_PER_USER
                else f"synthetic_backfill (real_access_events={n_access})"
            )

    needs_synthetic = (not user_ids) or any(
        v.startswith("synthetic_backfill") for v in provenance.values()
    )

    if needs_synthetic:
        synth_events, synth_meta = generate_synthetic_dataset(seed=seed)
        synth_meta = synth_meta.copy()
        synth_meta["data_source"] = "synthetic"
        synth_meta["upload_date_is_approximate"] = False
        events_frames.append(synth_events)
        metadata_frames.append(synth_meta)
        if not user_ids:
            provenance["_dataset"] = "synthetic_only (no real users supplied)"

    events_df = (
        pd.concat(events_frames, ignore_index=True) if events_frames else pd.DataFrame()
    )
    file_metadata_df = (
        pd.concat(metadata_frames, ignore_index=True) if metadata_frames else pd.DataFrame()
    )

    return events_df, file_metadata_df, provenance
