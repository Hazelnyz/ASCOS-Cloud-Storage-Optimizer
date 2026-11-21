"""
Synthetic / demo access-event generator for ASCOS ML pipeline development.

*** THIS MODULE PRODUCES SYNTHETIC DATA. IT IS NOT REAL PRODUCTION DATA. ***

Per the master reference, Part 2 §1, `access_event` is:

    event_id, user_id, file_id, event_type, timestamp, source_ip/device_context

with event_type in {read, write, delete, share, download}.

Real ASCOS access events come from CloudTrail S3 data events (read/write/
delete/download) plus application-logged `share` events. Since no real
production data exists yet, this generator simulates a plausible,
reproducible population of users/files/events so the rest of the pipeline
(features, labels, split, and later LightGBM/SHAP/policy) can be built
and tested against *something* concrete.

Reproducibility: every random draw goes through a single
`numpy.random.Generator` seeded once at the top of `generate_synthetic_dataset`.
No other randomness source (e.g. bare `random`, `uuid.uuid4()`, wall-clock
time) is used anywhere in this module, so two calls with the same seed
produce byte-for-byte identical output (see ml/tests/test_synthetic_generator.py).
"""

from __future__ import annotations

import uuid
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.config import RANDOM_SEED, SYNTHETIC_DATA_DISCLAIMER

# --- Simulation constants (demo-data design choices, not spec values) ---

SIM_START_DATE = pd.Timestamp("2026-01-01")
DEFAULT_SIM_DAYS = 210
DEFAULT_N_USERS = 20
DEFAULT_FILES_PER_USER_RANGE = (8, 16)

FILE_TYPES = ["pdf", "docx", "xlsx", "pptx", "png", "csv", "mp4", "txt"]
DIRECTORY_CATEGORIES = ["project_a", "project_b", "personal", "shared", "archive"]
FILE_SIZE_BUCKETS = ["small", "medium", "large"]

# Behavior archetypes assigned to files. Each archetype drives a daily
# access probability (Poisson lambda) and a preferred-hour distribution.
# This is purely a synthetic-data design device to make the demo dataset
# exercise every feature branch (never_accessed, high-consistency access
# hour, bursty acceleration, decay, brand-new files, etc.) -- it has no
# bearing on the actual ML spec.
ARCHETYPES = [
    "hot_daily",
    "warm_weekly",
    "cold_rare",
    "dead_never",
    "bursty",
    "declining",
    "new_arrival",
]
ARCHETYPE_WEIGHTS = np.array([0.15, 0.25, 0.20, 0.10, 0.10, 0.10, 0.10])
ARCHETYPE_WEIGHTS = ARCHETYPE_WEIGHTS / ARCHETYPE_WEIGHTS.sum()


@dataclass
class _FileSim:
    file_id: str
    user_id: str
    archetype: str
    upload_day: int  # integer day offset from SIM_START_DATE
    file_type: str
    file_size_bucket: str
    directory_category: str
    protected_flag: bool


def _new_id(rng: np.random.Generator) -> str:
    """Deterministic-given-rng UUID (avoids unseeded uuid.uuid4())."""
    return str(uuid.UUID(bytes=rng.bytes(16)))


def _archetype_daily_lambda(archetype: str, day_offset_since_upload: int, burst_days: set) -> float:
    """Poisson lambda for ACCESS_EVENTS (read/download) on a given day."""
    if archetype == "hot_daily":
        return 1.4
    if archetype == "warm_weekly":
        return 0.35
    if archetype == "cold_rare":
        return 0.03
    if archetype == "dead_never":
        return 0.0015
    if archetype == "bursty":
        return 3.0 if day_offset_since_upload in burst_days else 0.05
    if archetype == "declining":
        # Starts hot, decays roughly exponentially over ~60 days.
        return max(0.02, 1.2 * (0.965 ** day_offset_since_upload))
    if archetype == "new_arrival":
        return 0.4
    raise ValueError(f"unknown archetype: {archetype}")


def _sample_access_hour(archetype: str, rng: np.random.Generator) -> int:
    """Hour-of-day for an access event. Some archetypes are clockwork
    (low circular variance), others are uniformly random."""
    if archetype in ("hot_daily", "declining"):
        # Strong clockwork pattern: clustered around 9am +/- ~1h.
        hour = int(np.clip(round(rng.normal(loc=9, scale=1.0)), 0, 23))
        return hour
    if archetype == "warm_weekly":
        hour = int(np.clip(round(rng.normal(loc=14, scale=2.5)), 0, 23))
        return hour
    # bursty / cold_rare / dead_never / new_arrival: no consistent timing
    return int(rng.integers(0, 24))


