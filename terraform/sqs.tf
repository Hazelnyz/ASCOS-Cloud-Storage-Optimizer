############################################################
# ASCOS — Stage 7.5: Access Event Writer Dead-Letter Queue
#
# SCOPE (approved Stage 7 blueprint, decision #8):
#   DLQ only on access-event-writer-fn, NOT on anomaly-scorer-fn.
#   A lost writer invocation is a permanent, silent hole in the
#   future ML training dataset (master reference §22, ML schema
#   §1 — access_event is the authoritative source Stage 10 trains
#   on) — worth the small extra infrastructure to catch and allow
#   replay of failed writes rather than losing them invisibly.
#   A lost anomaly-scorer-fn invocation loses nothing real in
#   Stage 7, since its scoring logic is a hardcoded "Low" stub
#   with no persisted state — no DLQ is added for it here.
#
# MECHANISM: aws_lambda_function_event_invoke_config's
#   destination_config.on_failure is used rather than the older
#   dead_letter_config attribute on aws_lambda_function — this is
#   the current AWS-recommended path for asynchronous invocation
#   failures (which is what an EventBridge-triggered Lambda always
#   is), and it carries richer failure metadata (invoking event,
#   error, timestamps) than the legacy DLQ mechanism.
#
# RETENTION: 14 days on the queue — long enough to notice and
#   investigate a failure pattern without needing same-day
#   response, short enough not to accumulate indefinitely.
############################################################

resource "aws_sqs_queue" "access_event_writer_dlq" {
  name                      = "${var.project_name}-${var.environment}-access-event-writer-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage7-access-event-writer-failure-queue"
  }
}

resource "aws_lambda_function_event_invoke_config" "access_event_writer_fn" {
  function_name = aws_lambda_function.access_event_writer_fn.function_name

  destination_config {
    on_failure {
      destination = aws_sqs_queue.access_event_writer_dlq.arn
    }
  }
}