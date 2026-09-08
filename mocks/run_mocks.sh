#!/usr/bin/env bash
# Start Bamboo/HubSpot/Notify/Jobs mocks locally.
# Apollo: real when APOLLO_API_KEY is set; Bamboo when BAMBOOHR_API_KEY+SUBDOMAIN;
# HubSpot when HUBSPOT_SERVICE_KEY; Notify when SLACK_WEBHOOK_URL.
# Real HubSpot: dry_run=true does a read-only verify (no CRM writes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON="${PYTHON:-python3.13}"
if ! command -v "$PYTHON" &>/dev/null; then
  PYTHON=python3
fi

PIDS=()

cleanup() {
  echo ""
  echo "Stopping mock services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT INT TERM

start_mock() {
  local name="$1"
  local module="$2"
  local port="$3"
  echo "Starting ${name} on http://127.0.0.1:${port}"
  "$PYTHON" -m uvicorn "$module" --host 127.0.0.1 --port "$port" --log-level info &
  PIDS+=("$!")
  sleep 0.4
}

if [[ -n "${APOLLO_API_KEY:-}" ]]; then
  start_mock "apollo (real)" "services.apollo.app:app" 8001
  APOLLO_LABEL="Apollo (real API)"
else
  start_mock "apollo-mock" "mocks.apollo.app:app" 8001
  APOLLO_LABEL="Apollo (mock)"
fi
if [[ -n "${BAMBOOHR_API_KEY:-}" && -n "${BAMBOOHR_SUBDOMAIN:-}" ]]; then
  start_mock "bamboo (real)" "services.skills.app:app" 8003
  BAMBOO_LABEL="Bamboo (real API)"
else
  start_mock "bamboo-mock" "mocks.bamboo.app:app" 8003
  BAMBOO_LABEL="Bamboo (mock)"
fi
if [[ -n "${HUBSPOT_SERVICE_KEY:-}" ]]; then
  export HUBSPOT_BASE_URL="${HUBSPOT_BASE_URL:-https://api.hubapi.com}"
  start_mock "hubspot (real)" "services.hubspot.app:app" 8004
  HUBSPOT_LABEL="HubSpot (real API)"
else
  start_mock "hubspot-mock" "mocks.hubspot.app:app" 8004
  HUBSPOT_LABEL="HubSpot (mock)"
fi
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  start_mock "notify (real Slack)" "services.notify.app:app" 8005
  NOTIFY_LABEL="Notify (real Slack)"
else
  start_mock "notify-mock" "mocks.notify.app:app" 8005
  NOTIFY_LABEL="Notify (mock)"
fi
start_mock "jobs-mock" "mocks.jobs.app:app" 8006

echo ""
echo "Stack running (Ctrl+C to stop):"
echo "  ${APOLLO_LABEL}  http://127.0.0.1:8001/health"
echo "  ${BAMBOO_LABEL}  http://127.0.0.1:8003/health"
echo "  ${HUBSPOT_LABEL} http://127.0.0.1:8004/health"
echo "  ${NOTIFY_LABEL} http://127.0.0.1:8005/health"
echo "  Jobs (mock)      http://127.0.0.1:8006/health"
echo ""
if [[ -n "${HUBSPOT_SERVICE_KEY:-}" ]]; then
  echo "HubSpot key check (read-only): curl -s http://127.0.0.1:8004/v1/verify"
else
  echo "HubSpot mock writes upserts to .cache/hubspot-mock/leads/"
fi
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "Slack: real webhook via notify-service (SLACK_WEBHOOK_URL)"
else
  echo "Notify mock writes Slack text to .cache/notify-mock/"
fi
echo ""
echo "Next — real agent (Bedrock) in another terminal:"
echo "  export SKILLS_SERVICE_URL=http://127.0.0.1:8003"
echo "  uvicorn services.agent.app:app --host 127.0.0.1 --port 8002 --reload"
echo ""

wait
