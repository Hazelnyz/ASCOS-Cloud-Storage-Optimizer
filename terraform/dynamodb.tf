############################################################
# ASCOS — Data Layer (DynamoDB)
#
# SCOPE:
#   Six separate logical tables, per master reference §24 —
#   "don't collapse all of these into one unstructured table
#   just because they're all DynamoDB." Each table's key design
#   below was derived from its actual read/write access patterns
#   (which Lambda/UI feature needs which query), not chosen
#   arbitrarily. Full design discussion: docs/AWS_SETUP_LOG.md.
#
# BILLING MODE:
#   PAY_PER_REQUEST on every table. At this project's scale
#   (~5-10 users), provisioned throughput would mean paying for
#   capacity that mostly sits idle. Pay-per-request avoids paying
#   for provisioned capacity while the tables are mostly idle —
#   the right default until real traffic patterns justify
#   switching a specific table to provisioned capacity.
# WHAT THIS FILE DOES NOT DO:
#   No GSIs were added "for completeness" or because a table
#   technically could have one. Every GSI here maps to a named,
#   specific access pattern from the master reference or ML
#   schema. Batch/analytical consumers (LightGBM retraining,
#   §11 evaluation metrics) do NOT shape these key designs —
#   those are served by bulk/time-bounded scans or offline
#   export, not by adding operational GSIs.
############################################################

############################################################
# 1. access_event
#
# The append-only raw event log (ML schema §1) — everything
# else in the ML pipeline derives from this table.
#
# PK: user_id
#   Every core feature-engineering query (ML schema §2) is
#   scoped per-user: "this user's access history, at-or-before
#   snapshot time T." Also serves the anomaly detector's
#   short-window queries (§7) — same partition, just a tighter
#   SK time-range filter, no file-level GSI needed for that case.
#
# SK: timestamp#event_id
#   Composite for two reasons: (1) preserves chronological sort
#   order via the timestamp prefix, (2) timestamp alone isn't
#   guaranteed unique — two events can land in the same
#   millisecond — so event_id is appended as a tiebreaker.
#
# GSI-1 (user-file-index): user_id#file_id / timestamp#event_id
#   Serves per-(user,file) feature queries (days_since_last_
#   access, access_count_7d/30d/90d, access_hour_consistency —
#   ML schema §2). Partition key is user_id#file_id, NOT plain
#   file_id, specifically to avoid a hot-partition risk on
#   popular files — nothing in the ML schema ever needs
#   "who accessed file X across all users," so file_id alone
#   would add risk with no corresponding benefit.
#
# co_access_signal (ML schema §2) deliberately has NO dedicated
# index. It's computed by querying a time-window slice of the
# user's full event stream on the primary table — the schema
# itself flags this feature as "not assumed predictive by
# default," so a speculative GSI isn't justified yet. GSIs can
# be added later without recreating the table if ablation
# testing proves it's needed.
############################################################

resource "aws_dynamodb_table" "access_event" {
  name         = "${var.project_name}-${var.environment}-access-event"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "timestamp_event_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "timestamp_event_id"
    type = "S"
  }

  attribute {
    name = "user_id_file_id"
    type = "S"
  }

  global_secondary_index {
    name            = "user-file-index"
    hash_key        = "user_id_file_id"
    range_key       = "timestamp_event_id"
    projection_type = "ALL"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "ml-raw-access-event-log"
  }
}

############################################################
# 2. user_baseline
#
# One current baseline record per user — NOT a history log.
# Read by: LightGBM feature engineering (user_avg_daily_
# accesses, ML schema §2), Isolation Forest anomaly detection
# (§7, "trained on that user's own history"), and the absolute-
# activity-floor gate (documented decision below).
#
# PK: user_id, no SK, no GSI. Every real access pattern here is
# "give me this one user's current baseline" — a plain GetItem.
# No cross-user query exists anywhere in the spec for this data,
# so a GSI would add cost/complexity with nothing to serve.
#
# DESIGN NOTE — absolute-activity floor (documented decision,
# not yet implemented, belongs to Stage 7):
#   A purely user-relative anomaly model can flag small absolute
#   jumps as "anomalous" for low-baseline users (e.g. 1 file/day
#   -> 10 files/day reads as 10x relative change even though 10
#   files is trivial in absolute terms). The fix is NOT to gate
#   detection itself — Isolation Forest should still score every
#   event so the system keeps learning/observing. Instead, gate
#   the SEVERITY ESCALATION: only escalate to Medium/High if
#   absolute activity in the relevant window also clears a
#   minimum floor. This table stores both relative statistics
#   AND raw absolute counts so that gate has data to check
#   against. The exact floor value (N) is intentionally left
#   undecided — to be tuned against real usage once Stage 7 is
#   built, not guessed now.
############################################################

