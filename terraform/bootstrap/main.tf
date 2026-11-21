############################################################
# ASCOS — Terraform Bootstrap
#
# WHAT THIS IS:
#   A tiny, separate Terraform config that creates ONLY the
#   S3 bucket that will later hold the real project's remote
#   state (see ../versions.tf and ../backend.hcl.example).
#
# WHY IT'S SEPARATE:
#   Terraform can't be told "store your state in bucket X" if
#   bucket X doesn't exist yet. So this bootstrap config runs
#   ONCE with plain local state (a terraform.tfstate file on
#   disk, not in S3) to create that bucket. After that, this
#   bootstrap folder is rarely touched again.
#
# LOCKING:
#   Per the ASCOS master reference (§30), we use Terraform's
#   native S3 locking (`use_lockfile = true` in the backend
#   block), NOT a DynamoDB lock table. No DynamoDB resource
#   is created here or anywhere for Terraform locking purposes.
############################################################

terraform {
  required_version = ">= 1.11.0" # 1.11+ required for S3 native locking (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Intentionally NO backend block here — this config uses local state
  # on purpose. Do not add an S3 backend to this bootstrap folder.
}

provider "aws" {
  profile = "ascos-terraform"
  region = var.aws_region
}

# The bucket that will hold Terraform remote state for the rest of ASCOS.
resource "aws_s3_bucket" "terraform_state" {
  bucket = "${var.project_name}-${var.environment}-tfstate-${var.state_bucket_suffix}"

  # Guardrail: a `terraform destroy` run against this bootstrap config
  # should never be able to silently delete the bucket that every other
  # stage's state lives in.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "terraform-remote-state"
    ManagedBy   = "terraform-bootstrap"
  }
}

# Versioning: required by the master reference (§30) so a corrupted or
# accidentally-overwritten state file can be rolled back.
resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Encrypt state at rest. State files can contain sensitive values
# (ARNs, resource IDs, sometimes secrets from data sources), so this
# is a baseline regardless of what ends up in later stages.
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Block Public Access — this bucket only ever holds infra state, never
# app/user data, but there's no reason it should ever be public either.
resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Deny any non-TLS access to the state bucket.
resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
