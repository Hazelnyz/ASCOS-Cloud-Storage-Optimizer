############################################################
# Storage preferences API Lambda
############################################################

data "archive_file" "storage_preferences_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/storage-preferences-fn/handler.py"
  output_path = "${path.module}/../backend/storage-preferences-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "storage_preferences_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-storage-preferences-fn"
  retention_in_days = 14
  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role" "storage_preferences_fn" {
  name               = "${var.project_name}-${var.environment}-storage-preferences-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy" "storage_preferences_fn" {
  name = "storage-preferences-fn-policy"
  role = aws_iam_role.storage_preferences_fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "StoragePreferencesReadWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.storage_preferences.arn
      },
      {
        Sid      = "ScopedLogStreamWrite"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.storage_preferences_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "storage_preferences_fn" {
  function_name    = "${var.project_name}-${var.environment}-storage-preferences-fn"
  filename         = data.archive_file.storage_preferences_fn.output_path
  source_code_hash = data.archive_file.storage_preferences_fn.output_base64sha256
  role             = aws_iam_role.storage_preferences_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT               = var.environment
      PROJECT_NAME              = var.project_name
      STORAGE_PREFERENCES_TABLE = aws_dynamodb_table.storage_preferences.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.storage_preferences_fn]
  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
  }
}
