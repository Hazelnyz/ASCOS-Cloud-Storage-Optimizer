############################################################
# Shared variables for the whole ASCOS project.
# Stage 1 only needs these three — later stages (Cognito,
# S3, DynamoDB, Lambda, etc.) will add their own variables
# files without touching this one.
############################################################

variable "project_name" {
  description = "Short project identifier, used as a naming prefix across all resources."
  type        = string
  default     = "ascos"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region. Frozen by the master reference: ap-south-1 (Mumbai) is the single primary region for this project."
  type        = string
  default     = "ap-south-1"
}

variable "frontend_origins" {
  description = "Origins allowed to call the API (Stage 6 CORS) and to upload/download directly to/from S3 via presigned URLs (Stage 9 CORS). Development default until Stage 9 adds the real deployed frontend URL (Amplify/CloudFront) to this list."
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "alert_email" {
  description = "Email address to receive Stage 7 admin security/error alerts (SNS subscription). No default — must be supplied via terraform.tfvars (gitignored, never committed)."
  type        = string
  sensitive   = true
}

############################################################
# Cost & Budget Variables
#
# All rates are per-unit values in USD. Storage rates are per
# GB-month. Request rates are per 1,000 requests. Retrieval
# rates are per GB retrieved.
#
# Source for ap-south-1 storage and STANDARD request rates:
# cloud-credits.org/prices/s3/ap-south-1 (third-party mirror
# of the AWS S3 offer file).
#
# Note: WARM/COLD request and retrieval rates are us-east-1
# values and are NOT confirmed for ap-south-1. These are
# approximations only.
############################################################

variable "storage_rate_hot" {
  description = "S3 Standard storage rate per GB-month in ap-south-1"
  type        = number
  default     = 0.025
}

variable "storage_rate_warm" {
  description = "S3 Standard-IA storage rate per GB-month in ap-south-1"
  type        = number
  default     = 0.0138
}

variable "storage_rate_cold" {
  description = "S3 Glacier Instant Retrieval storage rate per GB-month in ap-south-1"
  type        = number
  default     = 0.005
}

variable "request_rate_standard_write" {
  description = "S3 STANDARD PUT/COPY/POST/LIST rate per 1,000 requests in ap-south-1"
  type        = number
  default     = 0.005
}

variable "request_rate_standard_read" {
  description = "S3 STANDARD GET/SELECT rate per 1,000 requests in ap-south-1"
  type        = number
  default     = 0.0004
}

variable "request_rate_warm_write" {
  description = "S3 Standard-IA PUT/COPY/POST/LIST rate per 1,000 requests (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.01
}

variable "request_rate_warm_read" {
  description = "S3 Standard-IA GET/SELECT rate per 1,000 requests (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.001
}

variable "request_rate_cold_write" {
  description = "S3 Glacier Instant Retrieval PUT rate per 1,000 requests (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.02
}

variable "request_rate_cold_read" {
  description = "S3 Glacier Instant Retrieval GET rate per 1,000 requests (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.01
}

variable "request_rate_delete" {
  description = "S3 DELETE rate per 1,000 requests (0 = no charge for DELETE)"
  type        = number
  default     = 0
}

variable "retrieval_rate_warm" {
  description = "S3 Standard-IA retrieval rate per GB (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.01
}

variable "retrieval_rate_cold" {
  description = "S3 Glacier Instant Retrieval retrieval rate per GB (unverified for ap-south-1, using us-east-1 value)"
  type        = number
  default     = 0.03
}

variable "shared_overhead_monthly" {
  description = "Fixed monthly shared overhead amount in USD (split equally among active users)"
  type        = number
  default     = 5.0
}

variable "budget_min" {
  description = "Minimum allowed budget value in USD"
  type        = number
  default     = 0
}

variable "budget_max" {
  description = "Maximum allowed budget value in USD"
  type        = number
  default     = 1000
}

variable "budget_step" {
  description = "Budget slider step increment in USD"
  type        = number
  default     = 5
}

variable "alert_threshold_min" {
  description = "Minimum allowed alert threshold percentage"
  type        = number
  default     = 1
}

variable "alert_threshold_max" {
  description = "Maximum allowed alert threshold percentage"
  type        = number
  default     = 100
}
