# Main Terraform configuration for Smart Traffic IoT
terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ============== VARIABLES ==============

variable "aws_region" {
  default = "us-east-1"
}

variable "project_name" {
  default = "smart-traffic"
}

variable "environment" {
  default = "dev"
}

# ============== IAM ROLES ==============

# Fog Node Role
resource "aws_iam_role" "fog_node_role" {
  name = "${var.project_name}-fog-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "fog_node_policy" {
  name = "${var.project_name}-fog-node-policy"
  role = aws_iam_role.fog_node_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueUrl",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.aggregates_queue.arn,
          aws_sqs_queue.events_queue.arn
        ]
      }
    ]
  })
}

# Lambda Execution Role — Process Aggregates
resource "aws_iam_role" "process_aggregates_role" {
  name = "${var.project_name}-process-aggregates-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "process_aggregates_policy" {
  name = "${var.project_name}-process-aggregates-policy"
  role = aws_iam_role.process_aggregates_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SQSConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [aws_sqs_queue.aggregates_queue.arn]
      },
      {
        Sid    = "DynamoDBWrite"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.aggregates_table.arn]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-process-aggregates:*"]
      }
    ]
  })
}

# Lambda Execution Role — Process Events
resource "aws_iam_role" "process_events_role" {
  name = "${var.project_name}-process-events-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "process_events_policy" {
  name = "${var.project_name}-process-events-policy"
  role = aws_iam_role.process_events_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SQSConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [aws_sqs_queue.events_queue.arn]
      },
      {
        Sid    = "DynamoDBWriteAndQuery"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.events_table.arn,
          aws_dynamodb_table.kpis_table.arn
        ]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-process-events:*"]
      }
    ]
  })
}

# Lambda Execution Role — Dashboard API (read-only)
resource "aws_iam_role" "dashboard_api_role" {
  name = "${var.project_name}-dashboard-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "dashboard_api_policy" {
  name = "${var.project_name}-dashboard-api-policy"
  role = aws_iam_role.dashboard_api_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBReadOnly"
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem"
        ]
        Resource = [
          aws_dynamodb_table.aggregates_table.arn,
          aws_dynamodb_table.events_table.arn,
          aws_dynamodb_table.kpis_table.arn
        ]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-dashboard-api:*"]
      }
    ]
  })
}

# API Gateway Execution Role
resource "aws_iam_role" "api_gateway_role" {
  name = "${var.project_name}-api-gateway-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "api_gateway_policy" {
  name = "${var.project_name}-api-gateway-policy"
  role = aws_iam_role.api_gateway_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [aws_lambda_function.dashboard_api.arn]
      }
    ]
  })
}

# ============== SQS QUEUES ==============

# Aggregates Queue (FIFO for ordering)
resource "aws_sqs_queue" "aggregates_dlq" {
  name                      = "${var.project_name}-aggregates-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600  # 14 days
}

resource "aws_sqs_queue" "aggregates_queue" {
  name                       = "${var.project_name}-aggregates-queue.fifo"
  fifo_queue                 = true
  content_based_deduplication = true
  message_retention_seconds  = 345600  # 4 days
  visibility_timeout_seconds = 60

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.aggregates_dlq.arn
    maxReceiveCount     = 3
  })
}

# Events Queue (FIFO)
resource "aws_sqs_queue" "events_dlq" {
  name                      = "${var.project_name}-events-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "events_queue" {
  name                       = "${var.project_name}-events-queue.fifo"
  fifo_queue                 = true
  content_based_deduplication = true
  message_retention_seconds  = 345600
  visibility_timeout_seconds = 60

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.events_dlq.arn
    maxReceiveCount     = 3
  })
}

# ============== DYNAMODB TABLES ==============

