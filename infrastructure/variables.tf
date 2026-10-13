variable "aws_access_key_id" {
  type        = string
  description = "AWS access key for Terraform (and the apply helper for CLI / S3 backend)"
  sensitive   = true
}

variable "aws_secret_access_key" {
  type        = string
  description = "AWS secret key for Terraform"
  sensitive   = true
}

variable "aws_session_token" {
  type        = string
  description = "Optional session token (SSO / assumed role). Leave empty if unused."
  default     = null
  sensitive   = true
}

variable "bedrock_model_id_high" {
  type        = string
  description = "Bedrock model for ICP scoring and outreach (HIGH)"
  default     = "google.gemma-3-27b-it"
}

variable "bedrock_model_id_low" {
  type        = string
  description = "Bedrock model for skill extraction/matching (LOW)"
  default     = "google.gemma-3-4b-it"
}

variable "services_image_tag" {
  type        = string
  description = "ECR image tag for the shared services Lambda image (pushed from ioet-leads-search-agent)"
  default     = "latest"
}

variable "workers_image_tag" {
  type        = string
  description = "ECR image tag for the workers container"
  default     = "latest"
}

variable "icp_s3_key" {
  type        = string
  description = "S3 object key where the app repo uploads icp.json"
  default     = "icp/icp.json"
}

variable "littlehorse_port" {
  type        = number
  description = "LittleHorse Cloud API gRPC port"
  default     = 2023
}

variable "littlehorse_use_tls" {
  type        = bool
  description = "Use TLS for LH Cloud"
  default     = true
}

variable "workers_desired_count" {
  type        = number
  description = "Desired ECS Fargate tasks for LH workers"
  default     = 1
}

variable "workers_cpu" {
  type        = number
  description = "Fargate CPU units for workers (1024 = 1 vCPU)"
  default     = 512
}

variable "workers_memory" {
  type        = number
  description = "Fargate memory (MiB) for workers"
  default     = 1024
}

variable "function_url_auth_type" {
  type        = string
  description = "Lambda Function URL auth: NONE (simple) or AWS_IAM"
  default     = "NONE"

  validation {
    condition     = contains(["NONE", "AWS_IAM"], var.function_url_auth_type)
    error_message = "function_url_auth_type must be NONE or AWS_IAM"
  }
}

variable "github_org" {
  type        = string
  description = "GitHub org allowed to assume the image-push role"
  default     = "ioet"
}

variable "github_repo" {
  type        = string
  description = "GitHub repo name allowed to assume the image-push role"
  default     = "ioet-leads-search-agent"
}
