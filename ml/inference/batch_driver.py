"""
ml/inference/batch_driver.py

Thin driver script -- NOT a second ML implementation. All real logic
lives in predictor.py / feature_loader.py / policy.py / bandit.py; this
file only: discovers which real users/files exist, calls
predictor.predict_one() per (user, file), and writes the result to the
existing `predictions` DynamoDB table using the exact attribute names
Stage 4's table design (and frequently-used-fn's read path) already
expect. No fabricated/demo rows are ever written -- every row here
comes from a real predict_one() call against real feature data (which
may itself be synthetic-backfilled per the agreed strategy, but the
PREDICTION is always genuinely computed, never hardcoded).

Per ML_SCHEMA Sec8: training/batch-inference belongs in a scheduled
job, not a request-serving Lambda. This script is meant to be invoked
that way (e.g. by training-orchestrator-fn triggering an EC2/Fargate
run, per your existing EC2-training design) -- it is a plain Python
entry point with no AWS-Lambda-specific wrapping, so it runs the same
way locally, in a container, or on EC2.

Run:
    python -m ml.inference.batch_driver --model-version <version>

Requires env vars (no hardcoding, matches every deployed Lambda):
    ACCESS_EVENT_TABLE, PROTECTED_FILES_TABLE, USER_BASELINE_TABLE,
    PREDICTIONS_TABLE, S3_BUCKET_NAME
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from decimal import Decimal
from pathlib import Path

import boto3
import pandas as pd

from ml.inference import feature_loader, predictor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "models"


def latest_model_version() -> str:
    """
    Picks the most recently trained artifact by metadata file mtime.
    Explicit --model-version always wins over this -- this is only a
    convenience default for local/manual runs.
    """
    meta_files = sorted(
        MODEL_ARTIFACT_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime
    )
    if not meta_files:
        raise FileNotFoundError(
            f"no trained model artifacts found under {MODEL_ARTIFACT_DIR} -- "
            "run ml/modeling/train_lightgbm.py first."
        )
    return meta_files[-1].stem.removesuffix(".meta")


def discover_user_ids() -> list[str]:
    """
    S3 key design is {user_id}/{file_id} (Master Reference Sec7,
    locked) -- top-level common prefixes under the bucket root ARE the
    real user_id set. Uses Delimiter='/' so this is a cheap prefix
    listing, not a full-bucket walk.
    """
    bucket = os.environ["S3_BUCKET_NAME"]
    s3 = boto3.client("s3")
    user_ids: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            user_ids.append(prefix["Prefix"].rstrip("/"))
    return user_ids


def _to_dynamodb_number(value):
    """DynamoDB's boto3 resource interface rejects native float -- must
    go through Decimal, round-tripped via str() to avoid binary-float
    precision artifacts (e.g. 0.1 -> Decimal('0.1000000000000000055...'))."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_dynamodb_number(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_dynamodb_number(v) for k, v in value.items()}
    return value


def write_prediction(table, prediction: dict) -> None:
    """
    Writes one prediction dict (exact Sec4 shape from predictor.py)
    into the predictions table's real schema: PK prediction_id, plus
    the composite attributes both GSIs (user-file-index, user-index)
    key off -- user_id_file_id and prediction_timestamp_id.
    """
    item = {
        "prediction_id": prediction["prediction_id"],
        "user_id": prediction["user_id"],
        "file_id": prediction["file_id"],
        "user_id_file_id": f"{prediction['user_id']}#{prediction['file_id']}",
        "prediction_timestamp_id": f"{prediction['prediction_timestamp']}#{prediction['prediction_id']}",
        "prediction_timestamp": prediction["prediction_timestamp"],
        "model_version": prediction["model_version"],
        "feature_schema_version": prediction["feature_schema_version"],
        "p_access": _to_dynamodb_number(prediction["p_access"]),
        "candidate_tiers": prediction["candidate_tiers"],
        "bandit_choice": prediction["bandit_choice"],
        "bandit_context": prediction["bandit_context"],
        "top_reasons": _to_dynamodb_number(prediction["top_reasons"]),
    }
    table.put_item(Item=item)


def run(
    model_version: str | None = None,
    user_ids: list[str] | None = None,
    run_id: str | None = None,
) -> int:
    """Returns the number of prediction rows written."""
    model_version = model_version or latest_model_version()
    user_ids = user_ids if user_ids is not None else discover_user_ids()
    run_id = run_id or str(uuid.uuid4())

    if not user_ids:
        logger.warning("no users discovered under the app storage bucket -- nothing to predict")
        return 0

    dynamodb = boto3.resource("dynamodb")
    predictions_table = dynamodb.Table(os.environ["PREDICTIONS_TABLE"])

    written = 0
    failed = 0
    for user_id in user_ids:
        events_df = feature_loader.load_real_events_for_user(user_id)
        file_metadata_df = feature_loader.load_real_file_metadata_for_user(user_id, events_df)

        if file_metadata_df.empty:
            logger.info("user_id=%s has no files in S3 -- skipping", user_id)
            continue

        for _, file_row in file_metadata_df.iterrows():
            try:
                prediction = predictor.predict_one(
                    user_id=user_id,
                    file_id=file_row["file_id"],
                    events_df=events_df,
                    file_metadata_row=file_row,
                    model_version=model_version,
                    run_id=run_id,
                )
                write_prediction(predictions_table, prediction)
                written += 1
                logger.info(
                    "wrote prediction user_id=%s file_id=%s p_access=%.4f bandit_choice=%s",
                    user_id, file_row["file_id"], prediction["p_access"], prediction["bandit_choice"],
                )
            except Exception:
                failed += 1
                logger.exception(
                    "prediction failed for user_id=%s file_id=%s -- skipping this file, "
                    "continuing batch", user_id, file_row["file_id"],
                )

    if written == 0 and failed > 0:
        logger.error(
            "batch inference complete with ZERO predictions written: %d files failed. "
            "This is a full-failure run - check logs for root causes.",
            failed,
        )
    else:
        logger.info("batch inference complete: %d prediction rows written, %d failed", written, failed)
    if failed:
        # A queue consumer retries the run; stable prediction IDs make already
        # successful file writes safe to repeat while failed files are retried.
        raise RuntimeError(f"batch inference had {failed} file failures")
    return written


def main():
    parser = argparse.ArgumentParser(description="ASCOS batch inference driver")
    parser.add_argument("--model-version", default=None, help="defaults to the most recently trained artifact")
    args = parser.parse_args()
    run(model_version=args.model_version)


if __name__ == "__main__":
    main()
