#!/usr/bin/env bash
# Provision AWS infra from infrastructure/ using credentials in terraform.tfvars.
# Same stack as infra-terraform/ioet-primary/ioet-leads-search (shared S3 state).
#
# Usage (from repo root):
#   cp infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
#   # fill aws_access_key_id / aws_secret_access_key
#   ./scripts/apply_infra.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure"
# shellcheck source=aws_from_tfvars.sh
source "$ROOT/scripts/aws_from_tfvars.sh"

cd "$TF_DIR"
# Reconfigure (do not -migrate-state): this dir was often inited with
# -backend=false, and remote state already lives in the ioet-primary S3 bucket.
terraform init -reconfigure

echo "Bootstrapping ECR, GitHub OIDC role, S3 ICP bucket, and Secrets Manager…"
terraform apply -auto-approve \
  -target=aws_ecr_repository.services \
  -target=aws_ecr_repository.workers \
  -target=aws_ecr_lifecycle_policy.services \
  -target=aws_ecr_lifecycle_policy.workers \
  -target=aws_iam_role.github_actions \
  -target=aws_iam_role_policy.github_actions \
  -target=aws_s3_bucket.icp \
  -target=aws_s3_bucket_public_access_block.icp \
  -target=aws_s3_bucket_server_side_encryption_configuration.icp \
  -target=aws_s3_bucket_versioning.icp \
  -target=aws_s3_bucket_policy.icp \
  -target=aws_secretsmanager_secret.app \
  -target=aws_secretsmanager_secret_version.app

echo "Building and pushing :latest images to ECR…"
chmod +x "$ROOT/scripts/build_and_push.sh"
"$ROOT/scripts/build_and_push.sh" latest

echo "Applying remaining resources (Lambdas + ECS)…"
terraform apply -auto-approve

ICP_BUCKET="$(terraform output -raw icp_bucket)"
ICP_KEY="$(terraform output -raw icp_s3_key)"
echo "Uploading data/icp.json → s3://${ICP_BUCKET}/${ICP_KEY}"
aws s3 cp "$ROOT/data/icp.json" "s3://${ICP_BUCKET}/${ICP_KEY}"

echo "Deploying ICP admin SPA to CloudFront…"
chmod +x "$ROOT/scripts/deploy_web.sh"
"$ROOT/scripts/deploy_web.sh"

echo
echo "Infra apply complete."
echo "  github_actions_role_arn: $(terraform output -raw github_actions_role_arn)"
echo "  icp_bucket:              ${ICP_BUCKET}"
echo "  secret_arn:              $(terraform output -raw secret_arn)"
echo "  cloudfront_url:          $(terraform output -raw cloudfront_url)"
echo
echo "Next: fill API keys + LHC_API_HOST / LH OAuth in Secrets Manager, set GitHub"
echo "secret AWS_ROLE_ARN and variables ICP_BUCKET, WEB_BUCKET, CLOUDFRONT_DISTRIBUTION_ID,"
echo "then ./scripts/register_lh.sh"
