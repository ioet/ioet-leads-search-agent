#!/usr/bin/env bash
# Register TaskDefs + WfSpecs with LittleHorse Cloud.
# Loads LHC_API_HOST + OAuth/tenant from Secrets Manager (same secret as ECS).
# Port/protocol default to prod infra values (2023 / TLS); override via env if needed.
#
# Usage (AWS creds required):
#   ./scripts/register_lh.sh
# Local override:
#   export LHC_API_HOST=localhost LHC_API_PORT=2023 LHC_API_PROTOCOL=PLAINTEXT
#   # (skips secret host if already set; still loads OAuth from secret when AWS works)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_NAME="${PROJECT_NAME:-leads-search-agent}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
SECRET_ID="${SECRET_ID:-${PROJECT_NAME}-${ENVIRONMENT}/app}"

export LHC_API_PORT="${LHC_API_PORT:-2023}"
export LHC_API_PROTOCOL="${LHC_API_PROTOCOL:-TLS}"

echo "Fetching LH credentials from Secrets Manager: ${SECRET_ID}"
SECRET_JSON="$(aws secretsmanager get-secret-value \
  --secret-id "${SECRET_ID}" \
  --query SecretString \
  --output text)"
export SECRET_JSON

for key in \
  LHC_API_HOST \
  LHC_OAUTH_CLIENT_ID \
  LHC_OAUTH_CLIENT_SECRET \
  LHC_OAUTH_ACCESS_TOKEN_URL \
  LHC_TENANT_ID
do
  # Do not override a host/protocol already set (local LH).
  if [[ -n "${!key:-}" ]]; then
    continue
  fi
  val="$(python3 -c "import json,os,sys; d=json.loads(os.environ['SECRET_JSON']); print(d.get(sys.argv[1],'') or '')" "$key")"
  if [[ -n "$val" ]]; then
    export "${key}=${val}"
  fi
done
unset SECRET_JSON

if [[ -z "${LHC_API_HOST:-}" ]]; then
  echo "LHC_API_HOST missing: set it in Secrets Manager (${SECRET_ID}) or export it" >&2
  exit 1
fi

cd "$ROOT"
echo "Registering LittleHorse TaskDefs + WfSpecs against ${LHC_API_HOST}:${LHC_API_PORT} (${LHC_API_PROTOCOL})"
exec python workflow/register.py
