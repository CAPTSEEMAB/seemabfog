# ============== CLOUDWATCH LOG GROUPS (retention = 14 days) ==============

resource "aws_cloudwatch_log_group" "process_aggregates_logs" {
  name              = "/aws/lambda/${var.project_name}-process-aggregates"
  retention_in_days = 14
  tags              = { Environment = var.environment }
}

resource "aws_cloudwatch_log_group" "process_events_logs" {
  name              = "/aws/lambda/${var.project_name}-process-events"
  retention_in_days = 14
  tags              = { Environment = var.environment }
}

resource "aws_cloudwatch_log_group" "dashboard_api_logs" {
  name              = "/aws/lambda/${var.project_name}-dashboard-api"
  retention_in_days = 14
  tags              = { Environment = var.environment }
}

# ============== CLOUDWATCH DASHBOARD ==============

resource "aws_cloudwatch_dashboard" "smart_traffic_dashboard" {
  dashboard_name = "${var.project_name}-operations"

  dashboard_body = jsonencode({
    widgets = [
      # ── Row 1: SQS Queue Depths ──────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "SQS ApproxNumberOfMessagesVisible"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible",
              "QueueName", aws_sqs_queue.aggregates_queue.name,
              { stat = "Maximum", period = 60, label = "Aggregates Queue" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible",
              "QueueName", aws_sqs_queue.events_queue.name,
              { stat = "Maximum", period = 60, label = "Events Queue" }]
          ]
        }
      },
      # ── DLQ Depth (should be 0) ─────────────────────────────
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "DLQ Depth (should be 0)"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible",
              "QueueName", aws_sqs_queue.aggregates_dlq.name,
              { stat = "Maximum", period = 60, color = "#d62728", label = "Aggregates DLQ" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible",
              "QueueName", aws_sqs_queue.events_dlq.name,
              { stat = "Maximum", period = 60, color = "#ff7f0e", label = "Events DLQ" }]
          ]
        }
      },
      # ── Row 2: Lambda Errors ─────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Lambda Errors"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/Lambda", "Errors",
              "FunctionName", aws_lambda_function.process_aggregates.function_name,
              { stat = "Sum", period = 60, color = "#d62728", label = "process-aggregates" }],
            ["AWS/Lambda", "Errors",
              "FunctionName", aws_lambda_function.process_events.function_name,
              { stat = "Sum", period = 60, color = "#ff7f0e", label = "process-events" }],
            ["AWS/Lambda", "Errors",
              "FunctionName", aws_lambda_function.dashboard_api.function_name,
              { stat = "Sum", period = 60, color = "#9467bd", label = "dashboard-api" }]
          ]
        }
      },
      # ── Lambda Duration ──────────────────────────────────────
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Lambda Duration (ms)"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/Lambda", "Duration",
              "FunctionName", aws_lambda_function.process_aggregates.function_name,
              { stat = "Average", period = 60, label = "aggregates avg" }],
            ["AWS/Lambda", "Duration",
              "FunctionName", aws_lambda_function.process_events.function_name,
              { stat = "Average", period = 60, label = "events avg" }],
            ["AWS/Lambda", "Duration",
              "FunctionName", aws_lambda_function.dashboard_api.function_name,
              { stat = "p99", period = 60, label = "dashboard p99" }]
          ]
        }
      },
      # ── Lambda Throttles ─────────────────────────────────────
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Lambda Throttles"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/Lambda", "Throttles",
              "FunctionName", aws_lambda_function.process_aggregates.function_name,
              { stat = "Sum", period = 60, color = "#e377c2", label = "aggregates" }],
            ["AWS/Lambda", "Throttles",
              "FunctionName", aws_lambda_function.process_events.function_name,
              { stat = "Sum", period = 60, color = "#bcbd22", label = "events" }],
            ["AWS/Lambda", "Throttles",
              "FunctionName", aws_lambda_function.dashboard_api.function_name,
              { stat = "Sum", period = 60, color = "#17becf", label = "dashboard" }]
          ]
        }
      },
      # ── Row 3: DynamoDB Throttled Requests ───────────────────
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB ThrottledRequests"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/DynamoDB", "ThrottledRequests",
              "TableName", aws_dynamodb_table.aggregates_table.name,
              { stat = "Sum", period = 60, label = "aggregates" }],
            ["AWS/DynamoDB", "ThrottledRequests",
              "TableName", aws_dynamodb_table.events_table.name,
              { stat = "Sum", period = 60, label = "events" }],
            ["AWS/DynamoDB", "ThrottledRequests",
              "TableName", aws_dynamodb_table.kpis_table.name,
              { stat = "Sum", period = 60, label = "kpis" }]
          ]
        }
      }
    ]
  })
}

# ============== CLOUDWATCH ALARMS ==============

# ── DLQ Alarms: > 0 messages (1 datapoint, 1 period) ──────

resource "aws_cloudwatch_metric_alarm" "dlq_alarm_aggregates" {
  alarm_name          = "${var.project_name}-dlq-aggregates-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Aggregates DLQ has messages — Lambda processing failures"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.aggregates_dlq.name
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_alarm_events" {
  alarm_name          = "${var.project_name}-dlq-events-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Events DLQ has messages — Lambda processing failures"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.events_dlq.name
  }
}

# ── Lambda Error Alarms: > 0 errors (1 datapoint) ─────────

resource "aws_cloudwatch_metric_alarm" "lambda_errors_process_aggregates" {
  alarm_name          = "${var.project_name}-lambda-errors-process-aggregates"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "process-aggregates Lambda errors detected"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.process_aggregates.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors_process_events" {
  alarm_name          = "${var.project_name}-lambda-errors-process-events"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "process-events Lambda errors detected"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.process_events.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors_dashboard_api" {
  alarm_name          = "${var.project_name}-lambda-errors-dashboard-api"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "dashboard-api Lambda errors detected"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.dashboard_api.function_name
  }
}

# ── SQS Backlog Alarms: > 1000 for 5 minutes (5 periods) ──

resource "aws_cloudwatch_metric_alarm" "sqs_backlog_aggregates" {
  alarm_name          = "${var.project_name}-sqs-backlog-aggregates"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1000
  alarm_description   = "Aggregates queue depth > 1000 for 5 consecutive minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.aggregates_queue.name
  }
}

resource "aws_cloudwatch_metric_alarm" "sqs_backlog_events" {
  alarm_name          = "${var.project_name}-sqs-backlog-events"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1000
  alarm_description   = "Events queue depth > 1000 for 5 consecutive minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.events_queue.name
  }
}
