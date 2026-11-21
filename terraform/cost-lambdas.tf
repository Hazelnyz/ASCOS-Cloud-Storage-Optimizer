############################################################
# ASCOS — Cost & Budget Lambda Functions
#
# SCOPE:
#   Two new Lambda functions for per-user cost estimation and
#   budget management. Single-purpose, least-privilege IAM roles.
#
# PRICING:
#   All rates are configured via Terraform variables and passed
#   as Lambda environment variables. Nothing is hardcoded in the
#   handler code. Rates marked as "unverified for ap-south-1" are
#   us-east-1 values used as approximations.
############################################################

############################################################
# 1. cost-summary-fn — GET /cost/summary
# Permission: s3:ListBucket (with prefix restriction) +
# dynamodb:Query (access_event, user_budgets)
#
# S3: ListObjectsV2 with prefix={user_id}/ to get size and
# StorageClass for all objects in the user's prefix. No GetObject
# needed — ListObjectsV2 returns size and StorageClass directly.
#
# DynamoDB: Query access_event by user_id + month prefix on
# timestamp_event_id to count requests (no scans). Query
# user_budgets to read the user's budget.
############################################################

data "archive_file" "cost_summary_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/cost-summary-fn/handler.py"
  output_path = "${path.module}/../backend/cost-summary-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "cost_summary_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-cost-summary-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "cost_summary_fn" {
  name               = "${var.project_name}-${var.environment}-cost-summary-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "cost_summary_fn" {
  name = "cost-summary-fn-policy"
  role = aws_iam_role.cost_summary_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ListUserPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.app_storage.arn
        Condition = {
          StringLike = { "s3:prefix" = ["?*/"] }
        }
      },
      {
        Sid      = "AccessEventQuery"
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = aws_dynamodb_table.access_event.arn
      },
      {
        Sid      = "UserBudgetsRead"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = aws_dynamodb_table.user_budgets.arn
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.cost_summary_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "cost_summary_fn" {
  function_name    = "${var.project_name}-${var.environment}-cost-summary-fn"
  filename         = data.archive_file.cost_summary_fn.output_path
  source_code_hash = data.archive_file.cost_summary_fn.output_base64sha256
  role             = aws_iam_role.cost_summary_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      ENVIRONMENT        = var.environment
      PROJECT_NAME       = var.project_name
      S3_BUCKET_NAME     = aws_s3_bucket.app_storage.bucket
      ACCESS_EVENT_TABLE = aws_dynamodb_table.access_event.name
      USER_BUDGETS_TABLE = aws_dynamodb_table.user_budgets.name
      # Storage rates (per GB-month, ap-south-1)
      STORAGE_RATE_HOT  = var.storage_rate_hot
      STORAGE_RATE_WARM = var.storage_rate_warm
      STORAGE_RATE_COLD = var.storage_rate_cold
      # Request rates (per 1,000 requests)
      REQUEST_RATE_STANDARD_WRITE = var.request_rate_standard_write
      REQUEST_RATE_STANDARD_READ  = var.request_rate_standard_read
      REQUEST_RATE_WARM_WRITE     = var.request_rate_warm_write
      REQUEST_RATE_WARM_READ      = var.request_rate_warm_read
      REQUEST_RATE_COLD_WRITE     = var.request_rate_cold_write
      REQUEST_RATE_COLD_READ      = var.request_rate_cold_read
      REQUEST_RATE_DELETE         = var.request_rate_delete
      # Retrieval rates (per GB)
      RETRIEVAL_RATE_WARM = var.retrieval_rate_warm
      RETRIEVAL_RATE_COLD = var.retrieval_rate_cold
      # Shared overhead (fixed monthly amount)
      SHARED_OVERHEAD_MONTHLY = var.shared_overhead_monthly
      BUDGET_MIN              = var.budget_min
      BUDGET_MAX              = var.budget_max
      BUDGET_STEP             = var.budget_step
      ALERT_THRESHOLD_MIN     = var.alert_threshold_min
      ALERT_THRESHOLD_MAX     = var.alert_threshold_max
    }
  }

  depends_on = [aws_cloudwatch_log_group.cost_summary_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "cost-estimation"
  }
}

############################################################
# 2. cost-budget-fn — PUT /cost/budget
# Permission: dynamodb:PutItem (user_budgets)
#
# DynamoDB: PutItem to save/update user's budget and alert
# threshold. No UpdateItem needed — PutItem overwrites.
############################################################

data "archive_file" "cost_budget_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/cost-budget-fn/handler.py"
  output_path = "${path.module}/../backend/cost-budget-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "cost_budget_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-cost-budget-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "cost_budget_fn" {
  name               = "${var.project_name}-${var.environment}-cost-budget-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "cost_budget_fn" {
  name = "cost-budget-fn-policy"
  role = aws_iam_role.cost_budget_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "UserBudgetsWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.user_budgets.arn
      },
      {
        Sid    = "ScopedLogStreamWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.cost_budget_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "cost_budget_fn" {
  function_name    = "${var.project_name}-${var.environment}-cost-budget-fn"
  filename         = data.archive_file.cost_budget_fn.output_path
  source_code_hash = data.archive_file.cost_budget_fn.output_base64sha256
  role             = aws_iam_role.cost_budget_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT         = var.environment
      PROJECT_NAME        = var.project_name
      USER_BUDGETS_TABLE  = aws_dynamodb_table.user_budgets.name
      BUDGET_MIN          = var.budget_min
      BUDGET_MAX          = var.budget_max
      BUDGET_STEP         = var.budget_step
      ALERT_THRESHOLD_MIN = var.alert_threshold_min
      ALERT_THRESHOLD_MAX = var.alert_threshold_max
    }
  }

  depends_on = [aws_cloudwatch_log_group.cost_budget_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "budget-management"
  }
}
