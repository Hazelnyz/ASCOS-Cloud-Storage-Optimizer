############################################################
# ASCOS — API Layer (API Gateway) — Stage 6
#
# SCOPE (master reference §33 Stage 6):
#   API Gateway HTTP API (NOT REST API — HTTP API is lighter-cost
#   and has a native Cognito JWT authorizer, so no custom Lambda
#   authorizer is needed here). 10 routes, all Cognito-JWT-
#   protected, covering file listing, upload/download/share URL
#   generation, metadata, delete, tier forecast/change, Frequently
#   Used, and feedback.
#
# THIS FILE CONTAINS: the API Gateway resource itself, CORS, the
# JWT authorizer, integrations, routes, the stage, access logging,
# and Lambda invoke permissions.
#
# THIS FILE DOES NOT CONTAIN: the 7 new Lambda functions and their
# IAM roles — those live in api-lambdas.tf, kept separate on
# purpose so API-layer and compute-layer concerns aren't mixed in
# one file. The 3 Stage 5 Lambdas this API also exposes
# (forecast-fn, tier-change-fn, feedback-writer-fn) are NOT
# redefined here at all — referenced directly from lambda.tf's
# existing resources.
#
# AUTHORIZATION MODEL:
#   Cognito JWT -> API Gateway validates token (issuer + audience)
#   -> Lambda receives validated claims via the proxy integration
#   -> Lambda derives user_id from those claims, NEVER from
#   client-supplied input -> Lambda constructs the S3 key. IAM
#   scoping on each Lambda's role is defense-in-depth, not the
#   primary authorization mechanism — that's Lambda's job, per
#   master reference §7.
#
# ACCESS TOKENS, NOT ID TOKENS:
#   The JWT authorizer validates Cognito access tokens (audience =
#   app client ID). This matches how a browser-based SPA client
#   normally calls a protected API after sign-in.
############################################################

############################################################
# HTTP API + CORS
############################################################

resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-${var.environment}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = [var.frontend_origin]
    allow_methods = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_headers = ["Authorization", "Content-Type"]
    max_age       = 300
    # credentials NOT enabled — ASCOS uses Cognito bearer access
    # tokens in the Authorization header, not browser cookies, so
    # allow_credentials = true is not required and is deliberately
    # left unset.
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage6-api"
  }
}

############################################################
# Cognito JWT authorizer — native HTTP API authorization, no
# custom Lambda authorizer needed.
############################################################

resource "aws_apigatewayv2_authorizer" "cognito_jwt" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.project_name}-${var.environment}-cognito-jwt"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

############################################################
# API access logging — request/route/status/latency, distinct
# from application/file-access logging (CloudTrail, Stage 7).
############################################################

resource "aws_cloudwatch_log_group" "api_access_logs" {
  name              = "/aws/apigateway/${var.project_name}-${var.environment}-api"
  retention_in_days = 14

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
    format = jsonencode({
      requestId               = "$context.requestId"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
      requestTime             = "$context.requestTime"
      sourceIp                = "$context.identity.sourceIp"
    })
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

############################################################
# Integrations — one per Lambda. 7 for the new functions
# (api-lambdas.tf), 3 for existing Stage 5 functions (lambda.tf).
# AWS_PROXY + payload format 2.0 throughout.
############################################################

resource "aws_apigatewayv2_integration" "file_list_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_list_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "file_upload_url_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_upload_url_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "file_download_url_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_download_url_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "file_metadata_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_metadata_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "file_delete_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_delete_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "file_share_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.file_share_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "frequently_used_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.frequently_used_fn.invoke_arn
  payload_format_version = "2.0"
}

# --- Existing Stage 5 Lambdas — referenced, not recreated ---

resource "aws_apigatewayv2_integration" "forecast_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.forecast_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "tier_change_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.tier_change_fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "feedback_writer_fn" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.feedback_writer_fn.invoke_arn
  payload_format_version = "2.0"
}

############################################################
# Routes — all 10, all Cognito JWT-protected.
############################################################

resource "aws_apigatewayv2_route" "get_files" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /files"
  target             = "integrations/${aws_apigatewayv2_integration.file_list_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "post_files_upload_url" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /files/upload-url"
  target             = "integrations/${aws_apigatewayv2_integration.file_upload_url_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "get_files_download_url" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /files/{fileId}/download-url"
  target             = "integrations/${aws_apigatewayv2_integration.file_download_url_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "get_files_metadata" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /files/{fileId}/metadata"
  target             = "integrations/${aws_apigatewayv2_integration.file_metadata_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "delete_files" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "DELETE /files/{fileId}"
  target             = "integrations/${aws_apigatewayv2_integration.file_delete_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "post_files_share_url" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /files/{fileId}/share-url"
  target             = "integrations/${aws_apigatewayv2_integration.file_share_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "get_files_frequently_used" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /files/frequently-used"
  target             = "integrations/${aws_apigatewayv2_integration.frequently_used_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "get_files_tier_forecast" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /files/{fileId}/tier/forecast"
  target             = "integrations/${aws_apigatewayv2_integration.forecast_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "post_files_tier_change" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /files/{fileId}/tier/change"
  target             = "integrations/${aws_apigatewayv2_integration.tier_change_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

resource "aws_apigatewayv2_route" "post_feedback" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /feedback"
  target             = "integrations/${aws_apigatewayv2_integration.feedback_writer_fn.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito_jwt.id
}

############################################################
# Lambda invoke permissions — one per Lambda this API calls,
# each scoped to THIS API's execution ARN only (not unrestricted
# apigateway.amazonaws.com invocation).
############################################################

resource "aws_lambda_permission" "file_list_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_list_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "file_upload_url_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_upload_url_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "file_download_url_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_download_url_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "file_metadata_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_metadata_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "file_delete_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_delete_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "file_share_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.file_share_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "frequently_used_fn" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.frequently_used_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "forecast_fn_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.forecast_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "tier_change_fn_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tier_change_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "feedback_writer_fn_api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.feedback_writer_fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
