resource "aws_secretsmanager_secret" "app" {
  name        = "${local.prefix}/app"
  description = "API keys, LHC_API_HOST, and LH OAuth for leads-search-agent (${local.environment})"
}

# Placeholder keys only. Fill values in the AWS console (or CLI).
# Terraform never reads the secret back; Lambdas/ECS fetch it at runtime.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    APOLLO_API_KEY             = ""
    HUBSPOT_SERVICE_KEY        = ""
    BAMBOOHR_API_KEY           = ""
    BAMBOOHR_SUBDOMAIN         = ""
    SLACK_WEBHOOK_URL          = ""
    AWS_BEDROCK_API_KEY        = ""
    LINKEDIN_JOBS_ACCESS_TOKEN = ""
    LHC_API_HOST               = ""
    LHC_OAUTH_CLIENT_ID        = ""
    LHC_OAUTH_CLIENT_SECRET    = ""
    LHC_OAUTH_ACCESS_TOKEN_URL = ""
    LHC_TENANT_ID              = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