resource "aws_dynamodb_table" "user_baseline" {
  name         = "${var.project_name}-${var.environment}-user-baseline"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "ml-anomaly-user-baseline"
  }
}
############################################################
# 3. protected_files
#
# Represents ONLY files under active manual protection — NOT a
# general file-metadata table, and NOT a record of ML-predicted/
# frequently-used files. ML predictions remain fully adaptive;
# only an explicit user pin creates a row here.
#
# PK: user_id, SK: file_id, no GSI.
#   Point check ("is (user, file) protected?") -> GetItem.
#   List check ("this user's protected files") -> Query(user_id).
#   Both served directly by the primary key — no GSI needed.
#
# Deliberately row-exists-means-protected: no protected=false
# rows are ever written. Pin = PutItem, unpin = DeleteItem. This
# keeps the table's size proportional to actual pins, not to the
# entire file population.
#
# DESIGN NOTE — pinning does NOT pause ML observation/learning:
#   A protected_files row blocks ONLY the automated tier-change/
#   bandit execution path (master reference §5 Step 1 hard gate).
#   access_event logging and prediction generation continue
#   completely unaffected for pinned files — they are a separate
#   pipeline from tiering execution. This is what allows a future
#   feature (Stage 9/10, not built yet) where the system notices
#   a pinned file has gone stale and suggests "consider
#   unpinning" — a recommendation only, never an automatic
#   override of the user's explicit protection choice.
############################################################

resource "aws_dynamodb_table" "protected_files" {
  name         = "${var.project_name}-${var.environment}-protected-files"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "file_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "file_id"
    type = "S"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "manual-tier-protection"
  }
}

############################################################
# 4. predictions
#
# Stores the prediction object from ML schema §4 (prediction_id,
# p_access, model_version, candidate_tiers, bandit_choice,
# top_reasons, etc.) — what makes "why did the bandit choose
# Warm here" answerable from one record.
#
# PK: prediction_id (no SK).
#   The dominant external access pattern is feedback storing a
#   reference to its prediction (ML schema §6) — the caller only
#   has prediction_id, not user_id/file_id, so prediction_id
#   alone as PK keeps that lookup a plain GetItem instead of
#   forcing a GSI for the single most common access.
#
# GSI-1 (user-file-index): user_id#file_id / prediction_timestamp
# #prediction_id
#   Serves the "ML Explanation" UI feature (master reference §3)
#   — retrieve the latest prediction for one user's specific file
#   by querying this user's/file's prediction history in
#   descending timestamp order with Limit=1.
#
# GSI-2 (user-index): user_id / prediction_timestamp#prediction_id
#   Serves the "Frequently Used" flow (master reference §12) —
#   this user's recent predictions across all their files.
#
# Both GSIs use INCLUDE projections (only the fields each UI
# feature actually needs), not ALL — no query benefit to
# duplicating every attribute (e.g. full SHAP detail) into both
# indexes, only extra storage/write cost.
#
# §11's evaluation metrics (false-archive rate, override rate by
# context bucket, etc.) are offline/batch analytics and
# deliberately do NOT shape this table's keys, same principle
# applied throughout this file.
############################################################

