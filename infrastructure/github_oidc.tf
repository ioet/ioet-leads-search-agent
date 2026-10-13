# GitHub Actions role for ioet-leads-search-agent (image push + deploy refresh).
# Reuse the account GitHub OIDC provider (one per URL; do not create a second).

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    sid     = "GitHubActionsOidc"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${local.prefix}-github-actions"
  description        = "CI role for ${var.github_org}/${var.github_repo} (ECR push, Lambda/ECS refresh)"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

data "aws_iam_policy_document" "github_actions" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      aws_ecr_repository.services.arn,
      aws_ecr_repository.workers.arn,
    ]
  }

  statement {
    sid = "LambdaRefresh"
    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:UpdateFunctionCode",
    ]
    resources = [
      for name in keys(local.lambda_services) :
      "arn:aws:lambda:${local.region}:${data.aws_caller_identity.current.account_id}:function:${local.prefix}-${name}"
    ]
  }

  statement {
    sid = "EcsRefresh"
    actions = [
      "ecs:DescribeClusters",
      "ecs:DescribeServices",
      "ecs:UpdateService",
    ]
    resources = [
      "arn:aws:ecs:${local.region}:${data.aws_caller_identity.current.account_id}:cluster/${local.prefix}",
      "arn:aws:ecs:${local.region}:${data.aws_caller_identity.current.account_id}:service/${local.prefix}/${local.prefix}-workers",
    ]
  }

  statement {
    sid       = "EcsDescribeTaskDefinition"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid = "IcpUpload"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
    ]
    resources = ["${aws_s3_bucket.icp.arn}/*"]
  }

  statement {
    sid       = "IcpList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.icp.arn]
  }

  statement {
    sid       = "ReadAppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }

  statement {
    sid = "WebBucketDeploy"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.web.arn}/*"]
  }

  statement {
    sid       = "WebBucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.web.arn]
  }

  statement {
    sid = "CloudFrontInvalidate"
    actions = [
      "cloudfront:CreateInvalidation",
      "cloudfront:GetInvalidation",
      "cloudfront:GetDistribution",
    ]
    resources = [aws_cloudfront_distribution.web.arn]
  }

  statement {
    sid     = "LambdaUrlForWebBuild"
    actions = ["lambda:GetFunctionUrlConfig"]
    resources = [
      "arn:aws:lambda:${local.region}:${data.aws_caller_identity.current.account_id}:function:${local.prefix}-icp"
    ]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${local.prefix}-github-actions"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions.json
}
