variable "aws_region" {
  type        = string
  description = "AWS region for all resources"
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Project name used in resource naming and tags"
  default     = "leads-search-agent"
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
  default     = "dev"
}

variable "bedrock_model_id" {
  type        = string
  description = "Bedrock model ID for agent-service"
  default     = "amazon.nova-pro-v1:0"
}
