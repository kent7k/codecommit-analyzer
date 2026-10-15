# AgentCore Runtime（対話の受付）と AgentCore Memory（会話の継続）。
# Runtime 自体は microVM で、重い解析は SQS に投げて Fargate に任せる。
#
# 注意: aws_bedrockagentcore_* は provider 6.x 後半。引数名はバージョンで動くので
#       `terraform validate` が落ちたら registry のドキュメントに合わせて直す。

data "aws_caller_identity" "current" {}

# --- ECR ---------------------------------------------------------------------

resource "aws_ecr_repository" "agent" {
  name                 = "${var.project}-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }
}

# --- Logs --------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/${var.project}/agent"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

# --- IAM（Runtime の実行ロール） -----------------------------------------------

data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "agent" {
  name               = "${var.project}-agent-runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
}

data "aws_iam_policy_document" "agent" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "EcrPull"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.agent.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/*", aws_cloudwatch_log_group.agent.arn, "${aws_cloudwatch_log_group.agent.arn}:*"]
  }

  # AgentCore Observability（Transaction Search / ADOT）
  statement {
    sid       = "Telemetry"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "Bedrock"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.bedrock_invoke_arns
  }

  statement {
    sid       = "Enqueue"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [var.queue_arn]
  }

  statement {
    sid       = "ReadResults"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [var.results_bucket_arn, "${var.results_bucket_arn}/*"]
  }

  statement {
    sid       = "Jobs"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
    resources = [var.jobs_table_arn, "${var.jobs_table_arn}/index/*"]
  }

  statement {
    sid       = "Memory"
    actions   = ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents", "bedrock-agentcore:GetEvent", "bedrock-agentcore:RetrieveMemoryRecords", "bedrock-agentcore:ListMemoryRecords"]
    resources = [aws_bedrockagentcore_memory.this.arn]
  }

  statement {
    sid       = "Identity"
    actions   = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"]
    resources = ["arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default", "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/*"]
  }

  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "agent" {
  name   = "agent"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent.json
}

# --- AgentCore Memory --------------------------------------------------------
# 短期（生イベント）だけ。長期の抽出戦略は要るようになってから足す。

resource "aws_bedrockagentcore_memory" "this" {
  name                  = replace("${var.project}_memory", "-", "_")
  description           = "conversation history for ${var.project}"
  event_expiry_duration = var.memory_event_expiry_days
}

# --- AgentCore Runtime -------------------------------------------------------

resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = replace("${var.project}_agent", "-", "_")
  description        = "CodeCommit analyzer front door"
  role_arn           = aws_iam_role.agent.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  lifecycle_configuration {
    idle_runtime_session_timeout = var.idle_timeout_seconds
    max_lifetime                 = var.max_lifetime_seconds
  }

  environment_variables = {
    AWS_REGION       = var.aws_region
    QUEUE_URL        = var.queue_url
    RESULTS_BUCKET   = var.results_bucket
    JOBS_TABLE       = var.jobs_table_name
    BEDROCK_MODEL_ID = var.bedrock_model_id
    MEMORY_ID        = aws_bedrockagentcore_memory.this.id
    LOG_LEVEL        = "INFO"
  }

  depends_on = [aws_iam_role_policy.agent]
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "live" {
  name             = "live"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
}
