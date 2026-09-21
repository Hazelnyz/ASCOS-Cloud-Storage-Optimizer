############################################################
# ASCOS — Compute Layer (Lambda) — Stage 5 Scaffolding
#
# REQUIRES: the "archive" provider (hashicorp/archive) must be
# added to versions.tf's required_providers block before this
# file will work:
#
#   archive = {
#     source  = "hashicorp/archive"
#     version = "~> 2.0"
#   }
#
# SCOPE (master reference §33 Stage 5):
#   Six Lambda functions, per the master reference's exact list:
#   tier-change-fn, forecast-fn, prediction-fn, anomaly-scorer-fn,
#   feedback-writer-fn, training-orchestrator-fn. No PostConfirmation
#   trigger — lazy provisioning was chosen instead (Stage 2).
#
# WHAT THIS STAGE IS AND IS NOT:
#   This is real, deployed AWS infrastructure — not placeholder
#   config. Each function actually runs, actually logs to
#   CloudWatch, and actually holds the exact IAM permissions it
#   currently has a cited, spec-justified reason to hold. What
#   this stage deliberately does NOT contain is business logic that
#   depends on components that don't exist yet (the ML model,
#   the anomaly-scoring algorithm, the bandit/policy engine — all
#   Stage 10). Each handler honestly returns a 200 "stage5_scaffold"
#   response with an explanation, rather than faking logic that
#   would just be rewritten later.
#
# LEAST PRIVILEGE — THE RULE FOLLOWED THROUGHOUT THIS FILE:
#   A permission is granted here ONLY if a specific section of the
#   master reference or ML schema directly names this function as
#   needing it NOW, AND the exact IAM action is verified against
#   official AWS documentation rather than inferred from an API
#   operation's name (S3's CopyObject is a real example of where
#   that inference would have been wrong — see tier-change-fn below
#   for the citation). "This function will probably need X
#   eventually" is explicitly NOT a justification — that permission
#   gets added in the stage that actually implements the logic
#   needing it. Where the master reference is silent on a function's
#   exact data flow (forecast-fn, prediction-fn's DynamoDB access,
#   feedback-writer-fn's predictions lookup), no permission is
#   granted yet, and the ambiguity is documented rather than
#   resolved by assumption.
#
# ONE EXECUTION ROLE PER FUNCTION:
#   No shared Lambda execution role, and these roles are never the
#   same as the human infra-manager IAM identities in iam-team.tf.
#
# CLOUDWATCH LOGS — TWO DELIBERATE DESIGN CHOICES:
#   1. logs:CreateLogGroup is scoped one level broader
#      (region:account:*) than logs:CreateLogStream/PutLogEvents
#      (scoped to the specific function's log group). This follows
#      AWS's own troubleshooting guidance ("Resolve 'Log group does
#      not exist' errors for Lambda logs") — CreateLogGroup is the
#      action that creates the group in the first place, so scoping
#      it to a not-yet-existent specific log-group ARN is a known
#      source of that exact error.
#   2. Each function's log group is created explicitly as its own
#      aws_cloudwatch_log_group resource with a 14-day retention
#      period, rather than left to Lambda's implicit default
#      (indefinite retention). Indefinite retention has a small but
#      real, avoidable cost and housekeeping implication over a
#      multi-month project — this is a genuine improvement, not
#      required by any spec section, added because it's cheap and
#      has no downside.
#
# ENVIRONMENT VARIABLES:
#   Added only for resources a function currently has real IAM
#   permission to access — not speculatively for future
#   responsibilities. This lets later stages read configuration
#   (table names, bucket name) via os.environ instead of hardcoding
#   them into business logic when it's eventually written.
############################################################

# Shared trust policy — every Lambda execution role trusts the
# Lambda service to assume it. This is identical across all six
# functions and isn't itself a data-access permission, so sharing
# this one data source doesn't violate the per-function-role rule.
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

############################################################
# 1. tier-change-fn
#
# Justified permissions (master reference §15, §16, §5 Step 1):
#   - S3 app bucket: s3:GetObject + s3:PutObject are the officially
#     documented requirement for CopyObject (source read +
#     destination write) per AWS's CopyObject API reference.
#     s3:PutObject also covers the entire multipart copy chain
#     (CreateMultipartUpload/UploadPartCopy/CompleteMultipartUpload
#     all map to s3:PutObject). s3:AbortMultipartUpload,
#     s3:ListMultipartUploadParts, and s3:ListBucketMultipartUploads
#     cover cleanup/listing for that same multipart flow, per §16.
#     s3:CopyObject and s3:RestoreObject are deliberately NOT
#     included — see the inline policy comment below for why both
#     were considered and rejected on evidence, not assumption.
#   - protected_files: GetItem — the hard-gate check required
#     before any automated tier action (§5 Step 1).
############################################################

