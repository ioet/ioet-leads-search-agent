#!/usr/bin/env bash
# Point all service Lambdas at the current :latest services image digest and
# force an ECS redeploy (so MUTABLE :latest actually rolls out).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=aws_from_tfvars.sh
source "$ROOT/scripts/aws_from_tfvars.sh"

AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-leads-search-agent}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
TAG="${1:-latest}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
SERVICES_REPO_NAME="${PROJECT_NAME}-${ENVIRONMENT}-services"
SERVICES_REPO="${SERVICES_REPO:-${REGISTRY}/${SERVICES_REPO_NAME}}"

DIGEST="$(aws ecr describe-images \
  --region "${AWS_REGION}" \
  --repository-name "${SERVICES_REPO_NAME}" \
  --image-ids "imageTag=${TAG}" \
  --query 'imageDetails[0].imageDigest' \
  --output text)"

if [[ -z "${DIGEST}" || "${DIGEST}" == "None" ]]; then
  echo "No image digest found for ${SERVICES_REPO_NAME}:${TAG}" >&2
  exit 1
fi

SERVICES_URI="${SERVICES_REPO}@${DIGEST}"
echo "Using services image ${SERVICES_URI}"

PREFIX="${PROJECT_NAME}-${ENVIRONMENT}"
for name in apollo agent skills hubspot notify jobs icp; do
  echo "Updating Lambda ${PREFIX}-${name}"
  aws lambda update-function-code \
    --region "${AWS_REGION}" \
    --function-name "${PREFIX}-${name}" \
    --image-uri "${SERVICES_URI}" \
    --output text \
    --query 'FunctionArn'
done

echo "Forcing ECS deployment ${PREFIX}/${PREFIX}-workers"
aws ecs update-service \
  --region "${AWS_REGION}" \
  --cluster "${PREFIX}" \
  --service "${PREFIX}-workers" \
  --force-new-deployment \
  --output text \
  --query 'service.serviceName'

echo "Done."
