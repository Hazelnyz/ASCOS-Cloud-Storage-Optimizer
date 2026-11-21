############################################################
# Phase 1 ML worker: SQS + one optional EC2 batch inference worker.
# The documented serving deviation is EC2 rather than ONNX in a
# Lambda zip because the current inference stack uses LightGBM,
# SHAP, and pandas.
############################################################

variable "ml_worker_enabled" {
  description = "Create one EC2 ML queue worker. Set false to omit the instance."
  type        = bool
  default     = true
}

variable "ml_worker_instance_type" {
  description = "EC2 type for the ML inference worker; keep architecture aligned with ml_worker_architecture."
  type        = string
  default     = "t4g.medium"
}

variable "ml_worker_architecture" {
  description = "Amazon Linux 2023 AMI architecture: arm64 or x86_64. Must match ml_worker_instance_type."
  type        = string
  default     = "arm64"
  validation {
    condition     = contains(["arm64", "x86_64"], var.ml_worker_architecture)
    error_message = "ml_worker_architecture must be arm64 or x86_64."
  }
}

variable "ml_worker_artifact_key" {
  description = "Object key of the versioned worker code and model ZIP uploaded to the private artifact bucket."
  type        = string
  default     = "ml-worker/worker-release.zip"
  validation {
    condition     = length(var.ml_worker_artifact_key) > 0 && !startswith(var.ml_worker_artifact_key, "/")
    error_message = "ml_worker_artifact_key must be a non-empty relative S3 key."
  }
}

variable "ml_worker_model_version" {
  description = "Pinned model version to load from the worker artifact's ml/models directory."
  type        = string
  default     = "ascos-lgbm-demo-20260924T100028Z-seed42"
}

variable "ml_worker_visibility_timeout_seconds" {
  description = "Initial SQS visibility timeout; worker heartbeats extend active tasks. SQS supports at most 12 hours."
  type        = number
  default     = 900
  validation {
    condition     = var.ml_worker_visibility_timeout_seconds >= 60 && var.ml_worker_visibility_timeout_seconds <= 43200
    error_message = "ML worker visibility timeout must be between 60 seconds and 12 hours."
  }
}

variable "ml_worker_instance_subnet_index" {
  description = "Index of the default-VPC default subnet selected for the worker."
  type        = number
  default     = 0
  validation {
    condition     = var.ml_worker_instance_subnet_index >= 0 && floor(var.ml_worker_instance_subnet_index) == var.ml_worker_instance_subnet_index
    error_message = "ml_worker_instance_subnet_index must be a non-negative integer."
  }
}

data "aws_vpc" "ml_worker_default" {
  default = true
}

data "aws_subnets" "ml_worker_default_public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.ml_worker_default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ssm_parameter" "ml_worker_al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.ml_worker_architecture}"
}

locals {
  ml_worker_queue_name = "${var.project_name}-${var.environment}-ml-inference"
  ml_worker_dlq_name   = "${var.project_name}-${var.environment}-ml-inference-dlq"
  ml_worker_artifact_bucket_name = "${var.project_name}-${var.environment}-ml-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_sqs_queue" "ml_worker_dlq" {
  name                      = local.ml_worker_dlq_name
  message_retention_seconds = 1209600
  receive_wait_time_seconds = 20
  sqs_managed_sse_enabled   = true

  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Purpose = "ml-inference-dead-letter-queue"
  }
}

resource "aws_sqs_queue" "ml_worker" {
  name                       = local.ml_worker_queue_name
  visibility_timeout_seconds = var.ml_worker_visibility_timeout_seconds
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ml_worker_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Purpose = "ml-inference-work-queue"
  }
}

resource "aws_sqs_queue_redrive_allow_policy" "ml_worker_dlq" {
  queue_url = aws_sqs_queue.ml_worker_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.ml_worker.arn]
  })
}

resource "aws_s3_bucket" "ml_worker_artifacts" {
  bucket = local.ml_worker_artifact_bucket_name
  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Purpose = "private-ml-worker-code-and-model-artifacts"
  }
}