data "archive_file" "tier_change_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/tier-change-fn/handler.py"
  output_path = "${path.module}/../backend/tier-change-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "tier_change_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-tier-change-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "tier_change_fn" {
  name               = "${var.project_name}-${var.environment}-tier-change-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "tier_change_fn" {
  name = "tier-change-fn-policy"
  role = aws_iam_role.tier_change_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3TierChangeOperations"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
      },
      {
        Sid      = "S3ListInProgressMultipartUploads"
        Effect   = "Allow"
        Action   = ["s3:ListBucketMultipartUploads"]
        Resource = aws_s3_bucket.app_storage.arn
      },
      {
        Sid      = "ProtectedFilesHardGateCheck"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = aws_dynamodb_table.protected_files.arn
      },
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.tier_change_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "tier_change_fn" {
  function_name    = "${var.project_name}-${var.environment}-tier-change-fn"
  filename         = data.archive_file.tier_change_fn.output_path
  source_code_hash = data.archive_file.tier_change_fn.output_base64sha256
  role             = aws_iam_role.tier_change_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 60

  environment {
    variables = {
      ENVIRONMENT           = var.environment
      PROJECT_NAME          = var.project_name
      S3_BUCKET_NAME        = aws_s3_bucket.app_storage.bucket
      PROTECTED_FILES_TABLE = aws_dynamodb_table.protected_files.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.tier_change_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}

############################################################
# 2. forecast-fn
#
# No DynamoDB/S3 permissions granted yet — the master reference
# (§25) does not specify whether this function reads access_event
# directly or receives pre-computed inputs from its caller. That
# data-flow question is deferred to Stage 6/7; granting read access
# now would be a guess, not a cited requirement.
############################################################

data "archive_file" "forecast_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/forecast-fn/handler.py"
  output_path = "${path.module}/../backend/forecast-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "forecast_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-forecast-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "forecast_fn" {
  name               = "${var.project_name}-${var.environment}-forecast-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "forecast_fn" {
  name = "forecast-fn-policy"
  role = aws_iam_role.forecast_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.forecast_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "forecast_fn" {
  function_name    = "${var.project_name}-${var.environment}-forecast-fn"
  filename         = data.archive_file.forecast_fn.output_path
  source_code_hash = data.archive_file.forecast_fn.output_base64sha256
  role             = aws_iam_role.forecast_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT  = var.environment
      PROJECT_NAME = var.project_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.forecast_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}

############################################################
# 3. prediction-fn
#
# No DynamoDB permissions granted yet. The eventual feature-
# engineering/inference logic (ML schema §2, §4) needs access_event,
# user_baseline, and predictions — but that logic doesn't exist
# until Stage 10, so granting the access now would not be justified
# by any current implementation.
############################################################

data "archive_file" "prediction_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/prediction-fn/handler.py"
  output_path = "${path.module}/../backend/prediction-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "prediction_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-prediction-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "prediction_fn" {
  name               = "${var.project_name}-${var.environment}-prediction-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "prediction_fn" {
  name = "prediction-fn-policy"
  role = aws_iam_role.prediction_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.prediction_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "prediction_fn" {
  function_name    = "${var.project_name}-${var.environment}-prediction-fn"
  filename         = data.archive_file.prediction_fn.output_path
  source_code_hash = data.archive_file.prediction_fn.output_base64sha256
  role             = aws_iam_role.prediction_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      ENVIRONMENT  = var.environment
      PROJECT_NAME = var.project_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.prediction_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}

############################################################
# 4. anomaly-scorer-fn
#
# Justified permissions (master reference §19):
#   - security_state: GetItem/PutItem/DeleteItem — §19 directly and
#     explicitly names this table/Lambda relationship as the
#     containment mechanism ("DynamoDB security state -> Lambda
#     authorization check on every request -> deny/contain future
#     actions"). This is cited architecture, not a guess.
#   No access_event/user_baseline permissions yet — the actual
#   Isolation Forest scoring logic (ML schema §7) that would read
#   those tables doesn't exist until the security/anomaly-detection
#   implementation stage.
#
# STAGE 7.6 ADDITION: sns:Publish on admin_alerts (sns.tf), and the
#   corresponding SNS_TOPIC_ARN env var below. This makes the
#   handler's dormant _publish_alert path (Stage 7.4) functional
#   IF Stage 10 ever activates it — the Stage 7 handler itself never
#   calls it, so this permission sits unused today by design.
############################################################

data "archive_file" "anomaly_scorer_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/anomaly-scorer-fn/handler.py"
  output_path = "${path.module}/../backend/anomaly-scorer-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "anomaly_scorer_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-anomaly-scorer-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "anomaly_scorer_fn" {
  name               = "${var.project_name}-${var.environment}-anomaly-scorer-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# --- CHANGED: added the PublishAdminAlerts statement below ---
resource "aws_iam_role_policy" "anomaly_scorer_fn" {
  name = "anomaly-scorer-fn-policy"
  role = aws_iam_role.anomaly_scorer_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecurityStateContainment"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = aws_dynamodb_table.security_state.arn
      },
      {
        Sid      = "PublishAdminAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.admin_alerts.arn
      },
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.anomaly_scorer_fn.arn}:*"
      },
    ]
  })
}

