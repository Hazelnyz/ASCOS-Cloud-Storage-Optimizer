############################################################
# ASCOS — Stage 7.4: EventBridge Routing
#
# Routes CloudTrail S3 events to the append-only access-event writer.
# The anomaly scorer runs separately on its 15-minute schedule so it
# can build complete hourly windows rather than score individual calls.
#
# SOURCE FIELD — IMPORTANT: for CloudTrail-sourced S3 data events
# (object-level operations like GetObject/PutObject/DeleteObject)
# routed through EventBridge, AWS's own documented pattern uses
# source = "aws.s3" — matching the originating service — while
# detail-type = "AWS API Call via CloudTrail" separately marks
# that the event arrived via CloudTrail's audit path (as opposed
# to a native S3 Event Notification, a different integration
# entirely). This mirrors AWS's official tutorial "Log Amazon S3
# object-level operations using EventBridge"
# (docs.aws.amazon.com/eventbridge/latest/userguide/eb-log-s3-data-events.html),
# which documents exactly this pattern for exactly this use case.
# An earlier draft of this rule used source = "aws.cloudtrail"
# based on how CloudTrail-forwarded *management*-event patterns
# are commonly documented elsewhere — that generalization to S3
# data events specifically was not verified against AWS's actual
# documented behavior for this scenario, and is corrected here.
#
# STILL TO VERIFY AGAINST A REAL DELIVERED EVENT (not just
# documentation) before relying on this rule: trigger one real
# GetObject against the deployed API once CloudTrail (7.1/7.2) is
# live, capture the actual EventBridge event, and confirm the
# real source value matches "aws.s3" before trusting this pattern
# in production. Do this before terraform apply, not after.
#
# eventName is restricted to GetObject/PutObject/DeleteObject.
# CopyObject/UploadPartCopy/RestoreObject/CompleteMultipartUpload
# are excluded by omission — these are system-initiated tier-
# transition operations (tier-change-fn), not user access, and
# must never contaminate the access_event stream Stage 10 trains
# on. CloudTrail (Stage 7.2) still logs all of these unfiltered,
# so the audit trail stays complete — only this routing layer
# narrows scope.
# on. CloudTrail (Stage 7.2) still logs all of these unfiltered,
# so the audit trail stays complete — only this routing layer
# narrows scope. Scheduled baseline volume scoring reads this
# append-only log; Isolation Forest remains planned.
############################################################

resource "aws_cloudwatch_event_rule" "s3_access_events" {
  name        = "${var.project_name}-${var.environment}-s3-access-events"
  description = "Routes GetObject/PutObject/DeleteObject S3 data events on the app bucket to access-event-writer-fn"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["s3.amazonaws.com"]
      eventName   = ["GetObject", "PutObject", "DeleteObject"]
      requestParameters = {
        bucketName = [aws_s3_bucket.app_storage.bucket]
      }
    }
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_event_target" "to_access_event_writer_fn" {
  rule = aws_cloudwatch_event_rule.s3_access_events.name
  arn  = aws_lambda_function.access_event_writer_fn.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_access_event_writer_fn" {
  statement_id  = "AllowEventBridgeInvokeAccessEventWriter"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.access_event_writer_fn.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.s3_access_events.arn
}

resource "aws_cloudwatch_event_rule" "anomaly_scorer_schedule" {
  name                = "${var.project_name}-${var.environment}-anomaly-scorer-schedule"
  description         = "Runs per-user baseline volume scoring every 15 minutes"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "anomaly_scorer_schedule" {
  rule = aws_cloudwatch_event_rule.anomaly_scorer_schedule.name
  arn  = aws_lambda_function.anomaly_scorer_fn.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_anomaly_scorer_fn" {
  statement_id  = "AllowScheduledEventBridgeInvokeAnomalyScorer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.anomaly_scorer_fn.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.anomaly_scorer_schedule.arn
}