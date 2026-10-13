#!/usr/bin/env bash
# Build the ICP admin SPA and sync it to the CloudFront origin bucket.
#
# Usage (from repo root, after terraform apply):
#   ./scripts/deploy_web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure"
# shellcheck source=aws_from_tfvars.sh
source "$ROOT/scripts/aws_from_tfvars.sh"

cd "$TF_DIR"
WEB_BUCKET="$(terraform output -raw web_bucket)"
CF_ID="$(terraform output -raw cloudfront_distribution_id)"
CF_URL="$(terraform output -raw cloudfront_url)"
API_URL="$(terraform output -json function_urls | python3 -c 'import json,sys; print(json.load(sys.stdin)["icp"])')"

cd "$ROOT/web"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
VITE_ICP_API_URL="${API_URL}" npm run build

aws s3 sync dist "s3://${WEB_BUCKET}" --delete
aws cloudfront create-invalidation --distribution-id "${CF_ID}" --paths "/*" >/dev/null

echo "ICP admin deployed: ${CF_URL}"
echo "  API: ${API_URL}"
