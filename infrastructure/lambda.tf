resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.lambda_services

  name              = "/aws/lambda/${local.prefix}-${each.key}"
  retention_in_days = 30
}

locals {
  services_image_uri = "${aws_ecr_repository.services.repository_url}:${var.services_image_tag}"
}

resource "aws_lambda_function" "service" {
  for_each = local.lambda_services

  function_name = "${local.prefix}-${each.key}"
  role          = aws_iam_role.lambda[each.key].arn
  package_type  = "Image"
  image_uri     = local.services_image_uri
  architectures = ["x86_64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory_size
  description   = each.value.description

  image_config {
    command = each.value.handler_command
  }

  environment {
    variables = merge(
      each.value.env,
      {
        APP_SECRET_ARN = aws_secretsmanager_secret.app.arn
      },
    )
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_service,
    aws_secretsmanager_secret_version.app,
  ]
}

resource "aws_lambda_function_url" "service" {
  for_each = local.lambda_services

  function_name      = aws_lambda_function.service[each.key].function_name
  authorization_type = var.function_url_auth_type

  cors {
    allow_origins = ["*"]
    allow_methods = ["*"]
    allow_headers = ["*"]
    max_age       = 86400
  }
}
