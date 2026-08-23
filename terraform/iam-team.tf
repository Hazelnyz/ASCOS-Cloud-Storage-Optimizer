############################################################
# ASCOS — Infrastructure Manager IAM
#
# SCOPE:
#   This file manages IAM identities for INFRASTRUCTURE
#   MANAGERS only (teammates who administer AWS/Terraform).
#   It has nothing to do with ASCOS application end users —
#   those are Cognito identities, managed entirely in
#   cognito.tf. Never create an IAM user for an app user.
#
# vandana-admin:
#   The primary AWS administrator (vandana-admin) was created
#   manually during initial account setup and is intentionally
#   NOT imported into or managed by Terraform. It remains a
#   standing, out-of-band identity — the same reasoning as the
#   AWS docs' own root-account guidance: your first/primary
#   admin identity is deliberately kept outside routine
#   Terraform lifecycle management, so a bad `apply`/`destroy`
#   can never lock out the person running Terraform.
#
# ACCESS MODEL FOR TEAMMATES:
#   Teammates get PowerUserAccess, not AdministratorAccess.
#   PowerUserAccess = full ability to create/modify/delete any
#   project resource (S3, DynamoDB, Lambda, API Gateway,
#   Cognito, CloudTrail, EventBridge, CloudWatch, SNS, etc.)
#   EXCEPT IAM user/group/policy management and account-level
#   settings (billing, organizations). This is a deliberate,
#   reversible choice — not a limitation on what they can build.
#   Decision + reasoning logged in docs/AWS_SETUP_LOG.md.
#
# ACTIVATION:
#   Users are defined here so the identity + permission exist
#   in Terraform state, but NO console password or programmatic
#   access key is generated yet — there's no one to hand
#   credentials to until they're actually onboarding. When a
#   teammate is ready, generate their credentials manually
#   (same pattern as vandana-admin's own setup) rather than
#   having Terraform create/output secrets.
#
# LAMBDA EXECUTION ROLES:
#   Explicitly NOT defined here. Lambda execution roles belong
#   to the compute stage (Stage 5) and must remain separate from
#   these human infrastructure-manager identities.
############################################################

locals {
  # Add/remove teammates here — everything downstream (user +
  # policy attachment) is generated from this single list.
  infra_team_members = [
    "nikhita",
    "rukkshana",
  ]
}

resource "aws_iam_user" "team" {
  for_each = toset(local.infra_team_members)

  name = each.value

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Role      = "infra-manager"
  }
}

resource "aws_iam_user_policy_attachment" "team_power_user" {
  for_each = aws_iam_user.team

  user       = each.value.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}