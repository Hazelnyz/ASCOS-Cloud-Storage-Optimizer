output "state_bucket_name" {
  description = "Name of the bucket created for Terraform remote state. Copy this into ../backend.hcl."
  value       = aws_s3_bucket.terraform_state.id
}

output "state_bucket_arn" {
  description = "ARN of the state bucket."
  value       = aws_s3_bucket.terraform_state.arn
}

output "state_bucket_region" {
  description = "Region the state bucket was created in. Copy this into ../backend.hcl."
  value       = var.aws_region
}
