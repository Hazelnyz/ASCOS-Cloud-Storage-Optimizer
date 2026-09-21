# Stage 8 - frontend-facing values exposed as Terraform outputs (Master Reference section 33).
# None of these are secrets. They are consumed as frontend env values, never hardcoded in source.
# Deliberately excluded: DynamoDB table names, the Terraform state bucket, Lambda names and other
# backend-internal values (populated into Lambdas via env vars, not needed by the frontend).
# The hosting URL output is added in Stage 9, once hosting exists.

output "app_storage_bucket" {
  description = "Application file-storage bucket name"
  value       = aws_s3_bucket.app_storage.bucket
}

output "api_endpoint" {
  description = "API Gateway HTTP API base URL (no trailing slash, no stage suffix)"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_app_client_id" {
  description = "Cognito App Client ID (web client)"
  value       = aws_cognito_user_pool_client.web.id
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}