def generate_synthetic_dataset(
    seed: int = RANDOM_SEED,
    n_users: int = DEFAULT_N_USERS,
    files_per_user_range: tuple[int, int] = DEFAULT_FILES_PER_USER_RANGE,
    sim_days: int = DEFAULT_SIM_DAYS,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate a reproducible synthetic ASCOS dataset.

    Returns
    -------
    events_df : pd.DataFrame
        Columns: event_id, user_id, file_id, event_type, timestamp,
        source_ip, device_context.
        This is the raw, append-only `access_event` log per §1.
    file_metadata_df : pd.DataFrame
        Columns: file_id, user_id, upload_date, file_type,
        file_size_bucket, directory_category, current_storage_tier,
        protected_flag, archetype.
        `archetype` is a synthetic-data-only debug column (NOT a model
        feature -- see feature_engineering.py, which never reads it).
        `current_storage_tier` is a static placeholder ("HOT") in this
        phase since tier-change simulation is out of scope for the
        standalone Phase 1 pipeline.

    Determinism
    -----------
    Calling this function twice with the same `seed` (and same other
    arguments) produces identical output, including event_id/file_id/
    user_id UUID strings. See ml/tests/test_synthetic_generator.py.
    """
    if verbose:
        print(f"[synthetic_generator] {SYNTHETIC_DATA_DISCLAIMER}")
    warnings.warn(SYNTHETIC_DATA_DISCLAIMER, category=UserWarning, stacklevel=2)

    rng = np.random.default_rng(seed)

    # --- Users ---
    user_ids = [_new_id(rng) for _ in range(n_users)]

    # --- Files ---
    files: list[_FileSim] = []
    for user_id in user_ids:
        n_files = int(rng.integers(files_per_user_range[0], files_per_user_range[1] + 1))
        for _ in range(n_files):
            archetype = rng.choice(ARCHETYPES, p=ARCHETYPE_WEIGHTS)
            if archetype == "new_arrival":
                # Uploaded near the very end of the simulation window,
                # deliberately so many snapshots will see never_accessed=True.
                upload_day = int(rng.integers(max(sim_days - 10, 0), sim_days))
            else:
                # Uploaded sometime in the first 70% of the window, leaving
                # room for a real access history to accumulate.
                upload_day = int(rng.integers(0, max(int(sim_days * 0.7), 1)))
            files.append(
                _FileSim(
                    file_id=_new_id(rng),
                    user_id=user_id,
                    archetype=str(archetype),
                    upload_day=upload_day,
                    file_type=str(rng.choice(FILE_TYPES)),
                    file_size_bucket=str(rng.choice(FILE_SIZE_BUCKETS)),
                    directory_category=str(rng.choice(DIRECTORY_CATEGORIES)),
                    protected_flag=bool(rng.random() < 0.05),
                )
            )

    # --- Events ---
    event_rows = []

    for f in files:
        # Pick 0-2 short "burst window" day-ranges for bursty archetype.
        burst_days: set[int] = set()
        if f.archetype == "bursty":
            n_bursts = int(rng.integers(1, 3))
            max_start = max(sim_days - f.upload_day - 10, 1)
            for _ in range(n_bursts):
                burst_start = int(rng.integers(0, max_start))
                burst_days.update(range(burst_start, min(burst_start + 5, sim_days - f.upload_day)))

        deleted = False
        # Initial write (creation) event on upload day.
        upload_ts = SIM_START_DATE + pd.Timedelta(
            days=f.upload_day, hours=int(rng.integers(0, 24)), minutes=int(rng.integers(0, 60))
        )
        event_rows.append(
            {
                "event_id": _new_id(rng),
                "user_id": f.user_id,
                "file_id": f.file_id,
                "event_type": "write",
                "timestamp": upload_ts,
                "source_ip": f"10.0.{int(rng.integers(0, 255))}.{int(rng.integers(0, 255))}",
                "device_context": str(rng.choice(["web", "desktop_sync", "mobile"])),
            }
        )

        for day_offset in range(0, sim_days - f.upload_day):
            if deleted:
                break

            # Small chance of a terminal delete event (not for brand-new files).
            if day_offset > 3 and rng.random() < 0.0008:
                del_ts = SIM_START_DATE + pd.Timedelta(
                    days=f.upload_day + day_offset,
                    hours=int(rng.integers(0, 24)),
                )
                event_rows.append(
                    {
                        "event_id": _new_id(rng),
                        "user_id": f.user_id,
                        "file_id": f.file_id,
                        "event_type": "delete",
                        "timestamp": del_ts,
                        "source_ip": f"10.0.{int(rng.integers(0, 255))}.{int(rng.integers(0, 255))}",
                        "device_context": str(rng.choice(["web", "desktop_sync", "mobile"])),
                    }
                )
                deleted = True
                break

            # Occasional edit (write) event.
            if rng.random() < 0.01:
                edit_ts = SIM_START_DATE + pd.Timedelta(
                    days=f.upload_day + day_offset, hours=int(rng.integers(0, 24))
                )
                event_rows.append(
                    {
                        "event_id": _new_id(rng),
                        "user_id": f.user_id,
                        "file_id": f.file_id,
                        "event_type": "write",
                        "timestamp": edit_ts,
                        "source_ip": f"10.0.{int(rng.integers(0, 255))}.{int(rng.integers(0, 255))}",
                        "device_context": str(rng.choice(["web", "desktop_sync", "mobile"])),
                    }
                )

            # ACCESS_EVENTS (read/download) for this day.
            lam = _archetype_daily_lambda(f.archetype, day_offset, burst_days)
            n_access = int(rng.poisson(lam))
            for _ in range(n_access):
                hour = _sample_access_hour(f.archetype, rng)
                minute = int(rng.integers(0, 60))
                ts = SIM_START_DATE + pd.Timedelta(
                    days=f.upload_day + day_offset, hours=hour, minutes=minute
                )
                event_type = "download" if rng.random() < 0.3 else "read"
                event_rows.append(
                    {
                        "event_id": _new_id(rng),
                        "user_id": f.user_id,
                        "file_id": f.file_id,
                        "event_type": event_type,
                        "timestamp": ts,
                        "source_ip": f"10.0.{int(rng.integers(0, 255))}.{int(rng.integers(0, 255))}",
                        "device_context": str(rng.choice(["web", "desktop_sync", "mobile"])),
                    }
                )

            # Occasional share event -- only plausible once the file has
            # some access history (collaboration signal).
            if n_access > 0 and rng.random() < 0.01:
                share_ts = SIM_START_DATE + pd.Timedelta(
                    days=f.upload_day + day_offset, hours=int(rng.integers(0, 24))
                )
                event_rows.append(
                    {
                        "event_id": _new_id(rng),
                        "user_id": f.user_id,
                        "file_id": f.file_id,
                        "event_type": "share",
                        "timestamp": share_ts,
                        "source_ip": f"10.0.{int(rng.integers(0, 255))}.{int(rng.integers(0, 255))}",
                        "device_context": str(rng.choice(["web", "desktop_sync", "mobile"])),
                    }
                )

    events_df = pd.DataFrame(event_rows)
    events_df = events_df.sort_values(["user_id", "file_id", "timestamp"]).reset_index(drop=True)

    file_metadata_df = pd.DataFrame(
        [
            {
                "file_id": f.file_id,
                "user_id": f.user_id,
                "upload_date": SIM_START_DATE + pd.Timedelta(days=f.upload_day),
                "file_type": f.file_type,
                "file_size_bucket": f.file_size_bucket,
                "directory_category": f.directory_category,
                "current_storage_tier": "HOT",  # static placeholder, Phase 1 scope
                "protected_flag": f.protected_flag,
                "archetype": f.archetype,  # DEBUG ONLY -- never fed to the model
            }
            for f in files
        ]
    )

    # Tag both DataFrames as synthetic so downstream code/notebooks can
    # assert on it and nobody accidentally treats this as production data.
    events_df.attrs["data_source"] = "synthetic_demo_data"
    events_df.attrs["disclaimer"] = SYNTHETIC_DATA_DISCLAIMER
    events_df.attrs["seed"] = seed
    file_metadata_df.attrs["data_source"] = "synthetic_demo_data"
    file_metadata_df.attrs["disclaimer"] = SYNTHETIC_DATA_DISCLAIMER
    file_metadata_df.attrs["seed"] = seed

    if verbose:
        print(
            f"[synthetic_generator] generated {len(events_df)} events across "
            f"{len(file_metadata_df)} files / {n_users} users "
            f"(seed={seed}, sim_days={sim_days})"
        )

    return events_df, file_metadata_df


SIM_END_DATE = SIM_START_DATE + pd.Timedelta(days=DEFAULT_SIM_DAYS)


if __name__ == "__main__":
    ev, meta = generate_synthetic_dataset()
    print(ev.head())
    print(meta.head())
