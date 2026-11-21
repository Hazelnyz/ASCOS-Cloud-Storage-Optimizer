############################################################
# ASCOS — Root Terraform config
#
# Stage 1 (this stage) only establishes the remote state
# backend and shared provider/variables — see versions.tf
# and variables.tf. No AWS application resources exist yet.
#
# Build order (per master reference §33), each stage adds
# its own resources here or in a dedicated file:
#   Stage 2  — iam-team.tf, cognito.tf        (identity)
#   Stage 3  — s3.tf                          (storage)
#   Stage 4  — dynamodb.tf                    (data layer)
#   Stage 5  — lambda.tf                      (compute)
#   Stage 6  — api-gateway.tf                 (API layer)
#   Stage 7  — cloudtrail.tf, eventbridge.tf,
#              cloudwatch.tf, sns.tf          (eventing/monitoring/security)
#   Stage 8  — outputs.tf                     (frontend config)
#   Stage 9  — frontend-hosting.tf            (frontend)
#   Stage 10 — ml pipeline (backend/ml, not Terraform-only)
#   Stage 11 — end-to-end validation
#
# Do not add resources here ahead of their stage — each stage
# should be reviewed and applied on its own.
############################################################
