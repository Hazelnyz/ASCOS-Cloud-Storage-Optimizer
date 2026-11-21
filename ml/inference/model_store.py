"""
ml/inference/model_store.py

Single source of truth for resolving a model artifact's LOCAL file
path, whether running locally (Phase 3 style: a plain directory
already on disk) or inside a deployed container-image Lambda (no
artifacts baked into the image -- must pull from the S3 model
registry, per ML_SCHEMA Sec10: s3://ascos-models/{user_id}/{model_version}/
model.txt -- and cache to /tmp so a warm container doesn't
re-download on every invocation).

Used by BOTH ml.inference.predictor.ModelBundle (LightGBM) and
ml.anomaly.score.AnomalyModelBundle (IsolationForest) -- one place
for the S3-vs-local decision and the /tmp caching logic, not
duplicated in each.

Resolution rule, in order:
  1. MODEL_ARTIFACT_S3_BUCKET NOT set -> local-dev path, UNCHANGED
     from before this file existed: look directly in the given local
     directory. This is the deliberate signal that keeps the existing
     local-development workflow (ml/models/, ml/anomaly's
     artifacts_dir) working exactly as before.
  2. MODEL_ARTIFACT_S3_BUCKET set (the deployed-Lambda case) -> check
     /tmp cache first (survives across warm invocations of the SAME
     container, at zero extra cost); on a cache miss, download from
     S3 and cache it there before returning.

Every artifact handled here is a PAIR of files (e.g. <key>.txt +
<key>.meta.json, or <key>.pkl + <key>.meta.json) -- both must resolve
successfully or this raises. A partially-downloaded or partially
present pair is never treated as valid, and the ML model/prediction
logic itself is untouched by any of this -- this module only ever
answers "where is the file on disk right now."

No AWS resource names are hardcoded (project rule #16): bucket name
and an optional key prefix come from environment variables, same as
every other deployed Lambda in this project.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# /tmp is the only writable filesystem inside a Lambda execution
# environment. Its ephemeral storage (512 MB default, configurable up
# to 10 GB) is reused across warm invocations of the SAME container --
# that reuse is exactly the caching behavior this module implements.
# Overridable via env var purely for local testing of the S3 code path
# without actually touching a real /tmp.
_TMP_CACHE_ROOT = Path(os.environ.get("ASCOS_MODEL_TMP_CACHE_DIR", "/tmp/ascos_model_cache"))


class ModelArtifactError(Exception):
    """
    Raised whenever a model artifact pair cannot be resolved to a
    valid local path -- either the local-dev directory is missing the
    files, or the S3 download failed for any reason (missing object,
    access denied, network error). Never swallowed or silenced here;
    a missing/unreachable model artifact is not a state a
    prediction/anomaly-scoring call should silently proceed past.
    """


def _s3_bucket() -> str | None:
    # Absence of this env var is the deliberate local-dev signal, not
    # a misconfiguration -- so this returns None rather than raising.
    return os.environ.get("MODEL_ARTIFACT_S3_BUCKET") or None


def _s3_prefix() -> str:
    prefix = os.environ.get("MODEL_ARTIFACT_S3_PREFIX", "")
    return prefix if (not prefix or prefix.endswith("/")) else prefix + "/"


def resolve_artifact_paths(
    key: str,
    filename_by_role: dict[str, str],
    local_dir: str | Path,
    cache_subdir: str,
) -> dict[str, Path]:
    """
    Resolves every file in `filename_by_role` (e.g.
    {"model": "<key>.txt", "meta": "<key>.meta.json"}) to a real,
    present-on-disk local Path -- downloading from S3 and caching to
    /tmp first if MODEL_ARTIFACT_S3_BUCKET is set, otherwise reading
    straight from `local_dir` exactly as before this module existed.

    `cache_subdir` namespaces the /tmp cache per artifact family
    (e.g. "lgbm" vs "anomaly") so the two bundle types can never
    collide on a filename.

    Returns {role: Path}. Raises ModelArtifactError if ANY file in
    the pair/set can't be resolved -- a partial result is never
    returned.
    """
    bucket = _s3_bucket()

    if bucket is None:
        # --- Local-dev path: identical behavior to before this file existed ---
        local_dir = Path(local_dir)
        paths = {role: local_dir / fname for role, fname in filename_by_role.items()}
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            raise ModelArtifactError(
                f"model artifact file(s) not found locally for key={key!r}: {missing} "
                "(MODEL_ARTIFACT_S3_BUCKET is not set, so this resolved in local-dev "
                "mode and looked only under the given local directory)."
            )
        return paths

    # --- Deployed path: /tmp cache, then S3 on a miss ---
    cache_dir = _TMP_CACHE_ROOT / cache_subdir
    cache_dir.mkdir(parents=True, exist_ok=True)

    prefix = _s3_prefix()
    resolved: dict[str, Path] = {}
    for role, fname in filename_by_role.items():
        cached_path = cache_dir / fname
        if cached_path.exists():
            logger.info("model artifact cache hit: %s", cached_path)
            resolved[role] = cached_path
            continue

        s3_key = f"{prefix}{fname}"
        logger.info("model artifact cache miss -- downloading s3://%s/%s", bucket, s3_key)
        try:
            import boto3
            from botocore.exceptions import ClientError, BotoCoreError

            s3 = boto3.client("s3")
            # Download to a hidden temp name first, then rename onto the
            # real cache filename -- rename is effectively atomic on the
            # same filesystem, so a crash mid-download can never leave a
            # half-written file sitting under a name that looks cached.
            tmp_download_path = cache_dir / f".{fname}.downloading"
            s3.download_file(bucket, s3_key, str(tmp_download_path))
            tmp_download_path.replace(cached_path)
        except (ClientError, BotoCoreError) as e:
            raise ModelArtifactError(
                f"failed to download model artifact from s3://{bucket}/{s3_key} "
                f"for key={key!r}: {e}"
            ) from e

        resolved[role] = cached_path

    return resolved
