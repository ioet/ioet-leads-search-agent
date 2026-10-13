locals {
  lambda_services = {
    apollo = {
      handler_command = ["services.apollo.lambda_handler.handler"]
      description     = "Apollo company/contact search"
      timeout         = 120
      memory_size     = 512
      env = {
        APOLLO_BASE_URL = "https://api.apollo.io/api/v1"
        ICP_S3_BUCKET   = aws_s3_bucket.icp.id
        ICP_S3_KEY      = var.icp_s3_key
      }
      bedrock = false
    }
    agent = {
      handler_command = ["services.agent.lambda_handler.handler"]
      description     = "Bedrock ICP scoring, skill match, outreach"
      timeout         = 300
      memory_size     = 1024
      env = {
        AWS_BEDROCK_REGION        = local.region
        AWS_BEDROCK_MODEL_ID_HIGH = var.bedrock_model_id_high
        AWS_BEDROCK_MODEL_ID_LOW  = var.bedrock_model_id_low
        ICP_S3_BUCKET             = aws_s3_bucket.icp.id
        ICP_S3_KEY                = var.icp_s3_key
      }
      bedrock = true
    }
    skills = {
      handler_command = ["services.skills.lambda_handler.handler"]
      description     = "BambooHR skills catalog"
      timeout         = 180
      memory_size     = 512
      env = {
        BAMBOOHR_SKILLS_FIELD      = "skills"
        BAMBOOHR_CACHE_TTL_SECONDS = "300"
        BAMBOOHR_FETCH_DETAILS     = "true"
      }
      bedrock = false
    }
    hubspot = {
      handler_command = ["services.hubspot.lambda_handler.handler"]
      description     = "HubSpot sanitize + upsert"
      timeout         = 120
      memory_size     = 512
      env = {
        HUBSPOT_BASE_URL = "https://api.hubapi.com"
        ICP_S3_BUCKET    = aws_s3_bucket.icp.id
        ICP_S3_KEY       = var.icp_s3_key
      }
      bedrock = false
    }
    notify = {
      handler_command = ["services.notify.lambda_handler.handler"]
      description     = "Slack notify + failure alerts"
      timeout         = 30
      memory_size     = 256
      env             = {}
      bedrock         = false
    }
    jobs = {
      handler_command = ["services.jobs.lambda_handler.handler"]
      description     = "Job posting scrape + skill extraction"
      timeout         = 180
      memory_size     = 1024
      env = {
        AWS_BEDROCK_REGION       = local.region
        AWS_BEDROCK_MODEL_ID_LOW = var.bedrock_model_id_low
        JOB_POSTING_SOURCES      = "linkedin,company_website"
      }
      bedrock = true
    }
    icp = {
      handler_command = ["services.icp.lambda_handler.handler"]
      description     = "ICP PDF extract + publish to S3"
      timeout         = 180
      memory_size     = 1024
      env = {
        AWS_BEDROCK_REGION        = local.region
        AWS_BEDROCK_MODEL_ID_HIGH = var.bedrock_model_id_high
        ICP_S3_BUCKET             = aws_s3_bucket.icp.id
        ICP_S3_KEY                = var.icp_s3_key
        ICP_S3_CACHE_TTL_SECONDS  = "60"
      }
      bedrock = true
    }
  }

  # JSON keys ECS injects into workers at task start (not read by Terraform).
  worker_secret_keys = [
    "LHC_API_HOST",
    "LHC_OAUTH_CLIENT_ID",
    "LHC_OAUTH_CLIENT_SECRET",
    "LHC_OAUTH_ACCESS_TOKEN_URL",
    "LHC_TENANT_ID",
  ]
}
