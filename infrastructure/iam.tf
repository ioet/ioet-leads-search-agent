data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each = local.lambda_services

  name               = "${local.prefix}-${each.key}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  for_each = local.lambda_services

  role       = aws_iam_role.lambda[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_service" {
  for_each = local.lambda_services

  statement {
    sid     = "ReadAppSecret"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.app.arn,
    ]
  }

  dynamic "statement" {
    for_each = each.value.bedrock ? [1] : []
    content {
      sid = "BedrockInvoke"
      actions = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
      ]
      resources = [
        "arn:aws:bedrock:${local.region}::foundation-model/*",
        "arn:aws:bedrock:${local.region}:${data.aws_caller_identity.current.account_id}:inference-profile/*",
      ]
    }
  }

  dynamic "statement" {
    for_each = contains(["agent", "apollo", "hubspot"], each.key) ? [1] : []
    content {
      sid       = "ReadIcpBucket"
      actions   = ["s3:GetObject"]
      resources = ["${aws_s3_bucket.icp.arn}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "icp" ? [1] : []
    content {
      sid = "WriteIcpBucket"
      actions = [
        "s3:GetObject",
        "s3:PutObject",
      ]
      resources = ["${aws_s3_bucket.icp.arn}/*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "icp" ? [1] : []
    content {
      sid       = "ListIcpBucket"
      actions   = ["s3:ListBucket"]
      resources = [aws_s3_bucket.icp.arn]
    }
  }
}

resource "aws_iam_role_policy" "lambda_service" {
  for_each = local.lambda_services

  name   = "${local.prefix}-${each.key}-policy"
  role   = aws_iam_role.lambda[each.key].id
  policy = data.aws_iam_policy_document.lambda_service[each.key].json
}

# ECS task execution + task roles for workers
data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${local.prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_extra" {
  statement {
    sid       = "ReadSecretsForTaskInjection"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "ecs_execution_extra" {
  name   = "${local.prefix}-ecs-execution-extra"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_extra.json
}

resource "aws_iam_role" "ecs_task" {
  name               = "${local.prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

data "aws_iam_policy_document" "ecs_task" {
  statement {
    sid       = "ReadAppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }

  statement {
    sid = "WriteLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.workers.arn}:*"]
  }

  statement {
    sid = "SkillsCatalogS3"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.icp.arn}/skills-catalogs/*"]
  }

  statement {
    sid       = "ListIcpBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.icp.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task" {
  name   = "${local.prefix}-ecs-task-policy"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task.json
}
