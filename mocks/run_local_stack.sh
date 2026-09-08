#!/usr/bin/env bash
# Start mocks + real agent-service, run end-to-end demo, then stop everything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

PYTHON="${PYTHON:-python3.13}"
if ! command -v "$PYTHON" &>/dev/null; then
  PYTHON=python3
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PIDS=()

cleanup() {
  echo ""
  echo "Stopping local stack..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT INT TERM

start() {
  local name="$1"
  local module="$2"
  local port="$3"
  echo "Starting ${name} on :${port}"
  "$PYTHON" -m uvicorn "$module" --host 127.0.0.1 --port "$port" --log-level warning &
  PIDS+=("$!")
  sleep 0.5
}

wait_health() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 30); do
    if curl -sf "$url" >/dev/null; then
      echo "  ${label} ready"
      return 0
    fi
    sleep 0.2
  done
  echo "Timed out waiting for ${label} at ${url}" >&2
  exit 1
}

if [[ -n "${APOLLO_API_KEY:-}" ]]; then
  start "apollo (real)" "services.apollo.app:app" 8001
  APOLLO_LABEL="apollo (real)"
else
  start "apollo-mock" "mocks.apollo.app:app" 8001
  APOLLO_LABEL="apollo-mock"
fi
if [[ -n "${BAMBOOHR_API_KEY:-}" && -n "${BAMBOOHR_SUBDOMAIN:-}" ]]; then
  start "bamboo (real)" "services.skills.app:app" 8003
  BAMBOO_LABEL="bamboo (real)"
else
  start "bamboo-mock" "mocks.bamboo.app:app" 8003
  BAMBOO_LABEL="bamboo-mock"
fi
if [[ -n "${HUBSPOT_SERVICE_KEY:-}" ]]; then
  export HUBSPOT_BASE_URL="${HUBSPOT_BASE_URL:-https://api.hubapi.com}"
  start "hubspot (real)" "services.hubspot.app:app" 8004
  HUBSPOT_LABEL="hubspot (real)"
else
  start "hubspot-mock" "mocks.hubspot.app:app" 8004
  HUBSPOT_LABEL="hubspot-mock"
fi
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  start "notify (real Slack)" "services.notify.app:app" 8005
  NOTIFY_LABEL="notify (real Slack)"
else
  start "notify-mock" "mocks.notify.app:app" 8005
  NOTIFY_LABEL="notify-mock"
fi
start "jobs-mock" "mocks.jobs.app:app" 8006

export SKILLS_SERVICE_URL="${SKILLS_SERVICE_URL:-http://127.0.0.1:8003}"
export AWS_BEDROCK_REGION="${AWS_BEDROCK_REGION:-us-east-1}"
export AWS_BEDROCK_MODEL_ID_HIGH="${AWS_BEDROCK_MODEL_ID_HIGH:-google.gemma-3-27b-it}"
export AWS_BEDROCK_MODEL_ID_LOW="${AWS_BEDROCK_MODEL_ID_LOW:-google.gemma-3-4b-it}"

start "agent (Bedrock)" "services.agent.app:app" 8002

echo "Waiting for services..."
wait_health "http://127.0.0.1:8001/health" "$APOLLO_LABEL"
wait_health "http://127.0.0.1:8003/health" "$BAMBOO_LABEL"
wait_health "http://127.0.0.1:8004/health" "$HUBSPOT_LABEL"
wait_health "http://127.0.0.1:8005/health" "$NOTIFY_LABEL"
wait_health "http://127.0.0.1:8006/health" "jobs-mock"
wait_health "http://127.0.0.1:8002/health" "agent"

echo ""
"$PYTHON" mocks/demo_agent_flow.py "$@"

echo ""
if [[ -n "${HUBSPOT_SERVICE_KEY:-}" ]]; then
  echo "Done. HubSpot key check: curl -s http://127.0.0.1:8004/v1/verify"
else
  echo "Done. Inspect mock CRM: curl http://127.0.0.1:8004/v1/store | python3 -m json.tool"
  echo "Filesystem output: .cache/hubspot-mock/leads/"
fi
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "Slack: real webhook via notify-service"
else
  echo "Notify mock output: .cache/notify-mock/"
fi
