#!/usr/bin/env python3
"""End-to-end local demo: mocks + real Bedrock agent.

Run mocks first (./mocks/run_mocks.sh) and agent on :8002, or use ./mocks/run_local_stack.sh.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.common.icp import load_icp

APOLLO_URL = os.environ.get("MOCK_APOLLO_URL", "http://127.0.0.1:8001")
BAMBOO_URL = os.environ.get("MOCK_BAMBOO_URL", "http://127.0.0.1:8003")
HUBSPOT_URL = os.environ.get("MOCK_HUBSPOT_URL", "http://127.0.0.1:8004")
JOBS_URL = os.environ.get("MOCK_JOBS_URL", "http://127.0.0.1:8006")
AGENT_URL = os.environ.get("AGENT_URL", "http://127.0.0.1:8002")


def _pp(title: str, payload: Any) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(json.dumps(payload, indent=2, default=str))


def _post(base: str, path: str, payload: dict) -> Any:
    url = f"{base.rstrip('/')}{path}"
    print(f"\n>> POST {url}")
    response = requests.post(url, json=payload, timeout=120)
    print(f"<< {response.status_code}")
    if not response.ok:
        print(response.text)
        response.raise_for_status()
    return response.json()


def _health(base: str, name: str) -> None:
    url = f"{base.rstrip('/')}/health"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    print(f"OK {name}: {response.json()}")


def main() -> None:
    icp = load_icp()
    print("Local demo — mocks + real Bedrock agent")
    print(f"ICP version: {icp.version}")

    for base, name in [
        (APOLLO_URL, "apollo"),
        (BAMBOO_URL, "bamboo/skills"),
        (HUBSPOT_URL, "hubspot"),
        (JOBS_URL, "jobs"),
        (AGENT_URL, "agent"),
    ]:
        _health(base, name)

    # 1) Apollo — discover companies
    companies = _post(
        APOLLO_URL,
        "/v1/search-companies",
        {
            "icp_version": icp.version,
            "segment_ids": ["primary"],
            "max_results": 3,
        },
    )
    _pp("Step 1 — Apollo returned companies", companies)

    # 2) Agent + Bedrock — score against ICP
    scored = _post(
        AGENT_URL,
        "/v1/score-companies",
        {"icp_version": icp.version, "companies": companies},
    )
    _pp("Step 2 — Agent (Bedrock) scored companies", scored)

    top = max(scored, key=lambda c: float(c.get("icp_score") or 0))
    print(f"\nTop lead: {top.get('name')} (score={top.get('icp_score')})")

    # 3) Apollo — decision makers
    contacts = _post(
        APOLLO_URL,
        "/v1/find-decision-makers",
        {"company": top, "icp_version": icp.version},
    )
    _pp("Step 3 — Apollo returned contacts", contacts)

    lead = {
        "company": top,
        "contacts": contacts,
        "skill_matches": [],
        "hubspot_ids": {},
        "status": "enriched",
        "notes": None,
    }

    # 4) HubSpot — sanitize (local, no CRM write)
    lead = _post(HUBSPOT_URL, "/v1/sanitize-public-fields", {"lead": lead})
    _pp("Step 4 — HubSpot sanitized lead", lead)

    # 5) Jobs — discover postings + extract required skills
    lead = _post(JOBS_URL, "/v1/extract-job-skills", lead)
    _pp("Step 5 — Jobs extracted required skills", lead)

    # 6) Bamboo catalog + Agent skill match
    print(f"\n>> GET {BAMBOO_URL}/v1/catalog")
    catalog_resp = requests.get(f"{BAMBOO_URL}/v1/catalog", timeout=120)
    print(f"<< {catalog_resp.status_code}")
    catalog_resp.raise_for_status()
    catalog = catalog_resp.json()
    _pp(f"Step 6a — Bamboo catalog ({len(catalog)} employees)", catalog[:3] if isinstance(catalog, list) else catalog)

    matched = _post(
        AGENT_URL,
        "/v1/match-skills",
        {"lead": lead, "skills_catalog": catalog},
    )
    _pp("Step 6b — Agent (Bedrock) skill matches", matched)

    # 7) Agent + Bedrock — outreach email for HubSpot note
    matched = _post(AGENT_URL, "/v1/draft-outreach-email", {"lead": matched})
    _pp("Step 7 — Agent (Bedrock) drafted outreach email", matched)

    # 8) HubSpot — dry_run upsert = read-only verify (no CRM writes)
    print(f"\n>> GET {HUBSPOT_URL}/v1/verify  (read-only key check)")
    verify_resp = requests.get(f"{HUBSPOT_URL}/v1/verify", timeout=30)
    print(f"<< {verify_resp.status_code}")
    if not verify_resp.ok:
        print(verify_resp.text)
        verify_resp.raise_for_status()
    _pp("Step 8a — HubSpot read (verify)", verify_resp.json())

    published = _post(
        HUBSPOT_URL,
        "/v1/upsert-lead",
        {"lead": matched, "dry_run": True},
    )
    _pp("Step 8b — HubSpot dry_run upsert (read + synthetic ids, no writes)", published)

    store_resp = requests.get(f"{HUBSPOT_URL}/v1/store", timeout=10)
    if store_resp.ok:
        _pp("HubSpot mock CRM store", store_resp.json())
    else:
        print("\n(real HubSpot — no /v1/store; CRM was not written)")

    print("\nDemo complete.")


if __name__ == "__main__":
    main()
