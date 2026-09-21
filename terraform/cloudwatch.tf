############################################################
# ASCOS — Stage 7.6: CloudWatch Alarms
#
# SCOPE (master reference §21, §36):
#   Three alarms, each tied to admin_alerts (sns.tf):
#     1. access-event-writer-fn errors — critical path for the
#        future ML training dataset; a silent failure here is
#        worse than in most Lambdas so far (master reference §22).
#     2. anomaly-scorer-fn errors — same baseline error coverage
#        every Lambda should have, per §21's monitoring/alerting
#        scope for this stage.
#     3. access-event-writer-dlq depth — a non-zero depth means
#        events are being permanently lost from access_event
#        unless someone notices and replays them (Stage 7.5).
#
# Evaluation period of 1 x 300s (5 min) at threshold > 0 is
# intentionally sensitive — at this project's scale (~5-10 users),
# any Lambda error or DLQ message is worth an immediate look, not
# something to average away with a longer period or higher bar.
############################################################

resource "aws_cloudwatch_metric_alarm" "access_event_writer_fn_errors" {
  alarm_name          = "${var.project_name}-${var.environment}-access-event-writer-fn-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  dimensions = {
    FunctionName = aws_lambda_function.access_event_writer_fn.function_name
  }
  alarm_actions = [aws_sns_topic.admin_alerts.arn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_metric_alarm" "anomaly_scorer_fn_errors" {
  alarm_name          = "${var.project_name}-${var.environment}-anomaly-scorer-fn-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  dimensions = {
    FunctionName = aws_lambda_function.anomaly_scorer_fn.function_name
  }
  alarm_actions = [aws_sns_topic.admin_alerts.arn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_metric_alarm" "access_event_writer_dlq_depth" {
  alarm_name          = "${var.project_name}-${var.environment}-access-event-writer-dlq-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  dimensions = {
    QueueName = aws_sqs_queue.access_event_writer_dlq.name
  }
  alarm_actions = [aws_sns_topic.admin_alerts.arn]

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}