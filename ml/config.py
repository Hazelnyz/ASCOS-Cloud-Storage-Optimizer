"""
Shared configuration constants for the ASCOS ML pipeline.

All values here are taken directly from Part 2 (ML_SCHEMA) of the ASCOS
master project reference. Nothing in this file should be treated as a
free design choice — where the spec gives a starting value ("start with
7 days", "margin = 0.1 (tunable)"), that is preserved as the default here,
not silently changed.
"""

# --- Label horizon (§3) ---
# "Horizon: start with 7 days. Revisit after real data (30 days as
# fallback if 7-day positives are too sparse)."
HORIZON_DAYS = 7

# --- Sliding window snapshot generation (§3) ---
# "for each user, generate one training row every ~3 days from their history"
SNAPSHOT_CADENCE_DAYS = 3

# --- Chronological split embargo (§3) ---
# "Add an embargo/gap at the split boundary at least as long as the
# prediction horizon (7+ days)"
# Kept as its own constant (rather than reusing HORIZON_DAYS directly)
# because the spec frames it as an independent >= constraint, not a
# hard equality -- callers may widen it, but never narrow it below
# HORIZON_DAYS (enforced in splitting/chronological_split.py).
EMBARGO_DAYS = HORIZON_DAYS

# --- Policy engine margin (§5 Step 2) ---
# "margin = 0.1  # tunable"
POLICY_MARGIN = 0.1

# --- Event type universe (§1) ---
# "event_type | enum | read | write | delete | share | download"
ALL_EVENT_TYPES = {"read", "write", "delete", "share", "download"}

# --- ACCESS_EVENTS definition (§1) ---
# "ACCESS_EVENTS = { read, download } -- this is the definition of
# 'access' used consistently by *both* the feature vector (§2) and the
# label (§3)."
ACCESS_EVENTS = {"read", "download"}

# --- co_access_signal window (§2) ---
# Not given a specific number in the spec ("within X minutes of another
# file") -- X is explicitly left as a parameter. Documented here as a
# named, single source of truth rather than a magic number buried in
# feature code.
CO_ACCESS_WINDOW_MINUTES = 15

# --- share_count window (§2) ---
SHARE_COUNT_WINDOW_DAYS = 30

# --- Feature schema version (§4 prediction output: "feature_schema_version") ---
# Bump this if FEATURE_COLUMNS' set/order/semantics ever change, so old
# prediction records stay distinguishable from ones produced under a
# different feature definition.
FEATURE_SCHEMA_VERSION = "v1"

# --- Reproducibility ---
RANDOM_SEED = 42

# --- Synthetic data labeling ---
# Every artifact produced by ml/data/synthetic_generator.py must be
# unambiguously identifiable as non-production demo data. This string
# is attached to generated DataFrames via .attrs and printed whenever
# the generator runs.
SYNTHETIC_DATA_DISCLAIMER = (
    "SYNTHETIC / DEMO DATA -- reproducibly generated for ASCOS ML "
    "pipeline development. This is NOT real user access-event data. "
    "Do not use for production model training or real tier decisions."
)

# --- Anomaly detection constants (§7) ---
# These are starting defaults, not spec values. The ML schema §7
# leaves specific numbers as implementation choices; these are
# reasonable starting points that can be tuned against real data.

# IsolationForest contamination parameter (expected fraction of anomalies)
# Starting default: 0.05 (5% of training data expected to be anomalous)
ANOMALY_CONTAMINATION = 0.05

# Minimum historical snapshots required before training a per-user model
# Below this threshold, the user falls back to the shared global model
# Starting default: 50 snapshots
ANOMALY_MIN_SAMPLES_PER_USER = 50

# Severity percentile thresholds (computed from training score distribution)
# Lower score = more anomalous in sklearn's IsolationForest
# These percentiles define the cutoffs for Medium/High severity
# Starting defaults: 90th percentile for Low/Medium, 95th for Medium/High
ANOMALY_SEVERITY_LOW_MAX_PERCENTILE = 90
ANOMALY_SEVERITY_MEDIUM_MAX_PERCENTILE = 95

# Short rolling windows for anomaly features (reactive, not multi-day)
# Starting defaults: 5 minutes, 1 hour, 24 hours
ANOMALY_WINDOW_5MIN_MINUTES = 5
ANOMALY_WINDOW_1H_HOURS = 1
ANOMALY_WINDOW_24H_HOURS = 24