# --- CHANGED: added SNS_TOPIC_ARN below ---
resource "aws_lambda_function" "anomaly_scorer_fn" {
  function_name    = "${var.project_name}-${var.environment}-anomaly-scorer-fn"
  filename         = data.archive_file.anomaly_scorer_fn.output_path
  source_code_hash = data.archive_file.anomaly_scorer_fn.output_base64sha256
  role             = aws_iam_role.anomaly_scorer_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      ENVIRONMENT          = var.environment
      PROJECT_NAME         = var.project_name
      SECURITY_STATE_TABLE = aws_dynamodb_table.security_state.name
      SNS_TOPIC_ARN        = aws_sns_topic.admin_alerts.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.anomaly_scorer_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}

############################################################
# 5. feedback-writer-fn
#
# Justified permission (ML schema §6):
#   - feedback: PutItem only — this function's one named purpose.
#   No predictions:GetItem — the master reference does not specify
#   whether this function looks up prediction context itself or
#   receives it already supplied by the caller. Deferred to Stage
#   6/7; will only be added if the actual wiring justifies it.
############################################################

data "archive_file" "feedback_writer_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/feedback-writer-fn/handler.py"
  output_path = "${path.module}/../backend/feedback-writer-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "feedback_writer_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-feedback-writer-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "feedback_writer_fn" {
  name               = "${var.project_name}-${var.environment}-feedback-writer-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "feedback_writer_fn" {
  name = "feedback-writer-fn-policy"
  role = aws_iam_role.feedback_writer_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "FeedbackWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.feedback.arn
      },
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.feedback_writer_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "feedback_writer_fn" {
  function_name    = "${var.project_name}-${var.environment}-feedback-writer-fn"
  filename         = data.archive_file.feedback_writer_fn.output_path
  source_code_hash = data.archive_file.feedback_writer_fn.output_base64sha256
  role             = aws_iam_role.feedback_writer_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT    = var.environment
      PROJECT_NAME   = var.project_name
      FEEDBACK_TABLE = aws_dynamodb_table.feedback.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.feedback_writer_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}

############################################################
# 6. training-orchestrator-fn
#
# ML schema §8 is explicit that heavy training must NOT run inside
# a request-serving Lambda — this function's real job is only to
# trigger a scheduled EC2/Fargate training run. That training
# pipeline doesn't exist until Stage 10, so there is nothing real
# to orchestrate yet. No permissions beyond logging are justified.
############################################################

data "archive_file" "training_orchestrator_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/training-orchestrator-fn/handler.py"
  output_path = "${path.module}/../backend/training-orchestrator-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "training_orchestrator_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-training-orchestrator-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "training_orchestrator_fn" {
  name               = "${var.project_name}-${var.environment}-training-orchestrator-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "training_orchestrator_fn" {
  name = "training-orchestrator-fn-policy"
  role = aws_iam_role.training_orchestrator_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LogGroupCreation"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.training_orchestrator_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "training_orchestrator_fn" {
  function_name    = "${var.project_name}-${var.environment}-training-orchestrator-fn"
  filename         = data.archive_file.training_orchestrator_fn.output_path
  source_code_hash = data.archive_file.training_orchestrator_fn.output_base64sha256
  role             = aws_iam_role.training_orchestrator_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT  = var.environment
      PROJECT_NAME = var.project_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.training_orchestrator_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage5-scaffolding"
  }
}