############################################################
# ASCOS — Stage 7.3: Access Event Writer Lambda
#
# SCOPE (master reference §22, §23; ML schema §1):
#   Single-purpose Lambda: writes CloudTrail-derived S3 data
#   events into access_event, the authoritative raw log Stage 10
#   trains on. Deliberately separate from anomaly-scorer-fn —
#   recording raw history and scoring anomalies are different
#   responsibilities with different IAM needs (§19: "single-
#   purpose, least-privilege functions were chosen deliberately").
#
# ATTRIBUTION: user_id/file_id recovered from the S3 key prefix
#   ({user_id}/{file_id}, locked Stage 6 design) — never from
#   CloudTrail's userIdentity, which reflects the Lambda
#   execution role that signed the presigned URL, not the end
#   user (§4).
#
# IDEMPOTENCY: CloudTrail's own eventID is reused as event_id;
#   the write is conditional on the composite sort key not
#   already existing, so at-least-once delivery never
#   double-counts.
#
# DLQ (Stage 7.5, sqs.tf): a lost invocation here is a permanent,
#   silent hole in the ML training dataset — sqs:SendMessage
#   below lets Lambda's async-invoke failure destination actually
#   deliver to that queue.
############################################################

data "archive_file" "access_event_writer_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/access-event-writer-fn/handler.py"
  output_path = "${path.module}/../backend/access-event-writer-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "access_event_writer_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-access-event-writer-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "access_event_writer_fn" {
  name               = "${var.project_name}-${var.environment}-access-event-writer-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "access_event_writer_fn" {
  name = "access-event-writer-fn-policy"
  role = aws_iam_role.access_event_writer_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AccessEventWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.access_event.arn
      },
      {
        Sid      = "SendToDLQ"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.access_event_writer_dlq.arn
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
        Resource = "${aws_cloudwatch_log_group.access_event_writer_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "access_event_writer_fn" {
  function_name    = "${var.project_name}-${var.environment}-access-event-writer-fn"
  filename         = data.archive_file.access_event_writer_fn.output_path
  source_code_hash = data.archive_file.access_event_writer_fn.output_base64sha256
  role             = aws_iam_role.access_event_writer_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT        = var.environment
      PROJECT_NAME       = var.project_name
      ACCESS_EVENT_TABLE = aws_dynamodb_table.access_event.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.access_event_writer_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage7-access-event-ingestion"
  }
}