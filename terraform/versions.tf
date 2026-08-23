############################################################
# ASCOS — Root Terraform config: backend + provider wiring
#
# This is the REAL project's Terraform. It stores its state
# remotely, in the bucket created by ./bootstrap.
#
# LOCKING: S3-native locking (use_lockfile = true) per the
# master reference §30 — deliberately NOT DynamoDB-based
# locking. No DynamoDB table is created for this purpose
# anywhere in this project.
############################################################

terraform {
  required_version = ">= 1.11.0" # 1.11+ required for S3 native locking (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # NOTE: Terraform backend blocks cannot reference variables or
  # locals — this is a Terraform language limitation, not an ASCOS
  # decision. So this block only sets what CAN be hardcoded safely
  # (locking behavior), and everything environment-specific (bucket
  # name, key, region) is supplied at `terraform init` time via:
  #
  #   terraform init -backend-config=backend.hcl
  #
  # backend.hcl is gitignored (like terraform.tfvars) since, depending
  # on setup, it may be considered environment-sensitive config.
  # See backend.hcl.example for the template.
  backend "s3" {
    use_lockfile = true
  }
}

provider "aws" {
  profile = "ascos-terraform"
  region = var.aws_region
}
