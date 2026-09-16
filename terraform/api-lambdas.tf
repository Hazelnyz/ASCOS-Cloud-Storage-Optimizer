############################################################
# ASCOS — Stage 6 File/API Lambda Functions
#
# SCOPE:
#   The 7 new Lambda functions Stage 6 routes need that were NOT
#   part of Stage 5's locked function list (tier-change-fn,
#   forecast-fn, prediction-fn, anomaly-scorer-fn, feedback-
#   writer-fn, training-orchestrator-fn). Those Stage 5 functions
#   are NOT redefined here — api.tf references them directly from
#   lambda.tf.
#
# WHY 7 SEPARATE FUNCTIONS, NOT ONE BUNDLED file-api-fn:
#   Deliberately decided against bundling despite the extra
#   Terraform resources / longer apply time this causes. A bundled
#   function would need the UNION of every route's permissions
#   (list+put+get+delete+access_event write) on one execution role,
#   meaning a bug in any one route handler could reach every
#   permission the bundle holds. Separate functions make that
#   structurally impossible — same least-privilege discipline as
#   Stage 5, chosen deliberately over the smaller/faster apply.
#
# LEAST PRIVILEGE — SAME RULE AS STAGE 5:
#   Every permission below is cited to a specific Stage 6 design
#   decision, not granted speculatively. Notably:
#     - file-list-fn gets ONLY s3:ListBucket. It does NOT get
#       s3:GetObject yet — that's only needed if the eventual
#       implementation calls HeadObject per listed item to read
#       the x-amz-meta-filename metadata (an implementation choice
#       not yet made). Add it then, not now.
#     - access_event:PutItem goes ONLY to file-share-fn. share is
#       the one event type application-logged directly (no S3 API
#       call for CloudTrail to observe) — upload/download/delete
#       get their access_event rows via CloudTrail S3 data events
#       in Stage 7 instead, so those three functions do NOT get
#       this permission.
#
# S3 KEY DESIGN THESE FUNCTIONS RELY ON:
#   S3 key = {user_id}/{file_id} — no filename in the key. Original
#   filename lives in the x-amz-meta-filename object metadata,
#   written by file-upload-url-fn's presigned PUT signature. Every
#   other function constructs this same key directly from the
#   JWT-derived user_id + route fileId — no S3 listing/discovery
#   step needed for download, metadata, delete, share, or (in
#   Stage 5's tier-change-fn) tier changes.
#
# AUTHORIZATION:
#   user_id is ALWAYS derived from the validated Cognito JWT claims
#   passed through by API Gateway — never from client-supplied
#   input. This is enforced in each handler's application logic
#   (master reference §7: "a prefix is an organizational namespace
#   — it is not by itself authorization"), not by IAM alone. IAM
#   scoping below is defense-in-depth on top of that, not a
#   substitute for it.
############################################################

############################################################
# 1. file-list-fn — GET /files
# Permission: s3:ListBucket only (see note above re: s3:GetObject).
############################################################

