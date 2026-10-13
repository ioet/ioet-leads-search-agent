#!/usr/bin/env bash
# Build and push Lambda services + workers images to ECR (:latest by default).
# Usage (from repo root, with AWS creds):
#   ./scripts/build_and_push.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=aws_from_tfvars.sh
source "$ROOT/scripts/aws_from_tfvars.sh"

TAG="${1:-latest}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-leads-search-agent}"
ENVIRONMENT="${ENVIRONMENT:-prod}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
SERVICES_REPO="${SERVICES_REPO:-${REGISTRY}/${PROJECT_NAME}-${ENVIRONMENT}-services}"
WORKERS_REPO="${WORKERS_REPO:-${REGISTRY}/${PROJECT_NAME}-${ENVIRONMENT}-workers}"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo "Building services Lambda image → ${SERVICES_REPO}:${TAG} (linux/amd64, Docker media types)"
# Lambda rejects BuildKit provenance/SBOM indexes and OCI image lists (common on
# Apple Silicon). Push a single-platform Docker-schema image instead.
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --output=type=image,push=true,oci-mediatypes=false \
  -t "${SERVICES_REPO}:${TAG}" \
  -f Dockerfile.lambda .

echo "Building workers image → ${WORKERS_REPO}:${TAG} (linux/amd64)"
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --output=type=image,push=true,oci-mediatypes=false \
  -t "${WORKERS_REPO}:${TAG}" \
  -f Dockerfile.workers .

echo "Done. Refresh Lambdas / ECS (CI does this automatically), e.g.:"
echo "  aws lambda update-function-code --function-name ${PROJECT_NAME}-${ENVIRONMENT}-apollo --image-uri ${SERVICES_REPO}:${TAG}"
echo "  aws ecs update-service --cluster ${PROJECT_NAME}-${ENVIRONMENT} --service ${PROJECT_NAME}-${ENVIRONMENT}-workers --force-new-deployment"
