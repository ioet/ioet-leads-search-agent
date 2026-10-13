terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
  }

  backend "s3" {
    bucket  = "apps-tfstate-bucket-f"
    key     = "infra-terraform/ioet-primary/ioet-leads-search/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region                   = local.region
  access_key               = var.aws_access_key_id
  secret_key               = var.aws_secret_access_key
  token                    = var.aws_session_token == null || var.aws_session_token == "" ? null : var.aws_session_token
  shared_config_files      = []
  shared_credentials_files = []

  default_tags {
    tags = {
      application         = local.name
      service             = local.name
      application-service = local.name
      environment         = local.environment
    }
  }
}

locals {
  name        = "leads-search-agent"
  environment = "prod"
  prefix      = "${local.name}-${local.environment}"
  region      = "us-east-1"
}

# Networking (account default VPC; Fargate tasks get a public IP)
######################################################################
data "aws_caller_identity" "current" {}

data "aws_vpc" "selected" {
  default = true
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}