data "archive_file" "file_list_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-list-fn/handler.py"
  output_path = "${path.module}/../backend/file-list-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_list_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-list-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_list_fn" {
  name               = "${var.project_name}-${var.environment}-file-list-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_list_fn" {
  name = "file-list-fn-policy"
  role = aws_iam_role.file_list_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ListUserFiles"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.app_storage.arn
        # Bucket-level action — this is a list operation, not an
        # object read, so s3:GetObject is NOT granted here.
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
        Resource = "${aws_cloudwatch_log_group.file_list_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_list_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-list-fn"
  filename         = data.archive_file.file_list_fn.output_path
  source_code_hash = data.archive_file.file_list_fn.output_base64sha256
  role             = aws_iam_role.file_list_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT    = var.environment
      PROJECT_NAME   = var.project_name
      S3_BUCKET_NAME = aws_s3_bucket.app_storage.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_list_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 2. file-upload-url-fn — POST /files/upload-url
# Permission: s3:PutObject (required to sign a presigned PUT URL).
############################################################

data "archive_file" "file_upload_url_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-upload-url-fn/handler.py"
  output_path = "${path.module}/../backend/file-upload-url-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_upload_url_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-upload-url-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_upload_url_fn" {
  name               = "${var.project_name}-${var.environment}-file-upload-url-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_upload_url_fn" {
  name = "file-upload-url-fn-policy"
  role = aws_iam_role.file_upload_url_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3PresignedPutSigning"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
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
        Resource = "${aws_cloudwatch_log_group.file_upload_url_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_upload_url_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-upload-url-fn"
  filename         = data.archive_file.file_upload_url_fn.output_path
  source_code_hash = data.archive_file.file_upload_url_fn.output_base64sha256
  role             = aws_iam_role.file_upload_url_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT               = var.environment
      PROJECT_NAME              = var.project_name
      S3_BUCKET_NAME            = aws_s3_bucket.app_storage.bucket
      UPLOAD_URL_EXPIRY_SECONDS = "300" # 5 minutes — locked value
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_upload_url_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 3. file-download-url-fn — GET /files/{fileId}/download-url
# Permission: s3:GetObject (required to sign a presigned GET URL).
############################################################

data "archive_file" "file_download_url_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-download-url-fn/handler.py"
  output_path = "${path.module}/../backend/file-download-url-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_download_url_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-download-url-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_download_url_fn" {
  name               = "${var.project_name}-${var.environment}-file-download-url-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_download_url_fn" {
  name = "file-download-url-fn-policy"
  role = aws_iam_role.file_download_url_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3PresignedGetSigning"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
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
        Resource = "${aws_cloudwatch_log_group.file_download_url_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_download_url_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-download-url-fn"
  filename         = data.archive_file.file_download_url_fn.output_path
  source_code_hash = data.archive_file.file_download_url_fn.output_base64sha256
  role             = aws_iam_role.file_download_url_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT                 = var.environment
      PROJECT_NAME                = var.project_name
      S3_BUCKET_NAME              = aws_s3_bucket.app_storage.bucket
      DOWNLOAD_URL_EXPIRY_SECONDS = "900" # 15 minutes — locked value
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_download_url_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 4. file-metadata-fn — GET /files/{fileId}/metadata
# Permission: s3:GetObject (HeadObject uses this same permission).
############################################################

data "archive_file" "file_metadata_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-metadata-fn/handler.py"
  output_path = "${path.module}/../backend/file-metadata-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_metadata_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-metadata-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_metadata_fn" {
  name               = "${var.project_name}-${var.environment}-file-metadata-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_metadata_fn" {
  name = "file-metadata-fn-policy"
  role = aws_iam_role.file_metadata_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3HeadObject"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
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
        Resource = "${aws_cloudwatch_log_group.file_metadata_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_metadata_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-metadata-fn"
  filename         = data.archive_file.file_metadata_fn.output_path
  source_code_hash = data.archive_file.file_metadata_fn.output_base64sha256
  role             = aws_iam_role.file_metadata_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT    = var.environment
      PROJECT_NAME   = var.project_name
      S3_BUCKET_NAME = aws_s3_bucket.app_storage.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_metadata_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 5. file-delete-fn — DELETE /files/{fileId}
# Permissions: s3:GetObject + s3:DeleteObject.
############################################################

data "archive_file" "file_delete_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-delete-fn/handler.py"
  output_path = "${path.module}/../backend/file-delete-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_delete_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-delete-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_delete_fn" {
  name               = "${var.project_name}-${var.environment}-file-delete-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_delete_fn" {
  name = "file-delete-fn-policy"
  role = aws_iam_role.file_delete_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3DeleteObject"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
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
        Resource = "${aws_cloudwatch_log_group.file_delete_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_delete_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-delete-fn"
  filename         = data.archive_file.file_delete_fn.output_path
  source_code_hash = data.archive_file.file_delete_fn.output_base64sha256
  role             = aws_iam_role.file_delete_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT    = var.environment
      PROJECT_NAME   = var.project_name
      S3_BUCKET_NAME = aws_s3_bucket.app_storage.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_delete_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 6. file-share-fn — POST /files/{fileId}/share-url
# Permissions: s3:GetObject (presigned GET signing) +
# access_event:PutItem (share is application-logged directly,
# per ML schema §1 — no S3 API call for CloudTrail to observe).
############################################################

data "archive_file" "file_share_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/file-share-fn/handler.py"
  output_path = "${path.module}/../backend/file-share-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "file_share_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-file-share-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "file_share_fn" {
  name               = "${var.project_name}-${var.environment}-file-share-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "file_share_fn" {
  name = "file-share-fn-policy"
  role = aws_iam_role.file_share_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3PresignedGetSigning"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*"
      },
      {
        Sid      = "AccessEventShareWrite"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.access_event.arn
        # Deliberately the ONLY new-Lambda role with access_event
        # write access. Upload/download/delete do NOT get this —
        # those event types arrive via CloudTrail S3 data events
        # (Stage 7), not direct Lambda writes.
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
        Resource = "${aws_cloudwatch_log_group.file_share_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "file_share_fn" {
  function_name    = "${var.project_name}-${var.environment}-file-share-fn"
  filename         = data.archive_file.file_share_fn.output_path
  source_code_hash = data.archive_file.file_share_fn.output_base64sha256
  role             = aws_iam_role.file_share_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT              = var.environment
      PROJECT_NAME             = var.project_name
      S3_BUCKET_NAME           = aws_s3_bucket.app_storage.bucket
      ACCESS_EVENT_TABLE       = aws_dynamodb_table.access_event.name
      SHARE_URL_EXPIRY_SECONDS = "86400" # 24 HOURS — not minutes
    }
  }

  depends_on = [aws_cloudwatch_log_group.file_share_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# 7. frequently-used-fn — GET /files/frequently-used
# Permission: dynamodb:Query on predictions (table + user-index GSI).
############################################################

data "archive_file" "frequently_used_fn" {
  type        = "zip"
  source_file = "${path.module}/../backend/frequently-used-fn/handler.py"
  output_path = "${path.module}/../backend/frequently-used-fn/handler.zip"
}

resource "aws_cloudwatch_log_group" "frequently_used_fn" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-frequently-used-fn"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "frequently_used_fn" {
  name               = "${var.project_name}-${var.environment}-frequently-used-fn-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "frequently_used_fn" {
  name = "frequently-used-fn-policy"
  role = aws_iam_role.frequently_used_fn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PredictionsUserIndexQuery"
        Effect = "Allow"
        Action = ["dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.predictions.arn,
          "${aws_dynamodb_table.predictions.arn}/index/user-index",
        ]
        # Query on a GSI requires both the table ARN and the
        # index ARN to be listed as resources.
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
        Resource = "${aws_cloudwatch_log_group.frequently_used_fn.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "frequently_used_fn" {
  function_name    = "${var.project_name}-${var.environment}-frequently-used-fn"
  filename         = data.archive_file.frequently_used_fn.output_path
  source_code_hash = data.archive_file.frequently_used_fn.output_base64sha256
  role             = aws_iam_role.frequently_used_fn.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT       = var.environment
      PROJECT_NAME      = var.project_name
      PREDICTIONS_TABLE = aws_dynamodb_table.predictions.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.frequently_used_fn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}
