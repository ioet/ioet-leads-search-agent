#!/usr/bin/env bash
# Register TaskDefs + WfSpecs with LittleHorse.
#
# Prod / remote (AWS creds required):
#   ./scripts/register_lh.sh
#   Loads LHC_API_HOST + OAuth/tenant from Secrets Manager (same secret as ECS).
#   Port/protocol default to 2023 / TLS.
#
# Local standalone (docker-compose littlehorse, no AWS):
#   ./scripts/register_lh.sh --local
#   Uses localhost:2023 PLAINTEXT and clears OAuth so LHConfig does not call Cloud.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

LOCAL=0
if [[ "${1:-}" == "--local" || "${1:-}" == "-l" ]]; then
  LOCAL=1
fi

if [[ "$LOCAL" -eq 1 ]]; then
  # Prefer explicit local overrides over anything leftover in the shell / Secrets Manager.
  export LHC_API_HOST="${LHC_API_HOST:-localhost}"
  export LHC_API_PORT="${LHC_API_PORT:-2023}"
  export LHC_API_PROTOCOL="${LHC_API_PROTOCOL:-PLAINTEXT}"
  unset LHC_OAUTH_CLIENT_ID LHC_OAUTH_CLIENT_SECRET LHC_OAUTH_ACCESS_TOKEN_URL LHC_TENANT_ID
  # Keep dotenv from re-introducing remote OAuth if someone added it to .env.
  export LHC_OAUTH_CLIENT_ID=""
  export LHC_OAUTH_CLIENT_SECRET=""
  export LHC_OAUTH_ACCESS_TOKEN_URL=""
  export LHC_TENANT_ID=""

  cd "$ROOT"
  echo "Registering LittleHorse TaskDefs + WfSpecs against ${LHC_API_HOST}:${LHC_API_PORT} (${LHC_API_PROTOCOL}) [local]"
  exec "${ROOT}/.venv/bin/python" workflow/register.py
fi

# shellcheck source=aws_from_tfvars.sh
source "$ROOT/scripts/aws_from_tfvars.sh"

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
  echo "For local standalone: ./scripts/register_lh.sh --local" >&2
  exit 1
fi

cd "$ROOT"
echo "Registering LittleHorse TaskDefs + WfSpecs against ${LHC_API_HOST}:${LHC_API_PORT} (${LHC_API_PROTOCOL})"
exec "${ROOT}/.venv/bin/python" workflow/register.py
