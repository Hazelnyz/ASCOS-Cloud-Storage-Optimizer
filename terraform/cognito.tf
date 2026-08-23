############################################################
# ASCOS — Application End-User Identity (Cognito)
#
# SCOPE:
#   This file manages ASCOS APPLICATION END-USER identity only.
#   It is completely separate from iam-team.tf (infrastructure
#   managers). Never create an IAM user for an application user,
#   and never treat a Cognito user as an AWS IAM identity — see
#   master reference §1, §34.2.
#
# SIGN-IN MODEL:
#   Email-as-username. No separate username field is collected.
#   Cognito's `sub` (not the email) becomes the application's
#   stable user_id, per master reference §5 — email can change,
#   sub cannot.
#
# DISPLAY NAME:
#   A custom, mutable, non-required "display_name" attribute is
#   included for UI/profile purposes only (1-50 chars). It is
#   deliberately NOT unique and NOT used as an identifier
#   anywhere — email remains the login identifier, sub remains
#   the canonical user_id. Kept minimal on purpose: no phone,
#   DOB, avatar, bio, or other profile fields here — this file
#   is the identity layer, not the user-profile system. Further
#   profile data belongs in DynamoDB later, if actually needed.
#
# AUTH FLOW:
#   The frontend integrates with Cognito via the SDK directly
#   (master reference §3, §6) — this is NOT a Hosted-UI/OAuth
#   redirect flow. Accordingly, this config intentionally does
#   NOT set allowed_oauth_flows, callback_urls, or logout_urls;
#   those belong to a Hosted-UI pattern this project isn't using.
#   explicit_auth_flows enables SRP-based sign-in (ALLOW_USER_SRP_AUTH)
#   plus refresh-token auth, which is what a direct-SDK flow needs.
#
# APP CLIENT:
#   Public client (generate_secret = false). A browser cannot
#   safely hold a client secret — anything shipped to frontend
#   JS is inspectable. This is the standard, correct setup for a
#   browser-based SPA per AWS's own guidance.
#
# PASSWORD POLICY:
#   Minimum 8 characters, upper + lower + number + symbol.
#   Deliberately chosen as "secure reasonable default," not
#   maximal strictness — see docs/AWS_SETUP_LOG.md decision log.
#
# MFA — IMPORTANT, READ BEFORE CHANGING:
#   mfa_configuration = "OFF" for this stage. This is a
#   DELIBERATE, DISCUSSED decision, not an oversight:
#
#   Target design (documented, not yet implemented): every user
#   enrolls MFA once; normal logins stay password-only; ASCOS's
#   own security/anomaly system triggers a step-up MFA challenge
#   only when it detects suspicious activity, with escalation to
#   a 12-hour account lock + admin notification for high-severity
#   threats (master reference §19).
#
#   That target design requires a custom Cognito authentication
#   flow (DefineAuthChallenge / CreateAuthChallenge /
#   VerifyAuthChallengeResponse Lambda triggers), which in turn
#   requires the security/anomaly Lambda system that doesn't
#   exist yet (Stage 5+). Cognito's basic mfa_configuration
#   setting cannot express "enroll once, challenge only when
#   suspicious" — ON means every login is challenged; there is
#   no built-in middle ground without either the paid Advanced
#   Security feature (explicitly not being used — see below) or
#   the custom Lambda challenge flow above.
#
#   Turning mfa_configuration to ON now would force every user
#   through MFA on every single login for however long it takes
#   to build the Stage 5+ security system, with zero adaptive
#   benefit in the meantime. That's a real UX cost with no
#   corresponding security gain, so it was deliberately rejected.
#
#   DO NOT flip this to "ON" or "OPTIONAL" piecemeal. The full
#   MFA system (mandatory enrollment + step-up challenge + lock +
#   alert) should be implemented together as one coherent piece
#   once the security/authentication Lambda infrastructure
#   actually exists to use it. See docs/AWS_SETUP_LOG.md for the
#   full decision history.
#
# ADVANCED SECURITY:
#   Not enabled. It's a paid, per-MAU AWS feature that could
#   provide risk-based adaptive auth automatically, but using it
#   would mean paying AWS to solve a problem this project intends
#   to solve with its own Lambda/anomaly-detection system instead
#   (master reference §35's GuardDuty reasoning applies here too:
#   a custom pipeline was chosen deliberately over a managed
#   AWS security product).
#
# USER METADATA PROVISIONING:
#   Lazy provisioning. No PostConfirmation Lambda trigger is
#   wired up here. Application metadata (baseline DynamoDB
#   records, etc.) initializes on the user's first real action
#   instead of immediately after signup — see master reference
#   §5 Option B. This avoids creating a Lambda + IAM role now
#   that would depend on DynamoDB tables that don't exist until
#   Stage 4. Re-evaluate PostConfirmation once Stages 4 and 5
#   are real, rather than building it prematurely.
############################################################

resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-${var.environment}-users"

  # Email is the sign-in identifier; no separate username exists.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # UI/profile-only display name. Deliberately NOT unique, NOT
  # required, NOT used as any kind of identifier — sub remains
  # the canonical user_id, email remains the login identifier.
  # mutable = true because schema attributes cannot be changed
  # after pool creation, and this is meant to be editable later.
  schema {
    name                = "display_name"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 1
      max_length = 50
    }
  }

  # Deliberately OFF for this stage — see header comment above.
  # DO NOT change without re-reading the decision log.
  mfa_configuration = "OFF"

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "ASCOS — verify your account"
    email_message        = "Your ASCOS verification code is {####}"
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "application-end-user-identity"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project_name}-${var.environment}-web-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # Public client — browsers cannot safely hold a secret.
  generate_secret = false

  # Direct-SDK auth (SRP), not Hosted-UI/OAuth. No callback_urls,
  # logout_urls, or allowed_oauth_flows — see header comment.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Don't reveal whether a given email exists in the pool on
  # failed sign-in/forgot-password attempts.
  prevent_user_existence_errors = "ENABLED"

  # A schema attribute existing on the pool does NOT automatically
  # mean this client can read/write it — that's a separate,
  # per-client permission. Explicitly grant it here so the
  # frontend can actually set/update the user's display name.
  read_attributes  = ["email", "custom:display_name"]
  write_attributes = ["custom:display_name"]
}