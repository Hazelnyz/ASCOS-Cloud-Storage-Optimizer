############################################################
# ASCOS — Stage 7.1/7.2: CloudTrail Log Bucket + Trail
#
# SCOPE (master reference §18, §33 Stage 7, §36):
#   Dedicated bucket for CloudTrail's own log files — kept
#   separate from aws_s3_bucket.app_storage (using the app
#   bucket for its own trail logs would create a self-
#   referential logging loop) and from the Terraform state
#   bucket (bootstrap/, different purpose/lifecycle).
#
# COST NOTE (§36): CloudTrail S3 data-event logging is a real,
#   ongoing cost — this stage exists specifically to make that
#   decision deliberately, not enable it as a default.
#
# RETENTION: no lifecycle expiration yet, deliberately deferred
#   — same reasoning as access_event's retention (§40, open
#   implementation decision). Can be added later without
#   recreating the bucket; can't be undone once objects expire.
#
# FILTERING DECISION: the trail below is scoped to the app
#   bucket's S3 data events but does NOT filter by eventName —
#   CloudTrail stays a complete audit record, including future
#   tier-change CopyObject/RestoreObject calls. Excluding those
#   from the ML training stream happens one layer downstream, in
#   the EventBridge rule (Stage 7.4) — keeping the audit trail
#   complete and keeping ML training data clean are two
#   different goals served at two different layers.
#
# EXPLICIT SCOPE DECISION — MANAGEMENT EVENTS EXCLUDED:
#   This trail defines only an S3 Data-events advanced_event_
#   selector. Once a trail uses advanced_event_selector, there is
#   no separate "management events still log by default" fallback
#   — so this trail deliberately does NOT log management/control-
#   plane events (IAM changes, Cognito config changes, API calls
#   against other services, etc.). This is an intentional Stage 7
#   scope boundary, not an oversight of the selector syntax: the
#   approved Stage 7 blueprint scopes this trail to S3 object-
#   level access events only, feeding the access_event/anomaly
#   pipeline. Account-wide management-event auditing is a
#   different, broader concern than anything Stage 7 was asked to
#   cover, and adding it now would be scope creep, not a bug fix.
#   Revisit explicitly if/when a real requirement for management-
#   event auditing is identified.
############################################################

resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket = "${var.project_name}-${var.environment}-cloudtrail-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "cloudtrail-log-destination"
  }
}

# Object Ownership explicitly set to BucketOwnerEnforced — this
# disables ACLs entirely on the bucket (matches the default for
# all new S3 buckets since April 2023, made explicit here rather
# than left implicit). This is a prerequisite for the bucket
# policy below: under BucketOwnerEnforced, an ACL-based condition
# in a bucket policy is unsatisfiable, since ACLs don't exist.
resource "aws_s3_bucket_ownership_controls" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail_logs" {
  bucket                  = aws_s3_bucket.cloudtrail_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 (AES256) only — bucket_key_enabled is an SSE-KMS-only
# setting and has no effect here, so it's deliberately omitted
# rather than copied from the app bucket's SSE-KMS-shaped pattern.
resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Trail ARN built as a plain string — not a resource reference —
# so this bucket policy applies cleanly even though aws_cloudtrail
# doesn't exist until later in this same file. AWS's own bucket-
# policy requirement only needs the trail's ARN value, not a live
# resource dependency.
locals {
  cloudtrail_name      = "${var.project_name}-${var.environment}-trail"
  cloudtrail_trail_arn = "arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${local.cloudtrail_name}"
}

resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail_logs.arn
        Condition = {
          StringEquals = { "aws:SourceArn" = local.cloudtrail_trail_arn }
        }
      },
      {
        # NOTE: no s3:x-amz-acl condition here. Under
        # BucketOwnerEnforced (aws_s3_bucket_ownership_controls
        # above), ACLs are disabled on this bucket entirely, so an
        # ACL-based policy condition would never be satisfiable —
        # CloudTrail's writes would fail Access Denied. This is
        # the current AWS-recommended bucket policy shape for
        # BucketOwnerEnforced destinations; object ownership
        # (and therefore delivery permission) is governed by the
        # bucket policy's Principal/Action/Resource/SourceArn
        # alone.
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = { "aws:SourceArn" = local.cloudtrail_trail_arn }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.cloudtrail_logs.arn,
          "${aws_s3_bucket.cloudtrail_logs.arn}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

resource "aws_cloudtrail" "main" {
  name                          = local.cloudtrail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  is_multi_region_trail         = false
  include_global_service_events = false
  enable_log_file_validation    = true

  # Scoped to S3 object-level Data events only, on the ASCOS app
  # storage bucket. See the module-level "EXPLICIT SCOPE DECISION"
  # comment above: this deliberately excludes management events —
  # not an oversight, a Stage 7 scope boundary.
  advanced_event_selector {
    name = "S3 object-level events for ASCOS app storage bucket"

    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }
    field_selector {
      field       = "resources.ARN"
      starts_with = ["${aws_s3_bucket.app_storage.arn}/"]
    }
  }

  depends_on = [
    aws_s3_bucket_policy.cloudtrail_logs,
    aws_s3_bucket_ownership_controls.cloudtrail_logs,
  ]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "s3-data-event-audit-trail"
  }
}