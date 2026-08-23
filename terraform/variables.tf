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