resource "aws_dynamodb_table" "predictions" {
  name         = "${var.project_name}-${var.environment}-predictions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "prediction_id"

  attribute {
    name = "prediction_id"
    type = "S"
  }

  attribute {
    name = "user_id_file_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "prediction_timestamp_id"
    type = "S"
  }

  global_secondary_index {
    name            = "user-file-index"
    hash_key        = "user_id_file_id"
    range_key       = "prediction_timestamp_id"
    projection_type = "INCLUDE"
    non_key_attributes = [
      "prediction_timestamp", "top_reasons", "candidate_tiers",
      "bandit_choice", "model_version", "p_access"
    ]
  }

  global_secondary_index {
    name            = "user-index"
    hash_key        = "user_id"
    range_key       = "prediction_timestamp_id"
    projection_type = "INCLUDE"
    non_key_attributes = [
      "prediction_timestamp", "file_id", "p_access",
      "candidate_tiers", "bandit_choice"
    ]
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "ml-prediction-records"
  }
}
############################################################
# 5. feedback
#
# Stores the feedback schema from ML schema §6 — closes the
# loop between a recommendation and the user's actual response.
# Never overwrites access_event; adds context on top of it.
#
# PK: feedback_event_id.
#   A globally unique event ID, independent of whether a
#   prediction ends up with exactly one or multiple feedback
#   events over its lifetime — this design is correct either
#   way, so it doesn't depend on that being resolved.
#
# GSI-1 (prediction-index): prediction_id / response_timestamp
# #feedback_event_id
#   Retrieves feedback history for a given prediction —
#   traceability/debugging (prediction_id -> features ->
#   model_version -> SHAP -> policy -> bandit choice -> this
#   feedback row, per ML schema §6). To get the most recent
#   feedback for a prediction, query this GSI in descending
#   timestamp order with Limit=1, same pattern as predictions'
#   GSI-1.
#
# Deliberately NO context GSI (user_id#p_access_bucket#file_type
# #file_age_bucket#current_tier or similar). The bandit's
# learned reward state (ML schema §5 Step 3) should be
# maintained as its own separate operational state, updated
# incrementally per feedback event — NOT reconstructed by
# repeatedly querying raw historical feedback via a monstrous
# composite-context GSI. This table is the durable event/history
# log; the bandit's fast-decision state lives elsewhere.
#
# Bandit context values (p_access_bucket, file_type,
# file_age_bucket, current_tier) are stored directly on each
# feedback record so they don't need to be reconstructed later
# from the predictions table — matches "feedback adds context,
# never overwrites" (master reference §22).
#
# LightGBM retraining reads this table in bulk/time-bounded
# batches (ML schema §6) — batch consumer, doesn't shape keys.
#
# WRITE-TIME NOTE: like access_event's timestamp_event_id and
# predictions' prediction_timestamp_id, response_timestamp_id is
# a single stored string (e.g. "2026-09-05T10:30:00Z#feedback123")
# that the writing Lambda (Stage 5/7) must construct itself
# before PutItem — DynamoDB does not concatenate this for you.
############################################################

resource "aws_dynamodb_table" "feedback" {
  name         = "${var.project_name}-${var.environment}-feedback"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feedback_event_id"

  attribute {
    name = "feedback_event_id"
    type = "S"
  }

  attribute {
    name = "prediction_id"
    type = "S"
  }

  attribute {
    name = "response_timestamp_id"
    type = "S"
  }

  global_secondary_index {
    name            = "prediction-index"
    hash_key        = "prediction_id"
    range_key       = "response_timestamp_id"
    projection_type = "ALL"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "ml-feedback-loop"
  }
}

############################################################
# 6. security_state
#
# Current user-level containment state for the anomaly response
# system (master reference §19). Explicitly NOT a history table —
# historical security events are outside this table's scope and
# will be addressed separately if required by the later
# security/monitoring implementation. This table answers exactly
# one live question.
#
# PK: user_id, no SK, no GSI.
#   §19's own wording is the access pattern: "DynamoDB security
#   state -> Lambda authorization check on EVERY request ->
#   deny/contain future actions." That's a single per-user point
#   lookup on every authenticated request — nothing in §19
#   describes file-level containment, so a user_id#file_id key
#   (considered and rejected) would invent scope the spec never
#   asks for.
#
# Row-exists = contained; row absent = not contained (deleted or
# cleared on expiry/review). No boolean "contained" field is
# stored — with the row-exists pattern, a boolean would be
# redundant at best and a source of drift/ambiguity at worst
# (e.g. a row existing with contained=false would be a
# contradictory state the schema shouldn't even allow).
#
# IMPORTANT SCOPE NOTE: this table is only the DynamoDB piece of
# ASCOS's security architecture, not the whole thing. The full
# containment flow spans Cognito (authentication) + this table
# (current state) + a Lambda authorization check (enforcement,
# Stage 5/6) + CloudTrail/EventBridge (event detection, Stage 7)
# + CloudWatch/SNS (monitoring/alerting, Stage 7) + the anomaly
# scorer (detection logic, Stage 7/10). This table being small is
# intentional good scoping, not an incomplete security design.
############################################################

resource "aws_dynamodb_table" "security_state" {
  name         = "${var.project_name}-${var.environment}-security-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "anomaly-containment-state"
  }
}