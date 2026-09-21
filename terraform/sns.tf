############################################################
# ASCOS — Stage 7.6: SNS Admin Alerts
#
# SCOPE (master reference §19, §21):
#   Single topic, single email subscription, for High-severity
#   anomaly alerts and Lambda/DLQ error alarms. The anomaly-
#   scorer-fn publish path (_publish_alert, Stage 7 dormant) is
#   wired to this topic so the pipe is provably correct before
#   real Isolation Forest scoring (Stage 10) ever produces a
#   genuine High result to exercise it.
#
# EMAIL CONFIRMATION: SNS email subscriptions require manual
#   confirmation via a link sent to the address — the
#   subscription stays PendingConfirmation, and nothing is
#   delivered, until that link is clicked. Expect one
#   confirmation email immediately after apply, sent to
#   vandana.b6871@gmail.com.
#
# TOPIC POLICY — WHY THIS EXISTS:
#   CloudWatch Alarms are a service-initiated caller (like
#   EventBridge invoking a Lambda, Stage 7.4), not an IAM-role-
#   bearing one — same-account SNS topics don't automatically
#   trust the CloudWatch service to publish just because they're
#   owned by the same account. Provisioning via the AWS console
#   silently adds this grant for you; provisioning via Terraform/
#   CLI does not, so it's made explicit here. Scoped via
#   aws:SourceAccount so only this account's CloudWatch alarms
#   can publish to this topic.
#
#   NOTE: anomaly-scorer-fn's own dormant _publish_alert path
#   (Stage 10 activation) does NOT need this policy — it
#   publishes via its execution role's identity-based sns:Publish
#   grant (lambda.tf), which is sufficient on its own for a
#   same-account topic. This policy addition is specifically for
#   the CloudWatch-alarm-initiated publish path.
############################################################

resource "aws_sns_topic" "admin_alerts" {
  name              = "${var.project_name}-${var.environment}-admin-alerts"
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "stage7-admin-alerting"
  }
}

resource "aws_sns_topic_policy" "admin_alerts" {
  arn = aws_sns_topic.admin_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudWatchAlarmsPublish"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.admin_alerts.arn
        Condition = {
          StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        }
      }
    ]
  })
}

resource "aws_sns_topic_subscription" "admin_email" {
  topic_arn = aws_sns_topic.admin_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}