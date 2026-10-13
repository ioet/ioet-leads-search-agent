#!/usr/bin/env bash
# Diagnose Bamboo skills catalog (level-based custom fields).
# Requires skills-service on :8003 (real Bamboo). Does not print API keys.
set -euo pipefail
BASE="${SKILLS_SERVICE_URL:-http://127.0.0.1:8003}"

echo "Clearing skills cache..."
curl -s -X POST "$BASE/v1/cache/clear" | tee /tmp/bamboo-cache-clear.json
echo
echo "Probing Bamboo fields via $BASE/v1/debug/bamboo-fields ..."
curl -s -m 180 "$BASE/v1/debug/bamboo-fields" | tee /tmp/bamboo-fields-probe.json
echo
python3 - <<'PY'
import json
from pathlib import Path
p = Path("/tmp/bamboo-fields-probe.json")
data = json.loads(p.read_text())
if "detail" in data and len(data) <= 2 and "employee_id" not in data:
    print("ERROR:", data.get("detail") or data)
    raise SystemExit(1)
print("employee:", data.get("display_name"), data.get("employee_id"))
print("skill_field_count:", data.get("skill_field_count"))
print("detail_key_count:", data.get("detail_key_count"))
print("parsed_skills_count:", data.get("parsed_skills_count"))
print("parsed_skills sample:", (data.get("parsed_skills") or [])[:20])
if data.get("parsed_skills"):
    print("OK — level-based custom fields are working")
else:
    print("ACTION: empty skills — check API permissions / BAMBOOHR_SKILL_FIELDS allowlist")
PY