resource "aws_dynamodb_table" "aggregates_table" {
  name           = "${var.project_name}-aggregates"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "PK"
  range_key      = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "events_table" {
  name           = "${var.project_name}-events"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "PK"
  range_key      = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "kpis_table" {
  name           = "${var.project_name}-kpis"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "PK"
  range_key      = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Environment = var.environment
  }
}

# ============== LAMBDA FUNCTIONS ==============

# Process Aggregates Lambda
resource "aws_lambda_function" "process_aggregates" {
  filename      = "process_aggregates.zip"
  function_name = "${var.project_name}-process-aggregates"
  role          = aws_iam_role.process_aggregates_role.arn
  handler       = "process_aggregates.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30

  environment {
    variables = {
      AGGREGATES_TABLE_NAME = aws_dynamodb_table.aggregates_table.name
    }
  }
}

# SQS Source Mapping for Aggregates
resource "aws_lambda_event_source_mapping" "aggregates_mapping" {
  event_source_arn = aws_sqs_queue.aggregates_queue.arn
  function_name    = aws_lambda_function.process_aggregates.function_name
  batch_size       = 10
}

# Process Events Lambda
resource "aws_lambda_function" "process_events" {
  filename      = "process_events.zip"
  function_name = "${var.project_name}-process-events"
  role          = aws_iam_role.process_events_role.arn
  handler       = "process_events.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30

  environment {
    variables = {
      EVENTS_TABLE_NAME     = aws_dynamodb_table.events_table.name
      KPIS_TABLE_NAME       = aws_dynamodb_table.kpis_table.name
    }
  }
}

# SQS Source Mapping for Events
resource "aws_lambda_event_source_mapping" "events_mapping" {
  event_source_arn = aws_sqs_queue.events_queue.arn
  function_name    = aws_lambda_function.process_events.function_name
  batch_size       = 10
}

# Dashboard API Lambda
resource "aws_lambda_function" "dashboard_api" {
  filename      = "dashboard_api.zip"
  function_name = "${var.project_name}-dashboard-api"
  role          = aws_iam_role.dashboard_api_role.arn
  handler       = "dashboard_api.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30

  environment {
    variables = {
      AGGREGATES_TABLE_NAME = aws_dynamodb_table.aggregates_table.name
      EVENTS_TABLE_NAME     = aws_dynamodb_table.events_table.name
      KPIS_TABLE_NAME       = aws_dynamodb_table.kpis_table.name
    }
  }
}

# ============== API GATEWAY ==============

resource "aws_api_gateway_rest_api" "dashboard_api" {
  name        = "${var.project_name}-dashboard-api"
  description = "Dashboard API for traffic analytics"
}

resource "aws_api_gateway_resource" "api_resource" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  parent_id   = aws_api_gateway_rest_api.dashboard_api.root_resource_id
  path_part   = "api"
}

resource "aws_api_gateway_method" "aggregates_method" {
  rest_api_id      = aws_api_gateway_rest_api.dashboard_api.id
  resource_id      = aws_api_gateway_resource.api_resource.id
  http_method      = "GET"
  authorization    = "NONE"
}

resource "aws_api_gateway_integration" "aggregates_integration" {
  rest_api_id      = aws_api_gateway_rest_api.dashboard_api.id
  resource_id      = aws_api_gateway_resource.api_resource.id
  http_method      = aws_api_gateway_method.aggregates_method.http_method
  type             = "AWS_PROXY"
  uri              = aws_lambda_function.dashboard_api.invoke_arn
  integration_http_method = "POST"
}

resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dashboard_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.dashboard_api.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "deployment" {
  rest_api_id = aws_api_gateway_rest_api.dashboard_api.id
  stage_name  = var.environment

  depends_on = [
    aws_api_gateway_integration.aggregates_integration
  ]
}

# ============== S3 FOR DASHBOARD ==============

resource "aws_s3_bucket" "dashboard_bucket" {
  bucket = "${var.project_name}-dashboard-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "dashboard_versioning" {
  bucket = aws_s3_bucket.dashboard_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "dashboard_public_access" {
  bucket = aws_s3_bucket.dashboard_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# ============== CLOUDFRONT DISTRIBUTION ==============

resource "aws_cloudfront_distribution" "dashboard_distribution" {
  origin {
    domain_name = aws_s3_bucket.dashboard_bucket.bucket_regional_domain_name
    origin_id   = "dashboard"
  }

  enabled = true
  default_root_object = "index.html"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "dashboard"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# ============== DATA SOURCES ==============

data "aws_caller_identity" "current" {}

# ============== OUTPUTS ==============

output "aggregates_queue_url" {
  value = aws_sqs_queue.aggregates_queue.url
}

output "events_queue_url" {
  value = aws_sqs_queue.events_queue.url
}

output "api_gateway_endpoint" {
  value = aws_api_gateway_deployment.deployment.invoke_url
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard_bucket.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.dashboard_distribution.domain_name
}
