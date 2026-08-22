variable "project_name" {
  description = "Short project identifier, used as a naming prefix. Not a secret, but keep it consistent with the root config."
  type        = string
  default     = "ascos"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev, staging, prod). Default is 'dev' since ASCOS is at Stage 1 with no environments defined yet — change if you want a different starting environment."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region. Frozen by the master reference: ap-south-1 (Mumbai)."
  type        = string
  default     = "ap-south-1"
}

variable "state_bucket_suffix" {
  description = <<-EOT
    Required, no default on purpose. S3 bucket names are globally unique
    across ALL AWS accounts, not just yours — "ascos-dev-tfstate" alone
    will very likely collide with someone else's bucket somewhere in the
    world. Supply something unique to you, e.g. your AWS account ID
    (recommended) or a random string. Set this in terraform.tfvars
    (copy terraform.tfvars.example) — never hardcode it here.
  EOT
  type        = string
}
