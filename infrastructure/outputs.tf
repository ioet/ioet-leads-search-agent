output "ecr_services_repository_url" {
  description = "ECR repo for the shared Lambda services image"
  value       = aws_ecr_repository.services.repository_url
}

output "ecr_workers_repository_url" {
  description = "ECR repo for the workers image"
  value       = aws_ecr_repository.workers.repository_url
}

output "secret_arn" {
  description = "Secrets Manager ARN — fill API keys, LHC_API_HOST, and LH Cloud OAuth here"
  value       = aws_secretsmanager_secret.app.arn
}

output "icp_bucket" {
  description = "S3 bucket for icp.json and skills catalogs (app repo uploads icp.json)"
  value       = aws_s3_bucket.icp.id
}

output "icp_s3_key" {
  description = "Expected object key for icp.json"
  value       = var.icp_s3_key
}

output "cloudfront_url" {
  description = "HTTPS URL of the ICP admin CloudFront distribution"
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (CI invalidation)"
  value       = aws_cloudfront_distribution.web.id
}

output "web_bucket" {
  description = "S3 bucket for the ICP admin SPA"
  value       = aws_s3_bucket.web.id
}

output "function_urls" {
  description = "HTTPS base URLs for each microservice"
  value = {
    for name, url in aws_lambda_function_url.service :
    name => trimsuffix(url.function_url, "/")
  }
}

output "worker_service_urls" {
  description = "Env mapping injected into ECS workers"
  value = {
    SERVICE_URL_SEARCH_COMPANIES       = trimsuffix(aws_lambda_function_url.service["apollo"].function_url, "/")
    SERVICE_URL_FIND_DECISION_MAKERS   = trimsuffix(aws_lambda_function_url.service["apollo"].function_url, "/")
    SERVICE_URL_SCORE_COMPANIES_ICP    = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/")
    SERVICE_URL_MATCH_IOET_SKILLS      = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/")
    SERVICE_URL_DRAFT_OUTREACH_EMAIL   = trimsuffix(aws_lambda_function_url.service["agent"].function_url, "/")
    SERVICE_URL_SANITIZE_PUBLIC_FIELDS = trimsuffix(aws_lambda_function_url.service["hubspot"].function_url, "/")
    SERVICE_URL_UPSERT_HUBSPOT         = trimsuffix(aws_lambda_function_url.service["hubspot"].function_url, "/")
    SERVICE_URL_NOTIFY                 = trimsuffix(aws_lambda_function_url.service["notify"].function_url, "/")
    SERVICE_URL_NOTIFY_FAILURE         = trimsuffix(aws_lambda_function_url.service["notify"].function_url, "/")
    SERVICE_URL_EXTRACT_JOB_SKILLS     = trimsuffix(aws_lambda_function_url.service["jobs"].function_url, "/")
    SKILLS_SERVICE_URL                 = trimsuffix(aws_lambda_function_url.service["skills"].function_url, "/")
  }
}

output "littlehorse_cloud" {
  description = "Non-secret LH Cloud settings. Host (LHC_API_HOST) is in Secrets Manager."
  value = {
    port     = var.littlehorse_port
    protocol = var.littlehorse_use_tls ? "TLS" : "PLAINTEXT"
  }
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_workers_service_name" {
  value = aws_ecs_service.workers.name
}

output "github_actions_role_arn" {
  description = "OIDC role ARN for GitHub secret AWS_ROLE_ARN in ioet-leads-search-agent"
  value       = aws_iam_role.github_actions.arn
}
