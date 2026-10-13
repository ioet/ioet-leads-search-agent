resource "aws_ecs_cluster" "main" {
  name = local.prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "workers" {
  name              = "/ecs/${local.prefix}-workers"
  retention_in_days = 30
}

resource "aws_security_group" "workers" {
  name        = "${local.prefix}-workers"
  description = "ECS Fargate LH task workers (egress to LH Cloud + Function URLs)"
  vpc_id      = data.aws_vpc.selected.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.prefix}-workers"
  }
}

resource "aws_ecs_task_definition" "workers" {
  family                   = "${local.prefix}-workers"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.workers_cpu
  memory                   = var.workers_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "workers"
      image     = "${aws_ecr_repository.workers.repository_url}:${var.workers_image_tag}"
      essential = true
      environment = [
        { name = "LHC_API_PORT", value = tostring(var.littlehorse_port) },
        { name = "LHC_API_PROTOCOL", value = var.littlehorse_use_tls ? "TLS" : "PLAINTEXT" },
        { name = "SERVICE_URL_SEARCH_COMPANIES", value = trimsuffix(aws_lambda_function_url.service["apollo"].function_url, "/") },
        { name = "SERVICE_URL_FIND_DECISION_MAKERS", value = trimsuffix(aws_lambda_function_url.service["apollo"].function_url, "/") },
        { name = "SERVICE_URL_SCORE_COMPANIES_ICP", value = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/") },
        { name = "SERVICE_URL_MATCH_IOET_SKILLS", value = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/") },
        { name = "SERVICE_URL_DRAFT_OUTREACH_EMAIL", value = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/") },
        { name = "SERVICE_URL_SANITIZE_PUBLIC_FIELDS", value = trimsuffix(aws_lambda_function_url.service["hubspot"].function_url, "/") },
        { name = "SERVICE_URL_UPSERT_HUBSPOT", value = trimsuffix(aws_lambda_function_url.service["hubspot"].function_url, "/") },
        { name = "SERVICE_URL_NOTIFY", value = trimsuffix(aws_lambda_function_url.service["notify"].function_url, "/") },
        { name = "SERVICE_URL_NOTIFY_FAILURE", value = trimsuffix(aws_lambda_function_url.service["notify"].function_url, "/") },
        { name = "SERVICE_URL_EXTRACT_JOB_SKILLS", value = trimsuffix(aws_lambda_function_url.service["jobs"].function_url, "/") },
        { name = "SKILLS_SERVICE_URL", value = trimsuffix(aws_lambda_function_url.service["skills"].function_url, "/") },
        { name = "SKILLS_CATALOG_S3_BUCKET", value = aws_s3_bucket.icp.id },
        { name = "SKILLS_CATALOG_STORAGE", value = "s3" },
        { name = "APP_SECRET_ARN", value = aws_secretsmanager_secret.app.arn },
        { name = "MAX_COMPANIES", value = "3" },
        { name = "MAX_CONTACTS_PER_COMPANY", value = "1" },
        { name = "TASK_TIMEOUT_SECONDS", value = "120" },
        { name = "TASK_RETRIES", value = "3" },
      ]
      secrets = [
        for key in local.worker_secret_keys : {
          name      = key
          valueFrom = "${aws_secretsmanager_secret.app.arn}:${key}::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.workers.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "workers"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "workers" {
  name                    = "${local.prefix}-workers"
  cluster                 = aws_ecs_cluster.main.id
  task_definition         = aws_ecs_task_definition.workers.arn
  desired_count           = var.workers_desired_count
  launch_type             = "FARGATE"
  propagate_tags          = "SERVICE"
  enable_ecs_managed_tags = true

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.workers.id]
    assign_public_ip = true
  }

  depends_on = [
    aws_lambda_function_url.service,
    aws_secretsmanager_secret_version.app,
  ]
}