resource "aws_s3_bucket_ownership_controls" "ml_worker_artifacts" {
  bucket = aws_s3_bucket.ml_worker_artifacts.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "ml_worker_artifacts" {
  bucket                  = aws_s3_bucket.ml_worker_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ml_worker_artifacts" {
  bucket = aws_s3_bucket.ml_worker_artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ml_worker_artifacts" {
  bucket = aws_s3_bucket.ml_worker_artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_policy" "ml_worker_artifacts_tls" {
  bucket = aws_s3_bucket.ml_worker_artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetObjectVersion",
        "s3:DeleteObjectVersion", "s3:ListBucket", "s3:GetBucketLocation"
      ]
      Resource = [aws_s3_bucket.ml_worker_artifacts.arn, "${aws_s3_bucket.ml_worker_artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_security_group" "ml_worker" {
  name        = "${var.project_name}-${var.environment}-ml-worker"
  description = "Outbound HTTPS only for the managed ML worker; no inbound access."
  vpc_id      = data.aws_vpc.ml_worker_default.id

  egress {
    description = "HTTPS to AWS APIs, package repositories, and artifact storage"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Purpose = "ml-worker-network-access"
  }
}

data "aws_iam_policy_document" "ml_worker_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ml_worker" {
  name               = "${var.project_name}-${var.environment}-ml-worker-role"
  assume_role_policy = data.aws_iam_policy_document.ml_worker_assume_role.json
  tags = {
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ml_worker_ssm_core" {
  role       = aws_iam_role.ml_worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "ml_worker" {
  name = "ml-worker-runtime-policy"
  role = aws_iam_role.ml_worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ConsumeInferenceQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.ml_worker.arn
      },
      {
        Sid      = "QueryAccessEventsForOneUser"
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = aws_dynamodb_table.access_event.arn
      },
      {
        Sid      = "ReadProtectionState"
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.protected_files.arn
      },
      {
        Sid      = "ReadAndUpdatePerUserBanditState"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.user_baseline.arn
      },
      {
        Sid      = "WritePredictions"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.predictions.arn
      },
      {
        Sid      = "ListUserFilePrefixes"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.app_storage.arn
        Condition = {
          StringLike = { "s3:prefix" = ["*/*"] }
        }
      },
      {
        Sid      = "ReadUserObjectMetadata"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.app_storage.arn}/*/*"
      },
      {
        Sid      = "FetchPinnedWorkerRelease"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.ml_worker_artifacts.arn}/${var.ml_worker_artifact_key}"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "ml_worker" {
  name = "${var.project_name}-${var.environment}-ml-worker-profile"
  role = aws_iam_role.ml_worker.name
}

resource "aws_instance" "ml_worker" {
  count                       = var.ml_worker_enabled ? 1 : 0
  ami                         = data.aws_ssm_parameter.ml_worker_al2023_ami.value
  instance_type               = var.ml_worker_instance_type
  subnet_id                   = data.aws_subnets.ml_worker_default_public.ids[var.ml_worker_instance_subnet_index]
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.ml_worker.id]
  iam_instance_profile        = aws_iam_instance_profile.ml_worker.name
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/ml-worker-user-data.sh.tftpl", {
    aws_region             = var.aws_region
    artifact_bucket        = aws_s3_bucket.ml_worker_artifacts.bucket
    artifact_key           = var.ml_worker_artifact_key
    app_bucket             = aws_s3_bucket.app_storage.bucket
    access_event_table     = aws_dynamodb_table.access_event.name
    protected_files_table  = aws_dynamodb_table.protected_files.name
    user_baseline_table    = aws_dynamodb_table.user_baseline.name
    predictions_table      = aws_dynamodb_table.predictions.name
    queue_url              = aws_sqs_queue.ml_worker.url
    model_version          = var.ml_worker_model_version
    visibility_timeout     = var.ml_worker_visibility_timeout_seconds
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = 30
    delete_on_termination = true
  }

  lifecycle {
    precondition {
      condition     = var.ml_worker_instance_subnet_index < length(data.aws_subnets.ml_worker_default_public.ids)
      error_message = "ml_worker_instance_subnet_index must select an available default-VPC default subnet."
    }
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ml-worker"
    Project = var.project_name
    Environment = var.environment
    ManagedBy = "terraform"
    Purpose = "ml-sqs-batch-inference-worker"
  }
}

output "ml_worker_queue_url" {
  description = "SQS URL for trusted producers to enqueue per-user inference tasks."
  value       = aws_sqs_queue.ml_worker.url
}

output "ml_worker_artifact_bucket" {
  description = "Private S3 bucket for versioned ML worker release ZIPs."
  value       = aws_s3_bucket.ml_worker_artifacts.bucket
}
